"""
Security utilities: credential encryption, input validation,
path-traversal prevention, CSRF token management.
"""
import os
import re
import ipaddress
import secrets
import hmac
from pathlib import Path
from cryptography.fernet import Fernet
from flask import session

_ENC_KEY_FILE = os.path.join(os.path.dirname(__file__), '.encryption_key')

def _get_encryption_key() -> bytes:
    if os.path.exists(_ENC_KEY_FILE):
        with open(_ENC_KEY_FILE, 'rb') as f:
            return f.read()
    key = Fernet.generate_key()
    fd = os.open(_ENC_KEY_FILE, os.O_WRONLY | os.O_CREAT, 0o600)
    os.write(fd, key)
    os.close(fd)
    return key

_fernet: Fernet | None = None

def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_get_encryption_key())
    return _fernet

def encrypt_password(password: str) -> bytes:
    if not password:
        return b''
    return _get_fernet().encrypt(password.encode('utf-8'))

def decrypt_password(encrypted: bytes) -> str:
    if not encrypted:
        return ''
    try:
        return _get_fernet().decrypt(encrypted).decode('utf-8')
    except Exception:
        return ''

# ── Input validation ──────────────────────────────────────────────────
_HOSTNAME_RE = re.compile(
    r'^(?=.{1,253}$)([a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)*'
    r'[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?$'
)

def validate_hostname(value: str) -> bool:
    """Accept IPv4, IPv6, or DNS hostname."""
    if not value or len(value) > 253:
        return False
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return bool(_HOSTNAME_RE.match(value))

def validate_port(value) -> int | None:
    try:
        p = int(value)
        return p if 1 <= p <= 65535 else None
    except (TypeError, ValueError):
        return None

_SAFE_FILENAME_RE = re.compile(r'[^a-zA-Z0-9._\-]')

def sanitize_filename(name: str) -> str:
    """Strip path separators and dangerous characters."""
    name = _SAFE_FILENAME_RE.sub('_', name or '').strip('._')
    return (name or 'unnamed')[:100]

def safe_join_path(base: str, *parts: str) -> str:
    """
    Join paths and guarantee the result stays inside *base*.
    Raises ValueError on path-traversal attempt (LFI prevention).
    """
    base_real = os.path.realpath(base)
    target = os.path.realpath(os.path.join(base_real, *parts))
    if target != base_real and not target.startswith(base_real + os.sep):
        raise ValueError(f'Path traversal blocked: {target}')
    return target

def is_safe_path(base: str, path: str) -> bool:
    base_real = os.path.realpath(base)
    target = os.path.realpath(path)
    return target == base_real or target.startswith(base_real + os.sep)

# ── CSRF tokens ───────────────────────────────────────────────────────
def generate_csrf_token() -> str:
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)
    return session['csrf_token']

def validate_csrf_token(token: str | None) -> bool:
    stored = session.get('csrf_token')
    if not stored or not token:
        return False
    return hmac.compare_digest(stored, token)