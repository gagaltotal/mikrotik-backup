# MikroTik Backup Dashboard

Aplikasi web untuk manajemen backup konfigurasi router MikroTik dengan database MySQL, penjadwalan, dan antarmuka pengguna berbasis Flask.

Fitur utama:
- Simpan konfigurasi backup router MikroTik ke file
- Kelola router, jadwal backup, dan aktivitas backup
- Melindungi aplikasi dengan login admin
- Menggunakan Flask, SQLAlchemy, Flask-Migrate, dan Gunicorn

## Persyaratan

- Docker dan Docker Compose untuk menjalankan dalam container
- Python 3.12 untuk pengembangan lokal
- MySQL 8.0 ketika dijalankan di luar Docker

## Screenshot Apps

![Screen Capture](https://raw.githubusercontent.com/gagaltotal/mikrotik-backup/refs/heads/main/images/Screenshot%20from%202026-08-12%2014-28-18.png)

![Screen Capture](https://raw.githubusercontent.com/gagaltotal/mikrotik-backup/refs/heads/main/images/Screenshot%20from%202026-08-12%2014-39-50.png)

![Screen Capture](https://raw.githubusercontent.com/gagaltotal/mikrotik-backup/refs/heads/main/images/Screenshot%20from%202026-08-12%2014-40-05.png)

![Screen Capture](https://raw.githubusercontent.com/gagaltotal/mikrotik-backup/refs/heads/main/images/Screenshot%20from%202026-08-12%2015-06-31.png)

![Screen Capture](https://raw.githubusercontent.com/gagaltotal/mikrotik-backup/refs/heads/main/images/Screenshot%20from%202026-08-12%2015-06-42.png)

![Screen Capture](https://raw.githubusercontent.com/gagaltotal/mikrotik-backup/refs/heads/main/images/Screenshot%20from%202026-08-12%2015-06-51.png)

## Instalasi dan pengembangan lokal

1. Salin contoh konfigurasi environment:
   
   ```
   cp .env-example .env
   ```

2. Ubah nilai dalam `.env` untuk lingkungan lokal Anda.

3. Buat virtual environment dan pasang dependensi:
   ```
   python -m venv .venv
   source .venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. Jalankan migrasi database:

   ```
   flask db init
   flask db migrate -m "Initial migration"
   flask db upgrade
   flask create-admin admin passwordanda123
   ```

5. Jalankan aplikasi untuk development:
   ```
   export FLASK_APP=app.py
   export FLASK_ENV=development
   flask run --host=0.0.0.0 --port=5000
   ```

6. Buka browser ke:
   ```
   http://localhost:5000
   ```

## Docker Compose (development / production ringan)

1. Salin contoh environment dan sesuaikan nilai:

   ```
   cp .env-example .env
   ```

2. Jalankan Compose:

   ```
   docker-compose up --build
   ```

3. Akses aplikasi:

   ```
   http://localhost:5000

   Atau

   http://localhost:8500
   ```

Pengaturan ini otomatis memetakan direktori `backups/` dan `logs/` dari host ke container.

## Environment variables

- `DATABASE_URL`: URL koneksi SQLAlchemy untuk MySQL
- `SECRET_KEY`: kunci rahasia Flask untuk sesi dan CSRF
- `SESSION_COOKIE_SECURE`: `true` jika HTTPS digunakan, `false` untuk HTTP lokal
- `FLASK_ENV`: `production` atau `development`
- `ADMIN_USERNAME` / `ADMIN_PASSWORD`: jika diisi, admin baru akan dibuat saat startup
- `MYSQL_DATABASE`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_ROOT_PASSWORD`: konfigurasi MySQL untuk Docker

## Service systemd (production)

1. Copy file service ke `/etc/systemd/system/mikrobackup.service`.
2. Siapkan file environment pada `/etc/mikrotik-backup.env` dengan nilai:
   ```
   DATABASE_URL=... 
   SECRET_KEY=...
   SESSION_COOKIE_SECURE=true
   FLASK_ENV=production
   ADMIN_USERNAME=admin
   ADMIN_PASSWORD=Secret123
   ```
3. Pastikan aplikasi di-deploy ke `/opt/mikrotik-backup` dan virtual environment berada di `/opt/mikrotik-backup/.venv`.
4. Reload systemd dan aktifkan service:
   ```
   sudo systemctl daemon-reload
   sudo systemctl enable mikrobackup.service
   sudo systemctl start mikrobackup.service
   ```

## Catatan produksi

- Jangan simpan file `.env` berisi password ke repositori.
- Pastikan `SECRET_KEY` adalah nilai acak panjang.
- Gunakan HTTPS di depan Gunicorn jika menjalankan di internet publik.
- Volume `backups/` dan `logs/` harus bisa ditulis oleh container atau user service.

## Struktur repositori penting

- `app.py`: aplikasi Flask utama
- `config.py`: konfigurasi Flask dan SQLAlchemy
- `db.py`: model database
- `docker-compose.yml`: setup container
- `Dockerfile`: definisi image aplikasi
- `entrypoint.sh`: startup container, migrasi, dan Gunicorn
- `mikrobackup.service`: contoh unit systemd
- `requirements.txt`: dependensi Python
- `migrations/`: skrip Alembic versioned
- `backups/`, `logs/`: direktori data runtime
