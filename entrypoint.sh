#!/bin/sh

set -e

# ==========================================================
# CONFIGURATION
# ==========================================================
if [ -z "$DATABASE_URL" ]; then
    echo "ERROR: DATABASE_URL environment variable is not set"
    exit 1
fi

export FLASK_APP=app.py
export FLASK_ENV=${FLASK_ENV:-production}

MIGRATION_DIR="/app/migrations"
MIGRATION_VERSIONS_DIR="${MIGRATION_DIR}/versions"

# ==========================================================
# MYSQL
# ==========================================================
echo "Menunggu database MySQL siap..."

until python - <<'PY'
import socket
import os
from urllib.parse import urlparse

url = os.environ['DATABASE_URL']
info = urlparse(url)

host = info.hostname
port = info.port or 3306

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.settimeout(2)
    s.connect((host, port))
PY
do
    echo "Database belum siap, menunggu 2 detik..."
    sleep 2
done

echo "Database siap!"

# ==========================================================
# FLASK MIGRATION
# ==========================================================
echo "Memeriksa Flask-Migrate..."

# Pastikan directory migration tersedia
if [ ! -d "$MIGRATION_DIR" ]; then
    echo "Directory migration belum ada."
    echo "Membuat directory: $MIGRATION_DIR"

    mkdir -p "$MIGRATION_DIR"
fi

# ==========================================================
# FIRST INITIALIZATION
# ==========================================================
if [ ! -f "$MIGRATION_DIR/alembic.ini" ]; then

    echo "=============================================="
    echo "Migration belum pernah diinisialisasi."
    echo "Menjalankan: flask db init"
    echo "=============================================="

    flask db init

fi

if [ ! -d "$MIGRATION_VERSIONS_DIR" ]; then

    echo "Directory migration versions belum ada."

    mkdir -p "$MIGRATION_VERSIONS_DIR"

fi

# ==========================================================
# FIRST MIGRATION
# ==========================================================
MIGRATION_COUNT=$(find "$MIGRATION_VERSIONS_DIR" \
    -maxdepth 1 \
    -type f \
    -name "*.py" \
    ! -name "__init__.py" \
    | wc -l)

if [ "$MIGRATION_COUNT" -eq 0 ]; then

    echo "=============================================="
    echo "Belum ada migration."
    echo "Membuat initial migration..."
    echo "=============================================="

    flask db migrate -m "Initial migration"

else

    echo "Migration sudah tersedia."
    echo "Jumlah migration: $MIGRATION_COUNT"

fi

# ==========================================================
# APPLY MIGRATION
# ==========================================================
echo "=============================================="
echo "Memeriksa database migration..."
echo "Menjalankan flask db upgrade..."
echo "=============================================="

flask db upgrade

echo "Database migration selesai."

# ==========================================================
# CREATE ADMIN
# ==========================================================
if [ -n "$ADMIN_USERNAME" ] && [ -n "$ADMIN_PASSWORD" ]; then

    echo "Memeriksa admin '$ADMIN_USERNAME'..."

    python - <<'PY'
from app import app, db, User
from werkzeug.security import generate_password_hash
import os

with app.app_context():

    username = os.environ['ADMIN_USERNAME']
    password = os.environ['ADMIN_PASSWORD']

    existing_user = User.query.filter_by(
        username=username
    ).first()

    if not existing_user:

        user = User(
            username=username,
            password_hash=generate_password_hash(password)
        )

        db.session.add(user)
        db.session.commit()

        print(f"Admin user created: {username}")

    else:

        print(f"Admin user already exists: {username}")

PY

fi

# ==========================================================
# START APPLICATION
# ==========================================================
if [ "${FLASK_ENV:-production}" = "development" ]; then

    echo "Menjalankan Flask development server..."

    exec flask run \
        --host=0.0.0.0 \
        --port=5000

else

    echo "Memulai Gunicorn..."

    exec gunicorn \
        -w 4 \
        -b 0.0.0.0:5000 \
        --timeout 120 \
        --access-logfile - \
        --error-logfile - \
        app:app

fi