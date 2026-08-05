import os
import secrets
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR = os.path.join(BASE_DIR, 'backups')
LOG_DIR = os.path.join(BASE_DIR, 'logs')

SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
SQLALCHEMY_TRACK_MODIFICATIONS = False
SQLALCHEMY_ENGINE_OPTIONS = {
    'pool_pre_ping': True,
    'pool_recycle': 3600,
}

_SECRET_KEY_FILE = os.path.join(BASE_DIR, '.secret_key')


def _get_secret_key() -> bytes:
    env_key = os.environ.get('SECRET_KEY')
    if env_key:
        return env_key.encode('utf-8') if isinstance(env_key, str) else env_key
    if os.path.exists(_SECRET_KEY_FILE):
        with open(_SECRET_KEY_FILE, 'rb') as f:
            return f.read()
    key = secrets.token_bytes(32)
    fd = os.open(_SECRET_KEY_FILE, os.O_WRONLY | os.O_CREAT, 0o600)
    os.write(fd, key)
    os.close(fd)
    return key

SECRET_KEY = _get_secret_key()

SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', 'false').lower() == 'true'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
PERMANENT_SESSION_LIFETIME = 3600 * 8

LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 300