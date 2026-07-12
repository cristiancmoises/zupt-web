#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Cristian Cezar Moisés
# Commercial licensing: sac@securityops.co
"""
VaptVupt Web — Hardened REST backend for post-quantum backup operations.

Licensed under the GNU Affero General Public License v3.0 or later.
If you operate a modified version of this software as a network service,
the AGPL requires you to make your modifications available to your users.
For commercial licensing inquiries, contact: sac@securityops.co

Backend for the bundled VaptVupt CLI (default 5.2.1) and libvuptsdk-2.0.
(VaptVupt is the project formerly named Zupt — the `.zupt` archive format
and extension are unchanged; VAPTVUPT_* env vars are preferred but the
legacy ZUPT_* names still work.)
Exposes:
  POST  /keygen          hybrid ML-KEM-768 + X25519 keypair (vaptvupt keygen)
  POST  /keygen-sdk      SDK v2 keypair (HKDF + key commitment + Argon2id)
  POST  /keygen-pqonly   FULL post-quantum keypair (ML-KEM-768 only, --pq-only)
  POST  /compress        file → .zupt; password, --pq, --pq-only, --pq-sdk, --dedup
  POST  /extract         .zupt → file; password, --pq, --pq-only, --pq-sdk
  POST  /test-archive    integrity verify
  POST  /info            archive header inspection (no credential required)
  GET   /version         vaptvupt CLI version (cached)
  GET   /healthz         liveness probe (no CLI call, no auth, no rate limit)
  GET   /download-key/<job>/<type>
"""
import os, sys, time, uuid, hmac, shutil, secrets, subprocess, tempfile
from pathlib import Path
from functools import wraps
from collections import defaultdict
from flask import (Flask, request, jsonify, send_file, render_template,
                   make_response, abort, g)

APP_VERSION = '5.2.1'   # tracks the bundled VaptVupt CLI version


def env(name, default=None):
    """Read VAPTVUPT_<name>, falling back to the legacy ZUPT_<name>."""
    v = os.environ.get('VAPTVUPT_' + name)
    if v is None:
        v = os.environ.get('ZUPT_' + name)
    return default if v is None else v


app = Flask(__name__)
app.secret_key = env('SECRET_KEY', secrets.token_hex(32))

# ─── Config ───
# Upload size cap. Override via VAPTVUPT_MAX_UPLOAD_MB env var.
# Default: 2 GiB.
MAX_UPLOAD_MB = int(env('MAX_UPLOAD_MB', '2048'))
app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_MB * 1024 * 1024

WORKDIR  = Path(env('WORKDIR', '/tmp/vaptvupt-work'))
WORKDIR.mkdir(parents=True, exist_ok=True)

VAPTVUPT_BIN = env('BIN', '/usr/local/bin/vaptvupt')
MAX_KEY_AGE = int(env('KEY_TTL_SEC', str(3600 * 4)))
COMPRESS_TIMEOUT = int(env('COMPRESS_TIMEOUT', '600'))
EXTRACT_TIMEOUT  = int(env('EXTRACT_TIMEOUT',  '600'))


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


def run_vaptvupt(args, timeout=600, input_data=None):
    """Run the vaptvupt CLI. Always uses argv (never shell). Returns
    (returncode, stdout, stderr). Caller is responsible for cleaning
    secrets out of the returned strings before logging or rendering."""
    cmd = [VAPTVUPT_BIN] + list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, input=input_data)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, '', f'Operation timed out after {timeout}s'
    except FileNotFoundError:
        return -1, '', f'vaptvupt binary not found at {VAPTVUPT_BIN}'


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
        code, out, _ = run_vaptvupt(['version'], timeout=5)
        _VERSION_CACHE = out.strip().split('\n')[0] if code == 0 else 'vaptvupt (offline)'
    return _VERSION_CACHE


# ─── Routes ───

@app.route('/healthz', methods=['GET'])
def healthz():
    """Liveness probe. No CLI call, no auth, no rate limit. The CLI's
    presence is verified once at startup via cli_version()'s cache."""
    return jsonify({'ok': True, 'service': 'vaptvupt-web',
                    'version': APP_VERSION}), 200


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
    """Hybrid ML-KEM-768 + X25519 keypair (`vaptvupt keygen`).
    Produces private.key + public.key in the job dir. Use with --pq."""
    job_id = uuid.uuid4().hex[:12]
    d = job_dir(job_id)
    priv = d / 'private.key'
    pub  = d / 'public.key'

    code, _, err = run_vaptvupt(['keygen', '-o', str(priv)])
    if code != 0:
        return render_template('result.html', success=False,
                               message=f'Key generation failed: {err}')

    code2, _, err2 = run_vaptvupt(['keygen', '--pub', '-o', str(pub), '-k', str(priv)])
    if code2 != 0:
        return render_template('result.html', success=False,
                               message=f'Public key export failed: {err2}')

    return render_template('keygen_result.html', job_id=job_id,
                           log=err + err2, key_kind='legacy')


@app.route('/keygen-sdk', methods=['POST'])
@rate_limit(10, 60)
def keygen_sdk():
    """SDK v2 keypair (`vaptvupt keygen --sdk`). Produces private.key
    AND private.key.pub in one shot, with HKDF-SHA3-256 combiner +
    key commitment + HPKE binding + Argon2id at the wrap step.
    Recommended for new archives — see VaptVupt CHANGELOG."""
    job_id = uuid.uuid4().hex[:12]
    d = job_dir(job_id)
    priv = d / 'private.key'

    code, _, err = run_vaptvupt(['keygen', '--sdk', '-o', str(priv)])
    if code != 0:
        return render_template('result.html', success=False,
                               message=f'SDK key generation failed: {err}')

    pub = d / 'private.key.pub'
    if not pub.exists():
        return render_template('result.html', success=False,
                               message='SDK keygen succeeded but public key was not produced')

    return render_template('keygen_result.html', job_id=job_id,
                           log=err, key_kind='sdk')


@app.route('/keygen-pqonly', methods=['POST'])
@rate_limit(10, 60)
def keygen_pqonly():
    """FULL post-quantum keypair (`vaptvupt keygen --pq-only`):
    ML-KEM-768 only, no classical X25519 layer. Use with --pq-only.
    Available since VaptVupt 4.2.0."""
    job_id = uuid.uuid4().hex[:12]
    d = job_dir(job_id)
    priv = d / 'private.key'
    pub  = d / 'public.key'

    code, _, err = run_vaptvupt(['keygen', '--pq-only', '-o', str(priv)])
    if code != 0:
        return render_template('result.html', success=False,
                               message=f'Full-PQ key generation failed: {err}')

    code2, _, err2 = run_vaptvupt(['keygen', '--pub', '--pq-only',
                                   '-o', str(pub), '-k', str(priv)])
    if code2 != 0:
        return render_template('result.html', success=False,
                               message=f'Public key export failed: {err2}')

    return render_template('keygen_result.html', job_id=job_id,
                           log=err + err2, key_kind='pqonly')


@app.route('/download-key/<job_id>/<key_type>', methods=['GET'])
def download_key(job_id, key_type):
    if key_type not in ('private', 'public'):
        abort(400)

    safe_id = ''.join(c for c in job_id if c.isalnum())[:16]
    if key_type == 'private':
        # All keygen paths write private.key
        path = WORKDIR / safe_id / 'private.key'
        download_name = 'vaptvupt_private.key'
    else:
        # Legacy/pq-only write public.key; SDK writes private.key.pub.
        # Try SDK first, fall back to the others.
        sdk = WORKDIR / safe_id / 'private.key.pub'
        legacy = WORKDIR / safe_id / 'public.key'
        path = sdk if sdk.exists() else legacy
        download_name = 'vaptvupt_public.key'

    if not path.exists() or not path.is_file():
        abort(404)
    try:
        path.resolve().relative_to(WORKDIR.resolve())
    except ValueError:
        abort(403)
    return send_file(path, as_attachment=True, download_name=download_name)


def _password_error(raw, stripped):
    """Reject passwords the CLI cannot receive safely via '-p <pw>':
    whitespace-only (would silently produce an UNENCRYPTED archive) and
    leading '-' (the CLI's parser treats the value as an option and may
    quote the password back in its error output)."""
    if raw and not stripped:
        return 'Password is only whitespace — archive would NOT be encrypted'
    if stripped.startswith('-'):
        return "Password may not start with '-'"
    return None


def _key_dir(d):
    """Uploaded key files go in a subdirectory so a source file that
    happens to be named 'upload_pub.key' (etc.) can never be
    overwritten by the key save."""
    kd = d / 'keys'
    kd.mkdir(exist_ok=True)
    return kd


def _enc_selection(form, files):
    """Return (password, pq_key, pq_only_key, sdk_key, n_modes, error)
    from a compress/extract form. The four encryption modes are
    mutually exclusive."""
    raw = form.get('password') or ''
    pw = raw.strip()
    pq_key   = files.get('pq_key')
    pqo_key  = files.get('pq_only_key')
    sdk_key  = files.get('pq_sdk_key')
    n = sum(bool(x) for x in
            (pw,
             pq_key and pq_key.filename,
             pqo_key and pqo_key.filename,
             sdk_key and sdk_key.filename))
    return pw, pq_key, pqo_key, sdk_key, n, _password_error(raw, pw)


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
    src_dir = d / 'in'
    src_dir.mkdir(exist_ok=True)
    src = src_dir / fname
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

    # Block-level deduplication
    if request.form.get('dedup') == 'on':
        cmd += ['--dedup']

    # Encryption: password XOR --pq XOR --pq-only XOR --pq-sdk
    pw, pq_key, pqo_key, sdk_key, enc_modes, pw_err = \
        _enc_selection(request.form, request.files)
    if pw_err:
        return render_template('result.html', success=False, message=pw_err)
    if enc_modes > 1:
        return render_template('result.html', success=False,
                               message='Choose ONE of: password, --pq key, '
                                       '--pq-only key, --pq-sdk key')

    if pw:
        cmd += ['-p', pw]
    elif pq_key and pq_key.filename:
        key_path = _key_dir(d) / 'upload_pub.key'
        pq_key.save(str(key_path))
        cmd += ['--pq', str(key_path)]
    elif pqo_key and pqo_key.filename:
        key_path = _key_dir(d) / 'upload_pqonly_pub.key'
        pqo_key.save(str(key_path))
        cmd += ['--pq-only', str(key_path)]
    elif sdk_key and sdk_key.filename:
        key_path = _key_dir(d) / 'upload_sdk_pub.key'
        sdk_key.save(str(key_path))
        cmd += ['--pq-sdk', str(key_path)]

    cmd += [str(out), str(src)]
    code, stdout, stderr = run_vaptvupt(cmd, timeout=COMPRESS_TIMEOUT)

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
    arc_dir = d / 'in'
    arc_dir.mkdir(exist_ok=True)
    arc = arc_dir / safe_filename(f.filename)
    outdir = d / 'extracted'
    outdir.mkdir()
    f.save(str(arc))

    cmd = ['extract', '-o', str(outdir)]

    pw, pq_key, pqo_key, sdk_key, enc_modes, pw_err = \
        _enc_selection(request.form, request.files)
    if pw_err:
        return render_template('result.html', success=False, message=pw_err)
    if enc_modes > 1:
        return render_template('result.html', success=False,
                               message='Choose ONE of: password, --pq key, '
                                       '--pq-only key, --pq-sdk key')

    if pw:
        cmd += ['-p', pw]
    elif pq_key and pq_key.filename:
        key_path = _key_dir(d) / 'upload_priv.key'
        pq_key.save(str(key_path))
        cmd += ['--pq', str(key_path)]
    elif pqo_key and pqo_key.filename:
        key_path = _key_dir(d) / 'upload_pqonly_priv.key'
        pqo_key.save(str(key_path))
        cmd += ['--pq-only', str(key_path)]
    elif sdk_key and sdk_key.filename:
        key_path = _key_dir(d) / 'upload_sdk_priv.key'
        sdk_key.save(str(key_path))
        cmd += ['--pq-sdk', str(key_path)]

    cmd += [str(arc)]
    code, stdout, stderr = run_vaptvupt(cmd, timeout=EXTRACT_TIMEOUT)

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
    if not f.filename:
        return render_template('result.html', success=False,
                               message='Empty filename')
    job_id = uuid.uuid4().hex[:12]
    d = job_dir(job_id)
    arc = d / safe_filename(f.filename)
    f.save(str(arc))

    cmd = ['test']
    raw_pw = request.form.get('password') or ''
    pw = raw_pw.strip()
    pw_err = _password_error(raw_pw, pw)
    if pw_err:
        shutil.rmtree(d, ignore_errors=True)
        return render_template('result.html', success=False, message=pw_err)
    if pw:
        cmd += ['-p', pw]
    cmd += [str(arc)]

    code, stdout, stderr = run_vaptvupt(cmd, timeout=EXTRACT_TIMEOUT)
    shutil.rmtree(d, ignore_errors=True)

    msg = scrub(stderr + stdout, pw)
    return render_template('result.html', success=(code == 0), message=msg)


@app.route('/info', methods=['POST'])
@rate_limit(30, 60)
def info():
    """Archive header inspection (`vaptvupt info`). Reads the header
    only — reports codec, encryption mode (password / hybrid PQ /
    full PQ / SDK), block count. No password or key required. This is
    the same header detection the 5.2.1 GUI uses to auto-pick the
    right decrypt mode."""
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
    f.save(str(arc))

    code, stdout, stderr = run_vaptvupt(['info', str(arc)], timeout=60)
    shutil.rmtree(d, ignore_errors=True)

    return render_template('result.html', success=(code == 0),
                           message=(stderr + stdout))


# ─── Entry point ───
if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=False)
