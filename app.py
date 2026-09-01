#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Cristian Cezar Moisés
# Commercial licensing: sac@securityops.co
"""
ZUPT Web — Hardened REST backend for post-quantum backup operations.

Licensed under the GNU Affero General Public License v3.0 or later.
If you operate a modified version of this software as a network service,
the AGPL requires you to make your modifications available to your users.
For commercial licensing inquiries, contact: sac@securityops.co

Backend for the bundled ZUPT CLI (default 5.2.8). ZUPT restored its original
name in 5.2.2; the `.zupt` archive format and VaptVupt codec name are
unchanged. ZUPT_* environment variables are canonical, with VAPTVUPT_*
accepted as compatibility fallbacks for deployments made with 3.0.0–5.2.1.
Exposes:
  POST  /keygen          hybrid ML-KEM-768 + X25519 keypair (zupt keygen)
  POST  /keygen-pqonly   FULL post-quantum keypair (ML-KEM-768 only, --pq-only)
  POST  /compress        file → .zupt; password, --pq, --pq-only, --dedup
  POST  /extract         .zupt → file; password, --pq, --pq-only
  POST  /test-archive    integrity verify
  POST  /info            archive header inspection (no credential required)
  GET   /version         ZUPT CLI version (cached)
  GET   /healthz         liveness probe (no CLI call, no auth, no rate limit)
  GET   /download-key/<job>/<type>
"""
import hmac
import os
import secrets
import shutil
# Fixed executable plus explicit argv; subprocess never invokes a shell.
import subprocess  # nosec B404
import tarfile
import time
from pathlib import Path
from functools import wraps
from collections import defaultdict
from flask import (Flask, request, jsonify, send_file, render_template,
                   make_response, abort, g)

APP_VERSION = '5.2.8'   # tracks the bundled ZUPT CLI version


def env(name, default=None):
    """Read ZUPT_<name>, falling back to renamed-era VAPTVUPT_<name>."""
    v = os.environ.get('ZUPT_' + name)
    if v is None:
        v = os.environ.get('VAPTVUPT_' + name)
    return default if v is None else v


def bounded_env_int(name, default, minimum, maximum):
    """Load a bounded integer setting or fail startup with a clear error."""
    raw = env(name, str(default))
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f'ZUPT_{name} must be an integer') from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(
            f'ZUPT_{name} must be between {minimum} and {maximum}')
    return value


app = Flask(__name__)
app.secret_key = env('SECRET_KEY', secrets.token_hex(32))

# ─── Config ───
# Upload size cap. Override via ZUPT_MAX_UPLOAD_MB env var.
# Default: 512 MiB. The supported deployment uses a 2 GiB tmpfs and needs
# room for Werkzeug's upload spool, the isolated input, and ZUPT's output.
MAX_UPLOAD_MB = int(env('MAX_UPLOAD_MB', '512'))
app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_MB * 1024 * 1024

# This is a dedicated mode-0700 tmpfs in the supported container deployment.
WORKDIR = Path(env('WORKDIR', '/tmp/zupt-work'))
WORKDIR.mkdir(mode=0o700, parents=True, exist_ok=True)

ZUPT_BIN = env('BIN', '/usr/local/bin/zupt')
MAX_KEY_AGE = int(env('KEY_TTL_SEC', str(3600 * 4)))
COMPRESS_TIMEOUT = bounded_env_int('COMPRESS_TIMEOUT', 600, 1, 600)
EXTRACT_TIMEOUT = bounded_env_int('EXTRACT_TIMEOUT', 600, 1, 600)


# ─── Rate limiting (in-process; fine for single-host deployment) ───
_rate = defaultdict(list)
_rate_max_keys = 4096   # cap memory usage if hit by random IPs


def rate_limit(max_calls, period_sec):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            ip = request.remote_addr or 'unknown-client'
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

    # Expiry is enforced on every externally reachable non-health request, so
    # idle key links cannot bypass their TTL by avoiding the home page.
    cleanup_old_jobs()

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
        "style-src 'self' 'unsafe-inline'; "
        "font-src 'self'; "
        "img-src 'self' data:; "
        "form-action 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "connect-src 'self'")
    # Note: 'Server: gunicorn/...' is set by gunicorn itself and cannot
    # be overridden from the WSGI app. It's harmless info disclosure.
    return response


# ─── Helpers ───
def new_job_id():
    """Return a 128-bit unguessable capability/job identifier."""
    return secrets.token_hex(16)


def valid_job_id(job_id):
    return (len(job_id) == 32 and
            all(c in '0123456789abcdef' for c in job_id))


def job_dir(job_id):
    if not valid_job_id(job_id):
        raise ValueError('invalid internal job identifier')
    d = WORKDIR / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def cleanup_old_jobs():
    now = time.time()
    try:
        for entry in WORKDIR.iterdir():
            if entry.is_dir() and now - entry.stat().st_mtime > MAX_KEY_AGE:
                shutil.rmtree(entry, ignore_errors=True)
    except OSError:
        return


def job_download(path, download_name, cleanup_dir=None):
    """Send a sensitive/generated file without browser/proxy caching.

    For one-shot archive and extraction results, remove the entire isolated
    job directory when the WSGI server closes the streamed response.
    """
    response = send_file(path, as_attachment=True, download_name=download_name)
    response.headers['Cache-Control'] = 'no-store, private'
    response.headers['Pragma'] = 'no-cache'
    if cleanup_dir is not None:
        # Keep the response as a streaming iterable, but let Werkzeug own its
        # ClosingIterator so call_on_close runs after the file wrapper closes.
        response.direct_passthrough = False
        response.call_on_close(
            lambda: shutil.rmtree(cleanup_dir, ignore_errors=True))
    return response


def safe_filename(name):
    candidate = ''.join(
        c for c in name if c.isalnum() or c in '.-_')[:128]
    return 'file' if candidate in ('', '.', '..') else candidate


def run_zupt(args, timeout=600, input_data=None, cwd=None):
    """Run the ZUPT CLI. Always uses argv (never shell). Returns
    (returncode, stdout, stderr). Caller is responsible for cleaning
    secrets out of the returned strings before logging or rendering."""
    cmd = [ZUPT_BIN] + list(args)
    try:
        # argv only; ZUPT_BIN is explicit operator configuration.
        r = subprocess.run(  # nosec B603
            cmd, capture_output=True, text=True,
            timeout=timeout, input=input_data, cwd=cwd)
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
_VERSION_OK = False
def cli_version():
    global _VERSION_CACHE, _VERSION_OK
    if _VERSION_CACHE is None:
        code, out, _ = run_zupt(['version'], timeout=5)
        first_line = out.strip().split('\n')[0] if out.strip() else ''
        _VERSION_OK = code == 0 and bool(first_line)
        _VERSION_CACHE = first_line if _VERSION_OK else 'zupt (offline)'
    return _VERSION_CACHE


# ─── Routes ───

@app.route('/healthz', methods=['GET'])
def healthz():
    """Process liveness probe. No CLI call, auth, cookie, or rate limit."""
    return jsonify({'ok': True, 'service': 'zupt-web',
                    'version': APP_VERSION}), 200


@app.route('/', methods=['GET'])
def index():
    return render_template('index.html',
                           version=cli_version(),
                           csrf_token=g.csrf_token)


@app.route('/version', methods=['GET'])
def version():
    current = cli_version()
    return jsonify({'version': current, 'ok': _VERSION_OK}), \
        (200 if _VERSION_OK else 503)


@app.route('/keygen', methods=['POST'])
@rate_limit(10, 60)
def keygen():
    """Hybrid ML-KEM-768 + X25519 keypair (`zupt keygen`).
    Produces private.key + public.key in the job dir. Use with --pq."""
    job_id = new_job_id()
    d = job_dir(job_id)
    priv = d / 'private.key'
    pub  = d / 'public.key'

    code, _, err = run_zupt(['keygen', '-o', str(priv)])
    if code != 0:
        shutil.rmtree(d, ignore_errors=True)
        return render_template('result.html', success=False,
                               message=f'Key generation failed: {err}')

    code2, _, err2 = run_zupt(['keygen', '--pub', '-o', str(pub), '-k', str(priv)])
    if code2 != 0:
        shutil.rmtree(d, ignore_errors=True)
        return render_template('result.html', success=False,
                               message=f'Public key export failed: {err2}')

    return render_template('keygen_result.html', job_id=job_id,
                           log=err + err2, key_kind='hybrid')


@app.route('/keygen-pqonly', methods=['POST'])
@rate_limit(10, 60)
def keygen_pqonly():
    """FULL post-quantum keypair (`zupt keygen --pq-only`):
    ML-KEM-768 only, no classical X25519 layer. Use with --pq-only.
    Available since ZUPT 4.2.0."""
    job_id = new_job_id()
    d = job_dir(job_id)
    priv = d / 'private.key'
    pub  = d / 'public.key'

    code, _, err = run_zupt(['keygen', '--pq-only', '-o', str(priv)])
    if code != 0:
        shutil.rmtree(d, ignore_errors=True)
        return render_template('result.html', success=False,
                               message=f'Full-PQ key generation failed: {err}')

    code2, _, err2 = run_zupt(['keygen', '--pub', '--pq-only',
                              '-o', str(pub), '-k', str(priv)])
    if code2 != 0:
        shutil.rmtree(d, ignore_errors=True)
        return render_template('result.html', success=False,
                               message=f'Public key export failed: {err2}')

    return render_template('keygen_result.html', job_id=job_id,
                           log=err + err2, key_kind='pqonly')


@app.route('/download-key/<job_id>/<key_type>', methods=['GET'])
@rate_limit(120, 60)
def download_key(job_id, key_type):
    if key_type not in ('private', 'public'):
        abort(400)

    if not valid_job_id(job_id):
        abort(404)
    key_job = WORKDIR / job_id
    try:
        if time.time() - key_job.stat().st_mtime > MAX_KEY_AGE:
            shutil.rmtree(key_job, ignore_errors=True)
            abort(404)
    except OSError:
        abort(404)

    if key_type == 'private':
        # All keygen paths write private.key
        path = key_job / 'private.key'
        download_name = 'zupt_private.key'
    else:
        path = key_job / 'public.key'
        download_name = 'zupt_public.key'

    if not path.exists() or not path.is_file():
        abort(404)
    try:
        path.resolve().relative_to(WORKDIR.resolve())
    except ValueError:
        abort(403)
    return job_download(path, download_name)


def _password_error(raw):
    """Validate a password before sending it over ZUPT's inherited stdin FD."""
    if any(char in raw for char in ('\x00', '\r', '\n')):
        return 'Password may not contain NUL or line-break characters'
    if len(raw.encode('utf-8')) > 255:
        return 'Password exceeds ZUPT\'s 255-byte limit'
    return None


def _key_dir(d):
    """Uploaded key files go in a subdirectory so a source file that
    happens to be named 'upload_pub.key' (etc.) can never be
    overwritten by the key save."""
    kd = d / 'keys'
    kd.mkdir(exist_ok=True)
    return kd


def _save_job_upload(upload, path, job):
    """Persist one multipart part, removing its whole job on I/O failure."""
    try:
        upload.save(str(path))
    except OSError:
        shutil.rmtree(job, ignore_errors=True)
        return False
    return True


def _enc_selection(form, files):
    """Return (password, pq_key, pq_only_key, n_modes, error)
    from a compress/extract form. The three encryption modes are
    mutually exclusive."""
    raw = form.get('password') or ''
    pw = raw
    pq_key   = files.get('pq_key')
    pqo_key  = files.get('pq_only_key')
    n = sum(bool(x) for x in
            (pw,
             pq_key and pq_key.filename,
             pqo_key and pqo_key.filename))
    return pw, pq_key, pqo_key, n, _password_error(raw)


def compatibility_hint(message):
    """Add an actionable recovery hint for retired opaque-SDK archives."""
    if 'libvuptsdk' not in message and 'Argon2id' not in message:
        return message
    return (message.rstrip() + '\n\nThis archive needs the retired SDK compatibility '
            'reader from the v5.2.1 release. Recover it there, then create a '
            'new native --pq, --pq-only, or PBKDF2 password archive. See '
            'MIGRATION.md in the zupt-web repository.')


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

    # Reject incompatible options and credentials before copying the upload
    # into the isolated work area.
    solid = request.form.get('solid') == 'on'
    dedup = request.form.get('dedup') == 'on'
    if solid and dedup:
        return render_template('result.html', success=False,
                               message='Solid mode and block dedup cannot be combined')

    pw, pq_key, pqo_key, enc_modes, pw_err = \
        _enc_selection(request.form, request.files)
    if pw_err:
        return render_template('result.html', success=False, message=pw_err)
    if enc_modes > 1:
        return render_template('result.html', success=False,
                               message='Choose ONE of: password, --pq key, '
                                       'or --pq-only key')

    job_id = new_job_id()
    d = job_dir(job_id)
    fname = safe_filename(f.filename)
    src_dir = d / 'in'
    src_dir.mkdir(exist_ok=True)
    src = src_dir / fname
    out = d / f'{fname}.zupt'
    if not _save_job_upload(f, src, d):
        return render_template('result.html', success=False,
                               message='Upload could not be stored')

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

    # Solid and dedup are separate writer paths upstream; combining them would
    # silently omit actual deduplication, so fail clearly instead.
    if solid:
        cmd += ['--solid']

    # Block-level deduplication
    if dedup:
        cmd += ['--dedup']

    # Encryption: password XOR --pq XOR --pq-only
    password_input = None
    if pw:
        cmd += ['--pass-fd', '0']
        password_input = pw + '\n'
    elif pq_key and pq_key.filename:
        key_path = _key_dir(d) / 'upload_pub.key'
        if not _save_job_upload(pq_key, key_path, d):
            return render_template('result.html', success=False,
                                   message='Public key could not be stored')
        cmd += ['--pq', str(key_path)]
    elif pqo_key and pqo_key.filename:
        key_path = _key_dir(d) / 'upload_pqonly_pub.key'
        if not _save_job_upload(pqo_key, key_path, d):
            return render_template('result.html', success=False,
                                   message='Public key could not be stored')
        cmd += ['--pq-only', str(key_path)]
    # Run from the isolated input directory and pass only the sanitized leaf
    # name. Otherwise ZUPT correctly strips the leading slash but preserves the
    # internal /tmp/zupt-work/... path as the archive member name.
    cmd += [str(out), '--', fname]
    code, stdout, stderr = run_zupt(
        cmd, timeout=COMPRESS_TIMEOUT, input_data=password_input, cwd=src_dir)

    # Scrub the password out of any quoted-back error string
    stderr = scrub(stderr, pw)
    stdout = scrub(stdout, pw)

    if code != 0 or not out.exists():
        shutil.rmtree(d, ignore_errors=True)
        return render_template('result.html', success=False,
                               message=f'Compression failed:\n{stderr}')

    return job_download(out, f'{fname}.zupt', cleanup_dir=d)


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

    pw, pq_key, pqo_key, enc_modes, pw_err = \
        _enc_selection(request.form, request.files)
    if pw_err:
        return render_template('result.html', success=False, message=pw_err)
    if enc_modes > 1:
        return render_template('result.html', success=False,
                               message='Choose ONE of: password, --pq key, '
                                       'or --pq-only key')

    job_id = new_job_id()
    d = job_dir(job_id)
    arc_dir = d / 'in'
    arc_dir.mkdir(exist_ok=True)
    arc = arc_dir / safe_filename(f.filename)
    outdir = d / 'extracted'
    outdir.mkdir()
    if not _save_job_upload(f, arc, d):
        return render_template('result.html', success=False,
                               message='Archive upload could not be stored')

    cmd = ['extract', '-o', str(outdir)]

    password_input = None
    if pw:
        cmd += ['--pass-fd', '0']
        password_input = pw + '\n'
    elif pq_key and pq_key.filename:
        key_path = _key_dir(d) / 'upload_priv.key'
        if not _save_job_upload(pq_key, key_path, d):
            return render_template('result.html', success=False,
                                   message='Private key could not be stored')
        cmd += ['--pq', str(key_path)]
    elif pqo_key and pqo_key.filename:
        key_path = _key_dir(d) / 'upload_pqonly_priv.key'
        if not _save_job_upload(pqo_key, key_path, d):
            return render_template('result.html', success=False,
                                   message='Private key could not be stored')
        cmd += ['--pq-only', str(key_path)]
    cmd += [str(arc)]
    code, stdout, stderr = run_zupt(
        cmd, timeout=EXTRACT_TIMEOUT, input_data=password_input)

    stderr = scrub(stderr, pw)
    stdout = scrub(stdout, pw)

    if code != 0:
        shutil.rmtree(d, ignore_errors=True)
        return render_template('result.html', success=False,
                               message=compatibility_hint(
                                   f'Extraction failed:\n{stderr}'))

    files = []
    for path in outdir.rglob('*'):
        if path.is_symlink():
            shutil.rmtree(d, ignore_errors=True)
            return render_template('result.html', success=False,
                                   message='Extraction produced a forbidden symlink')
        if path.is_file():
            try:
                path.resolve(strict=True).relative_to(outdir.resolve())
            except (OSError, ValueError):
                shutil.rmtree(d, ignore_errors=True)
                return render_template('result.html', success=False,
                                       message='Extraction escaped its isolated work directory')
            files.append(path)
    if not files:
        shutil.rmtree(d, ignore_errors=True)
        return render_template('result.html', success=False,
                               message=f'No files extracted.\n{stderr}')

    if len(files) == 1:
        return job_download(files[0], files[0].name, cleanup_dir=d)

    tar_out = d / 'extracted.tar.gz'
    try:
        with tarfile.open(tar_out, mode='w:gz') as archive:
            for path in sorted(files):
                archive.add(path, arcname=str(path.relative_to(outdir)),
                            recursive=False)
    except (OSError, tarfile.TarError) as exc:
        shutil.rmtree(d, ignore_errors=True)
        return render_template('result.html', success=False,
                               message=f'Could not package extracted files: {exc}')
    return job_download(tar_out, 'extracted.tar.gz', cleanup_dir=d)


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
    job_id = new_job_id()
    d = job_dir(job_id)
    arc = d / safe_filename(f.filename)
    if not _save_job_upload(f, arc, d):
        return render_template('result.html', success=False,
                               message='Archive upload could not be stored')

    cmd = ['test']
    pw, pq_key, pqo_key, enc_modes, pw_err = \
        _enc_selection(request.form, request.files)
    if pw_err:
        shutil.rmtree(d, ignore_errors=True)
        return render_template('result.html', success=False, message=pw_err)
    if enc_modes > 1:
        shutil.rmtree(d, ignore_errors=True)
        return render_template('result.html', success=False,
                               message='Choose ONE of: password, --pq key, '
                                       'or --pq-only key')

    password_input = None
    if pw:
        cmd += ['--pass-fd', '0']
        password_input = pw + '\n'
    elif pq_key and pq_key.filename:
        key_path = _key_dir(d) / 'upload_priv.key'
        if not _save_job_upload(pq_key, key_path, d):
            return render_template('result.html', success=False,
                                   message='Private key could not be stored')
        cmd += ['--pq', str(key_path)]
    elif pqo_key and pqo_key.filename:
        key_path = _key_dir(d) / 'upload_pqonly_priv.key'
        if not _save_job_upload(pqo_key, key_path, d):
            return render_template('result.html', success=False,
                                   message='Private key could not be stored')
        cmd += ['--pq-only', str(key_path)]
    cmd += [str(arc)]

    code, stdout, stderr = run_zupt(
        cmd, timeout=EXTRACT_TIMEOUT, input_data=password_input)
    shutil.rmtree(d, ignore_errors=True)

    msg = compatibility_hint(scrub(stderr + stdout, pw))
    return render_template('result.html', success=(code == 0), message=msg)


@app.route('/info', methods=['POST'])
@rate_limit(30, 60)
def info():
    """Unauthenticated archive framing inspection (`zupt info`). Reports
    format/trailer metadata, UUID, flags, encryption metadata, sizes, and
    block count without reading archive content or requiring a credential."""
    if 'archive' not in request.files:
        return render_template('result.html', success=False,
                               message='No archive uploaded')
    f = request.files['archive']
    if not f.filename:
        return render_template('result.html', success=False,
                               message='Empty filename')
    job_id = new_job_id()
    d = job_dir(job_id)
    arc = d / safe_filename(f.filename)
    if not _save_job_upload(f, arc, d):
        return render_template('result.html', success=False,
                               message='Archive upload could not be stored')

    code, stdout, stderr = run_zupt(['info', str(arc)], timeout=60)
    shutil.rmtree(d, ignore_errors=True)

    return render_template('result.html', success=(code == 0),
                           message=(stderr + stdout))


# ─── Entry point ───
if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=False)
