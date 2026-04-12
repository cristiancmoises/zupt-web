#!/usr/bin/env python3
"""
Zupt Web — Hardened REST backend for post-quantum backup operations.
"""
import subprocess, os, sys, uuid, shutil, time, hmac, secrets
from pathlib import Path
from functools import wraps
from collections import defaultdict
from flask import (Flask, request, jsonify, send_file, render_template,
                   redirect, url_for, make_response, abort)

app = Flask(__name__)
app.secret_key = os.environ.get('ZUPT_SECRET_KEY', secrets.token_hex(32))
app.config['MAX_CONTENT_LENGTH'] = 2000 * 1024 * 1024

WORKDIR = Path(os.environ.get('ZUPT_WORKDIR', '/tmp/zupt-work'))
WORKDIR.mkdir(parents=True, exist_ok=True)
ZUPT_BIN = os.environ.get('ZUPT_BIN', '/usr/local/bin/zupt')
MAX_KEY_AGE = 3600 * 4

# ─── Rate Limiting ───
_rate = defaultdict(list)
def rate_limit(max_calls, period_sec):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            ip = request.remote_addr or '0.0.0.0'
            now = time.time()
            key = f'{f.__name__}:{ip}'
            _rate[key] = [t for t in _rate[key] if now - t < period_sec]
            if len(_rate[key]) >= max_calls:
                return render_template('error.html', error='Rate limit exceeded. Try again later.'), 429
            _rate[key].append(now)
            return f(*args, **kwargs)
        return wrapper
    return decorator

# ─── CSRF ───
def validate_csrf(token):
    expected = request.cookies.get('csrf_token')
    if not expected or not token:
        return False
    return hmac.compare_digest(expected, token)

@app.before_request
def csrf_check():
    if request.method in ('POST', 'PUT', 'DELETE'):
        token = request.form.get('csrf_token', '')
        if not validate_csrf(token):
            abort(403)

@app.after_request
def headers(response):
    if 'csrf_token' not in request.cookies:
        response.set_cookie('csrf_token', secrets.token_hex(32),
                            httponly=True, samesite='Strict', max_age=3600)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
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

def run_zupt(args, timeout=600):
    cmd = [ZUPT_BIN] + list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, '', 'Operation timed out'
    except FileNotFoundError:
        return -1, '', f'zupt binary not found at {ZUPT_BIN}'

# ─── Routes ───
@app.route('/', methods=['GET'])
def index():
    cleanup_old_jobs()
    code, out, _ = run_zupt(['version'], timeout=5)
    version = out.strip().split('\n')[0] if code == 0 else 'zupt (offline)'
    csrf = request.cookies.get('csrf_token', secrets.token_hex(32))
    return render_template('index.html', version=version, csrf_token=csrf)

@app.route('/keygen', methods=['POST'])
@rate_limit(10, 60)
def keygen():
    job_id = uuid.uuid4().hex[:12]
    d = job_dir(job_id)
    priv = d / 'private.key'
    pub = d / 'public.key'

    code, _, err = run_zupt(['keygen', '-o', str(priv)])
    if code != 0:
        return render_template('result.html', success=False, message=f'Key generation failed: {err}')

    code2, _, err2 = run_zupt(['keygen', '--pub', '-o', str(pub), '-k', str(priv)])
    if code2 != 0:
        return render_template('result.html', success=False, message=f'Public key export failed: {err2}')

    csrf = request.cookies.get('csrf_token', secrets.token_hex(32))
    return render_template('keygen_result.html', job_id=job_id, log=err + err2, csrf_token=csrf)

@app.route('/download-key/<job_id>/<key_type>', methods=['GET'])
def download_key(job_id, key_type):
    if key_type not in ('private', 'public'):
        abort(400)
    safe_id = ''.join(c for c in job_id if c.isalnum())[:16]
    path = WORKDIR / safe_id / f'{key_type}.key'
    if not path.exists() or not path.is_file():
        abort(404)
    try:
        path.resolve().relative_to(WORKDIR.resolve())
    except ValueError:
        abort(403)
    return send_file(path, as_attachment=True, download_name=f'zupt_{key_type}.key')

@app.route('/compress', methods=['POST'])
@rate_limit(30, 60)
def compress():
    if 'file' not in request.files:
        return render_template('result.html', success=False, message='No file uploaded')
    f = request.files['file']
    if not f.filename:
        return render_template('result.html', success=False, message='Empty filename')

    job_id = uuid.uuid4().hex[:12]
    d = job_dir(job_id)
    fname = safe_filename(f.filename)
    src = d / fname
    out = d / f'{fname}.zupt'
    f.save(str(src))

    cmd = ['compress']
    level = request.form.get('level', '7')
    if level.isdigit() and 1 <= int(level) <= 9:
        cmd += ['-l', level]

    codec = request.form.get('codec', 'auto')
    if codec in ('vaptvupt', 'vv'):
        cmd += ['--vv']
    elif codec == 'lzhp':
        cmd += ['--lzhp']
    elif codec == 'store':
        cmd += ['-s']

    if request.form.get('solid') == 'on':
        cmd += ['--solid']

    pw = request.form.get('password', '')
    if pw:
        cmd += ['-p', pw]

    pq_key = request.files.get('pq_key')
    if pq_key and pq_key.filename:
        key_path = d / 'upload_pub.key'
        pq_key.save(str(key_path))
        cmd += ['--pq', str(key_path)]

    cmd += [str(out), str(src)]
    code, stdout, stderr = run_zupt(cmd)

    if code != 0 or not out.exists():
        return render_template('result.html', success=False,
                               message=f'Compression failed:\n{stderr}')

    return send_file(str(out), as_attachment=True, download_name=f'{fname}.zupt')

@app.route('/extract', methods=['POST'])
@rate_limit(30, 60)
def extract():
    if 'archive' not in request.files:
        return render_template('result.html', success=False, message='No archive uploaded')
    f = request.files['archive']
    if not f.filename:
        return render_template('result.html', success=False, message='Empty filename')

    job_id = uuid.uuid4().hex[:12]
    d = job_dir(job_id)
    arc = d / safe_filename(f.filename)
    outdir = d / 'extracted'
    outdir.mkdir()
    f.save(str(arc))

    cmd = ['extract', '-o', str(outdir)]
    pw = request.form.get('password', '')
    if pw:
        cmd += ['-p', pw]

    pq_key = request.files.get('pq_key')
    if pq_key and pq_key.filename:
        key_path = d / 'upload_priv.key'
        pq_key.save(str(key_path))
        cmd += ['--pq', str(key_path)]

    cmd += [str(arc)]
    code, stdout, stderr = run_zupt(cmd)

    if code != 0:
        return render_template('result.html', success=False,
                               message=f'Extraction failed:\n{stderr}')

    files = [f for f in outdir.rglob('*') if f.is_file()]

    if not files:
        return render_template('result.html', success=False,
                               message=f'No files extracted.\n{stderr}')

    if len(files) == 1:
        return send_file(str(files[0]), as_attachment=True,
                         download_name=files[0].name)

    tar_out = d / 'extracted.tar.gz'
    subprocess.run(['tar', 'czf', str(tar_out), '-C', str(outdir), '.'],
                   capture_output=True, timeout=300)
    return send_file(str(tar_out), as_attachment=True, download_name='extracted.tar.gz')

@app.route('/test-archive', methods=['POST'])
@rate_limit(30, 60)
def test_archive():
    if 'archive' not in request.files:
        return render_template('result.html', success=False, message='No archive uploaded')
    f = request.files['archive']
    job_id = uuid.uuid4().hex[:12]
    d = job_dir(job_id)
    arc = d / safe_filename(f.filename)
    f.save(str(arc))

    cmd = ['test']
    pw = request.form.get('password', '')
    if pw:
        cmd += ['-p', pw]
    cmd += [str(arc)]

    code, stdout, stderr = run_zupt(cmd, timeout=600)
    shutil.rmtree(d, ignore_errors=True)
    return render_template('result.html', success=(code == 0), message=stderr + stdout)

@app.route('/version', methods=['GET'])
def version():
    code, out, _ = run_zupt(['version'], timeout=5)
    return jsonify({'version': out.strip(), 'ok': code == 0})

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=False)
