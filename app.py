import os
import json
import time
import queue
import threading
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, time as dtime
from functools import wraps

import click
from flask import (Flask, request, session, redirect, url_for,
                   render_template, jsonify, send_file, abort,
                   Response, stream_with_context, flash, cli)
from werkzeug.security import generate_password_hash, check_password_hash
from flask_migrate import Migrate

import config
from security import (encrypt_password, decrypt_password,
                      validate_hostname, validate_port,
                      sanitize_filename, safe_join_path, is_safe_path,
                      generate_csrf_token, validate_csrf_token)
from mikrotik import MikrotikClient, BackupType, MikrotikError
from db import db, User, Router, Backup, Schedule, ActivityLog, log_activity
import scheduler as sched

# ── Logging ──────────────────────────────────────────────────────
os.makedirs(config.LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(
            os.path.join(config.LOG_DIR, 'app.log'),
            maxBytes=10_485_760, backupCount=5
        ),
    ],
)
logger = logging.getLogger('mikrotik_backup')

# ── Flask app ────────────────────────────────────────────────────
app = Flask(__name__)
app.config.from_object(config)
os.makedirs(config.BACKUP_DIR, exist_ok=True)

# Initialize Database & Migrations
db.init_app(app)
migrate = Migrate(app, db)

# ── CLI Command for Initial Admin ────────────────────────────────
@app.cli.command("create-admin")
@click.argument("username")
@click.argument("password")
def create_admin(username, password):
    """Creates an initial admin user."""
    with app.app_context():
        if User.query.filter_by(username=username).first():
            print("User already exists.")
            return
        user = User(username=username, password_hash=generate_password_hash(password))
        db.session.add(user)
        db.session.commit()
        print(f"Admin user '{username}' created successfully.")

# ── SSE infrastructure ───────────────────────────────────────────
_status_q: queue.Queue = queue.Queue(maxsize=2000)
_subscribers: list[queue.Queue] = []

def emit_status(router_id, status, message=''):
    try:
        _status_q.put_nowait(
            {'router_id': router_id, 'status': status,
             'message': message, 'timestamp': datetime.utcnow().isoformat()}
        )
    except queue.Full:
        pass

def _broadcaster():
    while True:
        try:
            msg = _status_q.get(timeout=1)
        except queue.Empty:
            continue
        dead = []
        for q in _subscribers:
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _subscribers.remove(q)

threading.Thread(target=_broadcaster, daemon=True).start()

# ── Decorators ───────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def _w(*a, **kw):
        if 'user_id' not in session:
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Unauthorized'}), 401
            return redirect(url_for('login', next=request.url))
        return f(*a, **kw)
    return _w

def csrf_protect(f):
    @wraps(f)
    def _w(*a, **kw):
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            tok = (request.headers.get('X-CSRF-Token')
                   or request.form.get('csrf_token')
                   or (request.get_json(silent=True) or {}).get('csrf_token'))
            if not validate_csrf_token(tok):
                abort(403, 'Invalid CSRF token')
        return f(*a, **kw)
    return _w

# ── Context processors ───────────────────────────────────────────
@app.context_processor
def _ctx():
    return {'csrf_token': generate_csrf_token()}

# ── Security headers ─────────────────────────────────────────────
@app.after_request
def _headers(resp):
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['X-Frame-Options'] = 'DENY'
    resp.headers['X-XSS-Protection'] = '1; mode=block'
    resp.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains; preload'
    resp.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    resp.headers['Permissions-Policy'] = (
        'geolocation=(), microphone=(), camera=()'
    )
    resp.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://cdn.jsdelivr.net; "
        "script-src-elem 'self' https://cdn.tailwindcss.com https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://fonts.googleapis.com; "
        "style-src-elem 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'none';"
    )
    return resp

# ── Template filters ─────────────────────────────────────────────
@app.template_filter('fmt_dt')
def _fmt_dt(v):
    if not v: return '—'
    try:
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace('Z', '+00:00')).strftime('%Y-%m-%d %H:%M:%S')
        return v.strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return str(v)

@app.template_filter('fmt_size')
def _fmt_size(s):
    if not s: return '0 B'
    for u in ('B', 'KB', 'MB', 'GB'):
        if s < 1024: return f'{s:.1f} {u}'
        s /= 1024
    return f'{s:.1f} TB'

@app.template_filter('status_class')
def _status_cls(s):
    return {
        'online':         'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
        'offline':        'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300',
        'error':          'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
        'backup_running': 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300 animate-pulse',
        'backup_success': 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
        'backup_failed':  'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
        'success':        'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
        'failed':         'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
    }.get(s, 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300')

# ── Routes: Auth ─────────────────────────────────────────────────
@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        if not validate_csrf_token(request.form.get('csrf_token')):
            flash('Session expired. Please retry.', 'error')
            return render_template('login.html')
            
        ip = request.remote_addr or 'unknown'
        key = f'_lr:{ip}'
        if not hasattr(app, '_attempts'):
            app._attempts = {}
            
        now = time.time()
        arr = [t for t in app._attempts.get(key, [])
               if now - t < config.LOGIN_WINDOW_SECONDS]
               
        if len(arr) >= config.LOGIN_MAX_ATTEMPTS:
            flash('Too many attempts. Wait 5 minutes.', 'error')
            return render_template('login.html')
        
        username = (request.form.get('username') or '').strip()[:100]
        password = request.form.get('password') or ''
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            session.clear()
            session['user_id'] = user.id
            session['username'] = user.username
            session.permanent = True
            
            user.last_login = datetime.utcnow()
            db.session.commit()
            
            app._attempts.pop(key, None)
            
            nxt = request.args.get('next') or url_for('dashboard')
            
            if not nxt.startswith('/') or nxt.startswith('//'):
                nxt = url_for('dashboard')
                
            return redirect(nxt)
        
        arr.append(now)
        app._attempts[key] = arr
        flash('Invalid username or password.', 'error')
        
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    session.clear()
    return redirect(url_for('login'))

# ── Routes: Dashboard ────────────────────────────────────────────
@app.route('/')
@login_required
def dashboard():
    routers = Router.query.order_by(Router.name).all()
    today_start = datetime.combine(datetime.utcnow().date(), dtime.min)
    stats = {
        'total': len(routers),
        'online': sum(1 for r in routers if r.last_status == 'online'),
        'backups': Backup.query.count(),
        'schedules': Schedule.query.filter_by(enabled=True).count(),
        'today': Backup.query.filter(Backup.created_at >= today_start).count(),
    }
    activity = ActivityLog.query.order_by(ActivityLog.created_at.desc()).limit(15).all()
    recent = Backup.query.order_by(Backup.created_at.desc()).limit(8).all()
    return render_template('dashboard.html', routers=routers,
                           stats=stats, activity=activity, recent=recent)

# ── Routes: Routers ──────────────────────────────────────────────
@app.route('/routers')
@login_required
def routers():
    rows = Router.query.order_by(Router.name).all()
    return render_template('routers.html', routers=rows)

@app.route('/routers/new', methods=['GET', 'POST'])
@login_required
@csrf_protect
def router_new():
    if request.method == 'POST':
        errors = _validate_router_form(request.form)
        if errors:
            for e in errors: flash(e, 'error')
            return render_template('router_form.html', router=request.form, is_edit=False)
        _insert_router(request.form)
        flash(f'Router "{request.form["name"]}" added.', 'success')
        return redirect(url_for('routers'))
    return render_template('router_form.html', router=None, is_edit=False)

@app.route('/routers/<int:rid>/edit', methods=['GET', 'POST'])
@login_required
@csrf_protect
def router_edit(rid):
    row = Router.query.get_or_404(rid)
    if request.method == 'POST':
        errors = _validate_router_form(request.form, is_edit=True)
        if errors:
            for e in errors: flash(e, 'error')
            return render_template('router_form.html', router=request.form, is_edit=True, rid=rid)
        _update_router(row, request.form)
        flash(f'Router "{request.form["name"]}" updated.', 'success')
        return redirect(url_for('routers'))
    return render_template('router_form.html', router=row, is_edit=True, rid=rid)

@app.route('/routers/<int:rid>/delete', methods=['POST'])
@login_required
@csrf_protect
def router_delete(rid):
    row = Router.query.get_or_404(rid)
    for s in Schedule.query.filter_by(router_id=rid).all():
        sched.remove_schedule_job(s.id)
    name = row.name
    db.session.delete(row)
    db.session.commit()
    log_activity(rid, 'router_deleted', 'success', f'"{name}" removed')
    flash(f'Router "{name}" deleted.', 'success')
    return redirect(url_for('routers'))

@app.route('/api/routers/test', methods=['POST'])
@login_required
@csrf_protect
def api_test_inline():
    d = request.get_json(silent=True) or request.form
    host = (d.get('host') or '').strip()
    port = validate_port(d.get('port', 22)) or 22
    username = (d.get('username') or '').strip()
    password = d.get('password', '')
    auth_method = d.get('auth_method', 'password')
    ssh_key = d.get('ssh_key', '')
    if not validate_hostname(host):
        return jsonify({'success': False, 'message': 'Invalid host.'})
    if not username:
        return jsonify({'success': False, 'message': 'Username required.'})
    try:
        c = MikrotikClient(
            host=host, port=port, username=username,
            password=password if auth_method == 'password' else None,
            ssh_key=ssh_key if auth_method == 'key' else None,
            timeout=12,
        )
        ok, info = c.test_connection()
        return jsonify({'success': ok, 'message': 'OK' if ok else str(info), 'info': info if ok else None})
    except Exception as exc:
        logger.exception('Inline router test failed')
        return jsonify({'success': False, 'message': 'Connection failed.'})

@app.route('/api/routers/<int:rid>/test', methods=['POST'])
@login_required
@csrf_protect
def api_test_saved(rid):
    row = Router.query.get_or_404(rid)
    pwd = decrypt_password(row.password_enc) if row.password_enc else ''
    key = decrypt_password(row.ssh_key_enc) if row.ssh_key_enc else ''
    try:
        c = MikrotikClient(host=row.host, port=row.port, username=row.username, password=pwd, ssh_key=key, timeout=12)
        ok, info = c.test_connection()
        row.last_status = 'online' if ok else 'offline'
        if ok: row.last_seen = datetime.utcnow()
        db.session.commit()
        log_activity(rid, 'connection_test', 'success' if ok else 'failed', 'OK' if ok else str(info))
        emit_status(rid, row.last_status, 'Connection OK' if ok else str(info))
        return jsonify({'success': ok, 'message': str(info) if not ok else 'OK', 'info': info if ok else None})
    except Exception as exc:
        row.last_status = 'error'
        db.session.commit()
        logger.exception('Saved router test failed')
        return jsonify({'success': False, 'message': 'Connection failed.'})

# ── Router form helpers ──────────────────────────────────────────
def _validate_router_form(form, is_edit=False):
    errors = []
    name = (form.get('name') or '').strip()
    host = (form.get('host') or '').strip()
    port = validate_port(form.get('port', 22))
    username = (form.get('username') or '').strip()
    auth_method = form.get('auth_method', 'password')
    password = form.get('password', '')
    ssh_key = form.get('ssh_key', '')
    if not name or len(name) > 100: errors.append('Name is required (max 100 chars).')
    if not host or not validate_hostname(host): errors.append('A valid IP address or hostname is required.')
    if port is None: errors.append('Port must be 1–65535.')
    if not username or len(username) > 50: errors.append('Username is required (max 50 chars).')
    if auth_method == 'password' and not password and not is_edit: errors.append('Password is required.')
    if auth_method == 'key' and not ssh_key and not is_edit: errors.append('SSH private key is required.')
    if len(form.get('notes', '') or '') > 2000: errors.append('Notes too long (max 2000 chars).')
    return errors

def _insert_router(form):
    router = Router(
        name=form.get('name').strip(),
        host=form.get('host').strip(),
        port=validate_port(form.get('port', 22)) or 22,
        username=form.get('username').strip(),
        auth_method=form.get('auth_method', 'password'),
        enabled=bool(form.get('enabled')),
        tags=(form.get('tags') or '').strip()[:200],
        notes=(form.get('notes') or '').strip()[:2000]
    )
    password = form.get('password', '')
    ssh_key = form.get('ssh_key', '')
    if password: router.password_enc = encrypt_password(password)
    if ssh_key: router.ssh_key_enc = encrypt_password(ssh_key)
    db.session.add(router)
    db.session.commit()
    log_activity(router.id, 'router_created', 'success', f'"{router.name}" added')

def _update_router(router, form):
    router.name = form.get('name').strip()
    router.host = form.get('host').strip()
    router.port = validate_port(form.get('port', 22)) or 22
    router.username = form.get('username').strip()
    router.auth_method = form.get('auth_method', 'password')
    router.enabled = bool(form.get('enabled'))
    router.tags = (form.get('tags') or '').strip()[:200]
    router.notes = (form.get('notes') or '').strip()[:2000]
    
    password = form.get('password', '')
    ssh_key = form.get('ssh_key', '')
    if password: router.password_enc = encrypt_password(password)
    if ssh_key: router.ssh_key_enc = encrypt_password(ssh_key)
    db.session.commit()
    log_activity(router.id, 'router_updated', 'success', f'"{router.name}" updated')

# ── Backup execution ─────────────────────────────────────────────
def perform_backup(router_id, backup_type_str, triggered_by='manual', schedule_id=None):
    router = Router.query.get(router_id)
    if not router: return None
    if backup_type_str not in ('full', 'config'): return None
    
    btype = BackupType.FULL if backup_type_str == 'full' else BackupType.CONFIG
    emit_status(router_id, 'backup_running', f'Starting {backup_type_str} backup…')
    safe_name = sanitize_filename(router.name)
    date_str = datetime.now().strftime('%Y-%m-%d')
    
    try:
        bdir = safe_join_path(config.BACKUP_DIR, safe_name, date_str)
    except ValueError:
        logger.error(f'Path error for router {router_id}')
        return None
    os.makedirs(bdir, exist_ok=True)
    
    pwd = decrypt_password(router.password_enc) if router.password_enc else ''
    key = decrypt_password(router.ssh_key_enc) if router.ssh_key_enc else ''
    client = None
    try:
        client = MikrotikClient(host=router.host, port=router.port, username=router.username, password=pwd, ssh_key=key, timeout=30)
        client.connect()
        emit_status(router_id, 'backup_running', 'Creating backup on router…')
        remote_name = client.create_backup(btype, safe_name)
        emit_status(router_id, 'backup_running', 'Downloading file…')
        local_name = sanitize_filename(remote_name)
        local_path = safe_join_path(bdir, local_name)
        client.download_file(remote_name, local_path)
        fsize = os.path.getsize(local_path)
        client.delete_file(remote_name)
        rel = os.path.relpath(local_path, config.BACKUP_DIR)
        
        backup = Backup(router_id=router_id, backup_type=backup_type_str, filename=local_name,
                        file_path=rel, file_size=fsize, status='success', triggered_by=triggered_by)
        db.session.add(backup)
        router.last_status = 'online'
        router.last_seen = datetime.utcnow()
        db.session.commit()
        
        log_activity(router_id, 'backup', 'success', f'{backup_type_str} ({fsize} bytes)', json.dumps({'backup_id': backup.id}))
        emit_status(router_id, 'backup_success', f'Completed: {local_name}')
        
        if schedule_id:
            _apply_retention(router_id, schedule_id)
            sched_obj = Schedule.query.get(schedule_id)
            if sched_obj:
                sched_obj.last_run = datetime.utcnow()
                db.session.commit()
                sched.reload_all()
        return backup.id
    except Exception as exc:
        msg = str(exc)
        backup = Backup(router_id=router_id, backup_type=backup_type_str, status='failed',
                        error_message=msg, triggered_by=triggered_by)
        db.session.add(backup)
        router.last_status = 'error'
        db.session.commit()
        log_activity(router_id, 'backup', 'failed', msg)
        emit_status(router_id, 'backup_failed', msg)
        logger.exception(f'Backup failed for router {router_id}')
        return None
    finally:
        if client: client.close()

def _apply_retention(router_id, schedule_id):
    s = Schedule.query.get(schedule_id)
    if not s or not s.keep_count: return
    keep = s.keep_count
    bk = Backup.query.filter_by(router_id=router_id, status='success').order_by(Backup.created_at.desc()).all()
    if len(bk) <= keep: return
    for b in bk[keep:]:
        fp = os.path.join(config.BACKUP_DIR, b.file_path)
        if is_safe_path(config.BACKUP_DIR, fp) and os.path.exists(fp):
            try: os.remove(fp)
            except OSError as e: logger.warning(f'rm {fp}: {e}')
        db.session.delete(b)
    db.session.commit()

@app.route('/api/routers/<int:rid>/backup', methods=['POST'])
@login_required
@csrf_protect
def api_trigger_backup(rid):
    router = Router.query.get_or_404(rid)
    data = request.get_json(silent=True) or {}
    btype = data.get('backup_type', 'full')
    if btype not in ('full', 'config'):
        return jsonify({'success': False, 'message': 'Invalid type'}), 400
    user = session.get('username', 'unknown')
    
    def _bg():
        with app.app_context():
            perform_backup(rid, btype, triggered_by=f'manual:{user}')
    
    threading.Thread(target=_bg, daemon=True).start()
    return jsonify({'success': True, 'message': f'{btype} backup started'})

# ── Routes: Schedules ────────────────────────────────────────────
@app.route('/schedules')
@login_required
def schedules():
    rows = Schedule.query.order_by(Schedule.name).all()
    routers = Router.query.filter_by(enabled=True).order_by(Router.name).all()
    return render_template('schedules.html', schedules=rows, routers=routers)

@app.route('/schedules/new', methods=['POST'])
@login_required
@csrf_protect
def schedule_new():
    f = request.form
    name = (f.get('name') or '').strip()
    router_id = f.get('router_id', type=int)
    backup_type = f.get('backup_type', 'full')
    cron_expr = (f.get('cron_expr') or '').strip()
    enabled = bool(f.get('enabled'))
    keep_count = f.get('keep_count', 10, type=int)
    
    errors = []
    if not name or len(name) > 100: errors.append('Name is required (max 100 chars).')
    if not router_id: errors.append('Router is required.')
    if backup_type not in ('full', 'config'): errors.append('Invalid backup type.')
    if not cron_expr: errors.append('Cron expression is required.')
    else:
        try:
            from apscheduler.triggers.cron import CronTrigger
            CronTrigger.from_crontab(cron_expr)
        except Exception:
            errors.append(f'Invalid cron expression: {cron_expr}')
    if not (1 <= (keep_count or 10) <= 1000): errors.append('Keep count must be 1–1000.')
    if not Router.query.get(router_id): errors.append('Router not found.')
    
    if errors:
        for e in errors: flash(e, 'error')
        return redirect(url_for('schedules'))
    
    s = Schedule(router_id=router_id, name=name, backup_type=backup_type,
                 cron_expr=cron_expr, enabled=enabled, keep_count=keep_count)
    db.session.add(s)
    db.session.commit()
    
    if enabled: sched.add_schedule_job(s)
    log_activity(router_id, 'schedule_created', 'success', f'"{name}"')
    flash(f'Schedule "{name}" created.', 'success')
    return redirect(url_for('schedules'))

@app.route('/schedules/<int:sid>/delete', methods=['POST'])
@login_required
@csrf_protect
def schedule_delete(sid):
    s = Schedule.query.get_or_404(sid)
    sched.remove_schedule_job(sid)
    name = s.name
    db.session.delete(s)
    db.session.commit()
    log_activity(s.router_id, 'schedule_deleted', 'success', f'"{name}"')
    flash(f'Schedule "{name}" deleted.', 'success')
    return redirect(url_for('schedules'))

@app.route('/api/schedules/<int:sid>/toggle', methods=['POST'])
@login_required
@csrf_protect
def schedule_toggle(sid):
    s = Schedule.query.get_or_404(sid)
    s.enabled = not s.enabled
    db.session.commit()
    if s.enabled: sched.add_schedule_job(s)
    else: sched.remove_schedule_job(s.id)
    return jsonify({'success': True, 'enabled': s.enabled})

# ── Routes: History ──────────────────────────────────────────────
@app.route('/history')
@login_required
def history():
    page = max(1, request.args.get('page', 1, type=int))
    per_page = 50
    rf = request.args.get('router', '', type=str)
    sf = request.args.get('status', '', type=str)
    
    q = Backup.query
    if rf: q = q.filter_by(router_id=rf)
    if sf: q = q.filter_by(status=sf)
    
    pagination = q.order_by(Backup.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    activity = ActivityLog.query.order_by(ActivityLog.created_at.desc()).limit(100).all()
    routers = Router.query.order_by(Router.name).all()
    
    return render_template('history.html', backups=pagination.items, activity=activity,
                           routers=routers, page=page, per_page=per_page,
                           total=pagination.total, rf=rf, sf=sf)

# ── Routes: Download / Delete backup ─────────────────────────────
@app.route('/backups/<int:bid>/download')
@login_required
def backup_download(bid):
    b = Backup.query.get_or_404(bid)
    if b.status != 'success': abort(404)
    fp = os.path.join(config.BACKUP_DIR, b.file_path)
    if not is_safe_path(config.BACKUP_DIR, fp): abort(403)
    if not os.path.isfile(fp): abort(404)
    log_activity(b.router_id, 'backup_download', 'success', f'Downloaded {b.filename}')
    return send_file(fp, as_attachment=True, download_name=b.filename)

@app.route('/backups/<int:bid>/delete', methods=['POST'])
@login_required
@csrf_protect
def backup_delete(bid):
    b = Backup.query.get_or_404(bid)
    if b.file_path:
        fp = os.path.join(config.BACKUP_DIR, b.file_path)
        if is_safe_path(config.BACKUP_DIR, fp) and os.path.exists(fp):
            try: os.remove(fp)
            except OSError as e: logger.warning(f'rm {fp}: {e}')
    db.session.delete(b)
    db.session.commit()
    log_activity(b.router_id, 'backup_deleted', 'success', f'Removed {b.filename}')
    flash('Backup deleted.', 'success')
    return redirect(url_for('history'))

# ── Routes: Settings ─────────────────────────────────────────────
@app.route('/settings', methods=['GET', 'POST'])
@login_required
@csrf_protect
def settings():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'change_password':
            cur = request.form.get('current_password', '')
            new = request.form.get('new_password', '')
            con = request.form.get('confirm_password', '')
            user = User.query.get(session['user_id'])
            if not user or not check_password_hash(user.password_hash, cur):
                flash('Current password incorrect.', 'error')
            elif len(new) < 8:
                flash('New password must be ≥ 8 characters.', 'error')
            elif new != con:
                flash('Passwords do not match.', 'error')
            else:
                user.password_hash = generate_password_hash(new)
                db.session.commit()
                flash('Password changed.', 'success')
        elif action == 'test_all':
            for r in Router.query.filter_by(enabled=True).all():
                def _bg(rid=r.id):
                    with app.app_context():
                        _bg_test(rid)
                threading.Thread(target=_bg, daemon=True).start()
            flash('Testing all routers in background…', 'info')
        return redirect(url_for('settings'))
    return render_template('settings.html')

def _bg_test(rid):
    router = Router.query.get(rid)
    if not router: return
    pwd = decrypt_password(router.password_enc) if router.password_enc else ''
    key = decrypt_password(router.ssh_key_enc) if router.ssh_key_enc else ''
    try:
        c = MikrotikClient(host=router.host, port=router.port, username=router.username, password=pwd, ssh_key=key, timeout=10)
        ok, _ = c.test_connection()
        router.last_status = 'online' if ok else 'offline'
        if ok: router.last_seen = datetime.utcnow()
        db.session.commit()
        emit_status(rid, router.last_status, 'OK' if ok else 'Connection failed')
    except Exception as exc:
        router.last_status = 'error'
        db.session.commit()
        emit_status(rid, 'error', str(exc))

# ── SSE endpoint ─────────────────────────────────────────────────
@app.route('/api/events')
@login_required
def sse_events():
    def stream():
        q: queue.Queue = queue.Queue(maxsize=200)
        _subscribers.append(q)
        try:
            yield 'event: ping\ndata: {}\n\n'
            while True:
                try:
                    msg = q.get(timeout=15)
                    yield f'event: status\ndata: {json.dumps(msg)}\n\n'
                except queue.Empty:
                    yield 'event: ping\ndata: {}\n\n'
        finally:
            if q in _subscribers:
                _subscribers.remove(q)
    return Response(
        stream_with_context(stream()),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no', 'Connection': 'keep-alive'},
    )

@app.route('/api/routers/status')
@login_required
def api_routers_status():
    routers = Router.query.order_by(Router.name).all()
    return jsonify({'routers': [{'id': r.id, 'name': r.name, 'last_status': r.last_status, 'last_seen': r.last_seen.isoformat() if r.last_seen else None} for r in routers]})

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

# ── Error handlers ───────────────────────────────────────────────
@app.errorhandler(404)
def _e404(e):
    if request.path.startswith('/api/'): return jsonify({'error': 'Not found'}), 404
    return render_template('error.html', code=404, msg='Page not found'), 404

@app.errorhandler(403)
def _e403(e):
    if request.path.startswith('/api/'): return jsonify({'error': 'Forbidden'}), 403
    return render_template('error.html', code=403, msg='Access denied'), 403

@app.errorhandler(500)
def _e500(e):
    if request.path.startswith('/api/'): return jsonify({'error': 'Internal error'}), 500
    return render_template('error.html', code=500, msg='Internal server error'), 500

# ── Bootstrap ────────────────────────────────────────────────────
sched.set_status_queue(_status_q)
sched.init_scheduler(app)
sched.reload_all()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)