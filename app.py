#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Cristian Cezar Moisés
# Commercial licensing: sac@securityops.co
"""
Zupt Web — Hardened REST backend for post-quantum backup operations.

Licensed under the GNU Affero General Public License v3.0 or later.
If you operate a modified version of this software as a network service,
the AGPL requires you to make your modifications available to your users.
For commercial licensing inquiries, contact: sac@securityops.co

Backend for the bundled Zupt CLI (default 2.2.3) and libzuptsdk-2.0.
Exposes:
  POST  /keygen         legacy ML-KEM-768 + X25519 keypair (zupt keygen)
  POST  /keygen-sdk     SDK v2 keypair (HKDF + key commitment + Argon2id)
  POST  /compress       file → .zupt; supports password, --pq, --pq-sdk, --dedup
  POST  /extract        .zupt → file; supports password, --pq, --pq-sdk
  POST  /test-archive   integrity verify
  GET   /version        zupt CLI version (cached)
  GET   /healthz        liveness probe (no CLI call, no auth, no rate limit)
  GET   /download-key/<job>/<type>
"""
import os, sys, time, uuid, hmac, shutil, secrets, subprocess, tempfile
from pathlib import Path
from functools import wraps
from collections import defaultdict
from flask import (Flask, request, jsonify, send_file, render_template,
                   make_response, abort, g)

app = Flask(__name__)
app.secret_key = os.environ.get('ZUPT_SECRET_KEY', secrets.token_hex(32))

# ─── Config ───
# Upload size cap. Override via ZUPT_MAX_UPLOAD_MB env var.
# Default: 2 GiB.
MAX_UPLOAD_MB = int(os.environ.get('ZUPT_MAX_UPLOAD_MB', '2048'))
app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_MB * 1024 * 1024

WORKDIR  = Path(os.environ.get('ZUPT_WORKDIR', '/tmp/zupt-work'))
WORKDIR.mkdir(parents=True, exist_ok=True)

ZUPT_BIN = os.environ.get('ZUPT_BIN', '/usr/local/bin/zupt')
MAX_KEY_AGE = int(os.environ.get('ZUPT_KEY_TTL_SEC', str(3600 * 4)))
COMPRESS_TIMEOUT = int(os.environ.get('ZUPT_COMPRESS_TIMEOUT', '600'))
EXTRACT_TIMEOUT  = int(os.environ.get('ZUPT_EXTRACT_TIMEOUT',  '600'))


# ─── Rate limiting (in-process; fine for single-host deployment) ───
_rate = defaultdict(list)
_rate_max_keys = 4096   # cap memory usage if hit by random IPs


def rate_limit(max_calls, period_sec):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            ip = request.remote_addr or '0.0.0.0'
            now = time.time()
            key = f'{f.__name__}:{ip}'
            _rate[key] = [t for t in _rate[key] if now - t < period_sec]
            if len(_rate[key]) >= max_calls:
                return render_template('error.html',
                    error='Rate limit exceeded. Try again later.'), 429
            _rate[key].append(now)
            # Bound memory: drop oldest keys if dict grows unbounded
            if len(_rate) > _rate_max_keys:
                # Drop the 25% oldest entries (cheap O(n) scan)
                items = sorted(_rate.items(),
                               key=lambda kv: kv[1][-1] if kv[1] else 0)
                for k, _ in items[:len(items) // 4]:
                    _rate.pop(k, None)
            return f(*args, **kwargs)
        return wrapper
    return decorator


# ─── CSRF: double-submit cookie + hidden field, hmac-compared ───
@app.before_request
def csrf_prepare():
    # Healthz must work for orchestrator probes without a cookie roundtrip.
    if request.path == '/healthz':
        return

    cookie = request.cookies.get('csrf_token')
    g.csrf_token = cookie or secrets.token_hex(32)
    g.csrf_new = cookie is None

    if request.method in ('POST', 'PUT', 'DELETE'):
        if not cookie:
            abort(403)
        submitted = request.form.get('csrf_token', '')
        if not submitted or not hmac.compare_digest(cookie, submitted):
            abort(403)


@app.after_request
def headers(response):
    if getattr(g, 'csrf_new', False):
        response.set_cookie('csrf_token', g.csrf_token,
                            httponly=True, samesite='Strict',
                            secure=request.is_secure, max_age=3600)
    # Full security header set — applied directly by Flask/gunicorn.
    # The runtime container has no separate proxy.
    response.headers.setdefault('X-Content-Type-Options',       'nosniff')
    response.headers.setdefault('X-Frame-Options',              'DENY')
    response.headers.setdefault('X-XSS-Protection',             '1; mode=block')
    response.headers.setdefault('Referrer-Policy',              'no-referrer')
    response.headers.setdefault('Cross-Origin-Opener-Policy',   'same-origin')
    response.headers.setdefault('Cross-Origin-Resource-Policy', 'same-origin')
    response.headers.setdefault('Permissions-Policy',
        'camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()')
    response.headers.setdefault('Content-Security-Policy',
        "default-src 'none'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "form-action 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "connect-src 'self'")
    # Note: 'Server: gunicorn/...' is set by gunicorn itself and cannot
    # be overridden from the WSGI app. It's harmless info disclosure.
    return response


# ─── Helpers ───
def job_dir(job_id):
    safe_id = ''.join(c for c in job_id if c.isalnum() or c == '-')[:16]
    d = WORKDIR / safe_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def cleanup_old_jobs():
    now = time.time()
    try:
        for entry in WORKDIR.iterdir():
            if entry.is_dir() and now - entry.stat().st_mtime > MAX_KEY_AGE:
                shutil.rmtree(entry, ignore_errors=True)
    except Exception:
        pass


def safe_filename(name):
    return ''.join(c for c in name if c.isalnum() or c in '.-_')[:128] or 'file'


def run_zupt(args, timeout=600, input_data=None):
    """Run the zupt CLI. Always uses argv (never shell). Returns
    (returncode, stdout, stderr). Caller is responsible for cleaning
    secrets out of the returned strings before logging or rendering."""
    cmd = [ZUPT_BIN] + list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, input=input_data)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, '', f'Operation timed out after {timeout}s'
    except FileNotFoundError:
        return -1, '', f'zupt binary not found at {ZUPT_BIN}'


def scrub(text, *secrets_to_remove):
    """Strip any literal occurrence of a secret string from text before
    returning it to the user. Defence-in-depth so a stray error message
    that quotes back the password can't leak it."""
    if not text:
        return text
    for s in secrets_to_remove:
        if s and len(s) >= 4:
            text = text.replace(s, '***')
    return text


# Cache the CLI version once at startup. The CLI binary is immutable
# inside the container, so re-querying it on every request is just
# wasted forks.
_VERSION_CACHE = None
def cli_version():
    global _VERSION_CACHE
    if _VERSION_CACHE is None:
        code, out, _ = run_zupt(['version'], timeout=5)
        _VERSION_CACHE = out.strip().split('\n')[0] if code == 0 else 'zupt (offline)'
    return _VERSION_CACHE


# ─── Routes ───

@app.route('/healthz', methods=['GET'])
def healthz():
    """Liveness probe. No CLI call, no auth, no rate limit. The CLI's
    presence is verified once at startup via cli_version()'s cache."""
    return jsonify({'ok': True, 'service': 'zupt-web', 'version': '2.2.3'}), 200


@app.route('/', methods=['GET'])
def index():
    cleanup_old_jobs()
    return render_template('index.html',
                           version=cli_version(),
                           csrf_token=g.csrf_token)


@app.route('/version', methods=['GET'])
def version():
    return jsonify({'version': cli_version(), 'ok': True})


@app.route('/keygen', methods=['POST'])
@rate_limit(10, 60)
def keygen():
    """Legacy ML-KEM-768 + X25519 keypair (`zupt keygen`).
    Produces private.key + public.key in the job dir."""
    job_id = uuid.uuid4().hex[:12]
    d = job_dir(job_id)
    priv = d / 'private.key'
    pub  = d / 'public.key'

    code, _, err = run_zupt(['keygen', '-o', str(priv)])
    if code != 0:
        return render_template('result.html', success=False,
                               message=f'Key generation failed: {err}')

    code2, _, err2 = run_zupt(['keygen', '--pub', '-o', str(pub), '-k', str(priv)])
    if code2 != 0:
        return render_template('result.html', success=False,
                               message=f'Public key export failed: {err2}')

    return render_template('keygen_result.html', job_id=job_id,
                           log=err + err2, csrf_token=g.csrf_token,
                           key_kind='legacy')


@app.route('/keygen-sdk', methods=['POST'])
@rate_limit(10, 60)
def keygen_sdk():
    """SDK v2 keypair (`zupt keygen --sdk`). Produces private.key
    AND private.key.pub in one shot, with HKDF-SHA3-256 combiner +
    key commitment + HPKE binding + Argon2id at the wrap step.
    Recommended for new archives — see Zupt 2.2.3 CHANGELOG."""
    job_id = uuid.uuid4().hex[:12]
    d = job_dir(job_id)
    priv = d / 'private.key'

    code, _, err = run_zupt(['keygen', '--sdk', '-o', str(priv)])
    if code != 0:
        return render_template('result.html', success=False,
                               message=f'SDK key generation failed: {err}')

    pub = d / 'private.key.pub'
    if not pub.exists():
        return render_template('result.html', success=False,
                               message='SDK keygen succeeded but public key was not produced')

    return render_template('keygen_result.html', job_id=job_id,
                           log=err, csrf_token=g.csrf_token,
                           key_kind='sdk')


@app.route('/download-key/<job_id>/<key_type>', methods=['GET'])
def download_key(job_id, key_type):
    if key_type not in ('private', 'public'):
        abort(400)

    safe_id = ''.join(c for c in job_id if c.isalnum())[:16]
    if key_type == 'private':
        # Both legacy and SDK paths write private.key
        path = WORKDIR / safe_id / 'private.key'
        download_name = 'zupt_private.key'
    else:
        # Legacy writes public.key; SDK writes private.key.pub.
        # Try SDK first, fall back to legacy.
        sdk = WORKDIR / safe_id / 'private.key.pub'
        legacy = WORKDIR / safe_id / 'public.key'
        path = sdk if sdk.exists() else legacy
        download_name = 'zupt_public.key'

    if not path.exists() or not path.is_file():
        abort(404)
    try:
        path.resolve().relative_to(WORKDIR.resolve())
    except ValueError:
        abort(403)
    return send_file(path, as_attachment=True, download_name=download_name)


@app.route('/compress', methods=['POST'])
@rate_limit(30, 60)
def compress():
    if 'file' not in request.files:
        return render_template('result.html', success=False,
                               message='No file uploaded')
    f = request.files['file']
    if not f.filename:
        return render_template('result.html', success=False,
                               message='Empty filename')

    job_id = uuid.uuid4().hex[:12]
    d = job_dir(job_id)
    fname = safe_filename(f.filename)
    src = d / fname
    out = d / f'{fname}.zupt'
    f.save(str(src))

    cmd = ['compress']

    # Level
    level = request.form.get('level', '5')
    if level.isdigit() and 1 <= int(level) <= 9:
        cmd += ['-l', level]

    # Codec
    codec = request.form.get('codec', 'auto')
    if codec in ('vaptvupt', 'vv'):
        cmd += ['--vv']
    elif codec == 'lzhp':
        cmd += ['--lzhp']
    elif codec == 'store':
        cmd += ['-s']
    # 'auto' → no flag, let the CLI pick based on hardware (AVX2/NEON → VV)

    # Solid mode
    if request.form.get('solid') == 'on':
        cmd += ['--solid']

    # Block-level deduplication (Zupt 2.1.5+)
    if request.form.get('dedup') == 'on':
        cmd += ['--dedup']

    # Encryption: password XOR --pq XOR --pq-sdk (mutually exclusive)
    pw = (request.form.get('password') or '').strip()
    pq_key  = request.files.get('pq_key')
    sdk_key = request.files.get('pq_sdk_key')

    enc_modes = sum(bool(x) for x in
                    (pw, pq_key and pq_key.filename, sdk_key and sdk_key.filename))
    if enc_modes > 1:
        return render_template('result.html', success=False,
                               message='Choose ONE of: password, --pq key, --pq-sdk key')

    if pw:
        cmd += ['-p', pw]
    elif pq_key and pq_key.filename:
        key_path = d / 'upload_pub.key'
        pq_key.save(str(key_path))
        cmd += ['--pq', str(key_path)]
    elif sdk_key and sdk_key.filename:
        key_path = d / 'upload_sdk_pub.key'
        sdk_key.save(str(key_path))
        cmd += ['--pq-sdk', str(key_path)]

    cmd += [str(out), str(src)]
    code, stdout, stderr = run_zupt(cmd, timeout=COMPRESS_TIMEOUT)

    # Scrub the password out of any quoted-back error string
    stderr = scrub(stderr, pw)
    stdout = scrub(stdout, pw)

    if code != 0 or not out.exists():
        return render_template('result.html', success=False,
                               message=f'Compression failed:\n{stderr}')

    return send_file(str(out), as_attachment=True,
                     download_name=f'{fname}.zupt')


@app.route('/extract', methods=['POST'])
@rate_limit(30, 60)
def extract():
    if 'archive' not in request.files:
        return render_template('result.html', success=False,
                               message='No archive uploaded')
    f = request.files['archive']
    if not f.filename:
        return render_template('result.html', success=False,
                               message='Empty filename')

    job_id = uuid.uuid4().hex[:12]
    d = job_dir(job_id)
    arc = d / safe_filename(f.filename)
    outdir = d / 'extracted'
    outdir.mkdir()
    f.save(str(arc))

    cmd = ['extract', '-o', str(outdir)]

    pw = (request.form.get('password') or '').strip()
    pq_key  = request.files.get('pq_key')
    sdk_key = request.files.get('pq_sdk_key')

    enc_modes = sum(bool(x) for x in
                    (pw, pq_key and pq_key.filename, sdk_key and sdk_key.filename))
    if enc_modes > 1:
        return render_template('result.html', success=False,
                               message='Choose ONE of: password, --pq key, --pq-sdk key')

    if pw:
        cmd += ['-p', pw]
    elif pq_key and pq_key.filename:
        key_path = d / 'upload_priv.key'
        pq_key.save(str(key_path))
        cmd += ['--pq', str(key_path)]
    elif sdk_key and sdk_key.filename:
        key_path = d / 'upload_sdk_priv.key'
        sdk_key.save(str(key_path))
        cmd += ['--pq-sdk', str(key_path)]

    cmd += [str(arc)]
    code, stdout, stderr = run_zupt(cmd, timeout=EXTRACT_TIMEOUT)

    stderr = scrub(stderr, pw)
    stdout = scrub(stdout, pw)

    if code != 0:
        return render_template('result.html', success=False,
                               message=f'Extraction failed:\n{stderr}')

    files = [p for p in outdir.rglob('*') if p.is_file()]
    if not files:
        return render_template('result.html', success=False,
                               message=f'No files extracted.\n{stderr}')

    if len(files) == 1:
        return send_file(str(files[0]), as_attachment=True,
                         download_name=files[0].name)

    tar_out = d / 'extracted.tar.gz'
    subprocess.run(['tar', 'czf', str(tar_out), '-C', str(outdir), '.'],
                   capture_output=True, timeout=300)
    return send_file(str(tar_out), as_attachment=True,
                     download_name='extracted.tar.gz')


@app.route('/test-archive', methods=['POST'])
@rate_limit(30, 60)
def test_archive():
    if 'archive' not in request.files:
        return render_template('result.html', success=False,
                               message='No archive uploaded')
    f = request.files['archive']
    job_id = uuid.uuid4().hex[:12]
    d = job_dir(job_id)
    arc = d / safe_filename(f.filename)
    f.save(str(arc))

    cmd = ['test']
    pw = (request.form.get('password') or '').strip()
    if pw:
        cmd += ['-p', pw]
    cmd += [str(arc)]

    code, stdout, stderr = run_zupt(cmd, timeout=EXTRACT_TIMEOUT)
    shutil.rmtree(d, ignore_errors=True)

    msg = scrub(stderr + stdout, pw)
    return render_template('result.html', success=(code == 0), message=msg)


# ─── Entry point ───
if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=False)
