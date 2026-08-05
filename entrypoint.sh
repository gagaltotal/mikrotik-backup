#!/bin/sh
set -e

if [ -z "$DATABASE_URL" ]; then
  echo "DATABASE_URL environment variable is not set"
  exit 1
fi

echo "Menunggu database MySQL siap..."

DB_HOST=$(python - <<'PY'
import os
from urllib.parse import urlparse
url = os.environ['DATABASE_URL']
print(urlparse(url).hostname or '')
PY
)
DB_PORT=$(python - <<'PY'
import os
from urllib.parse import urlparse
url = os.environ['DATABASE_URL']
print(urlparse(url).port or 3306)
PY
)

until python - <<'PY'
import socket, os
from urllib.parse import urlparse
url = os.environ['DATABASE_URL']
info = urlparse(url)
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.settimeout(2)
    s.connect((info.hostname, info.port or 3306))
PY
 do
  echo "Database belum siap, menunggu 2 detik..."
  sleep 2
done

echo "Database siap! Menjalankan migrasi..."
export FLASK_APP=app.py
export FLASK_ENV=${FLASK_ENV:-production}
flask db upgrade

if [ -n "$ADMIN_USERNAME" ] && [ -n "$ADMIN_PASSWORD" ]; then
  echo "Membuat admin '$ADMIN_USERNAME' jika belum ada..."
  python - <<'PY'
from app import app, db, User
from werkzeug.security import generate_password_hash
import os
with app.app_context():
    username = os.environ['ADMIN_USERNAME']
    password = os.environ['ADMIN_PASSWORD']
    if not User.query.filter_by(username=username).first():
        user = User(username=username, password_hash=generate_password_hash(password))
        db.session.add(user)
        db.session.commit()
        print('Admin user created:', username)
PY
fi

if [ "${FLASK_ENV:-production}" = "development" ]; then
  echo "Menjalankan Flask development server..."
  exec flask run --host=0.0.0.0 --port=5000
else
  echo "Memulai Gunicorn..."
  exec gunicorn -w 4 -b 0.0.0.0:5000 --timeout 120 --access-logfile - --error-logfile - app:app
fi
