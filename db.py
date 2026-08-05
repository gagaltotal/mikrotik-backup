from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.security import generate_password_hash

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(120))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)

class Router(db.Model):
    __tablename__ = 'routers'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    host = db.Column(db.String(253), nullable=False)
    port = db.Column(db.Integer, nullable=False, default=22)
    username = db.Column(db.String(50), nullable=False)
    password_enc = db.Column(db.LargeBinary)
    ssh_key_enc = db.Column(db.LargeBinary)
    auth_method = db.Column(db.String(20), default='password')
    enabled = db.Column(db.Boolean, default=True)
    tags = db.Column(db.String(200))
    notes = db.Column(db.Text)
    last_seen = db.Column(db.DateTime)
    last_status = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    backups = db.relationship('Backup', backref='router', cascade='all, delete-orphan')
    schedules = db.relationship('Schedule', backref='router', cascade='all, delete-orphan')

    @property
    def router_name(self):
        return self.name

class Backup(db.Model):
    __tablename__ = 'backups'
    id = db.Column(db.Integer, primary_key=True)
    router_id = db.Column(db.Integer, db.ForeignKey('routers.id', ondelete='CASCADE'), nullable=False)
    backup_type = db.Column(db.String(20), nullable=False)
    filename = db.Column(db.String(255), default='')
    file_path = db.Column(db.String(500), default='')
    file_size = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), nullable=False)
    error_message = db.Column(db.Text)
    triggered_by = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def router_name(self):
        return self.router.name if self.router else None

class Schedule(db.Model):
    __tablename__ = 'schedules'
    id = db.Column(db.Integer, primary_key=True)
    router_id = db.Column(db.Integer, db.ForeignKey('routers.id', ondelete='CASCADE'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    backup_type = db.Column(db.String(20), nullable=False)
    cron_expr = db.Column(db.String(100), nullable=False)
    enabled = db.Column(db.Boolean, default=True)
    keep_count = db.Column(db.Integer, default=10)
    last_run = db.Column(db.DateTime)
    next_run = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def router_name(self):
        return self.router.name if self.router else None
    
    @property
    def router_host(self):
        return self.router.host if self.router else None

class ActivityLog(db.Model):
    __tablename__ = 'activity_log'
    id = db.Column(db.Integer, primary_key=True)
    router_id = db.Column(db.Integer, db.ForeignKey('routers.id', ondelete='SET NULL'))
    action = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(50), nullable=False)
    message = db.Column(db.String(500))
    details = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    router = db.relationship('Router', backref='activity_logs')

    @property
    def router_name(self):
        return self.router.name if self.router else 'System'

def log_activity(router_id, action, status, message='', details=''):
    log = ActivityLog(
        router_id=router_id, action=action, status=status,
        message=message, details=details
    )
    db.session.add(log)
    db.session.commit()