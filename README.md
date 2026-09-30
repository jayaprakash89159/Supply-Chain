# Supply Chain Portal

Django 5.2 portal with PostgreSQL deployment support, authenticated read-only directories, and admin-managed master data.

## Run with Docker Compose

Prerequisites: Docker Engine with the Compose plugin.

```powershell
Copy-Item .env.example .env
```

Edit `.env` and set a unique `DJANGO_SECRET_KEY` and strong `DB_PASSWORD`. For a deployment behind HTTPS, set `DJANGO_ALLOWED_HOSTS` to the public host names, `DJANGO_CSRF_TRUSTED_ORIGINS` to their HTTPS origins, and enable `DJANGO_SECURE_SSL_REDIRECT=1` and `DJANGO_SECURE_COOKIES=1`. Enable HSTS only after HTTPS is confirmed end-to-end.

Start the portal:

```powershell
docker compose up --build -d
```

Open `http://localhost:8000/health/` to check readiness and `http://localhost:8000/` for the portal. The web port binds to loopback by default; for public access, place it behind a TLS-terminating reverse proxy and configure the allowed hosts, trusted origins, and secure-cookie/redirect settings. The first container startup applies database migrations and collects static files. Persistent PostgreSQL and uploaded-media data use named volumes.

Create the first administrator:

```powershell
docker compose exec web python manage.py createsuperuser
```

Sign in, then manage organizations and reference data through `/admin/`. Normal accounts created under **Users** are read-only and cannot enter Django admin. User passwords are handled by Django's authentication system.

Stop the services without deleting data:

```powershell
docker compose down
```

To also permanently delete the database and uploaded files, use `docker compose down --volumes` only when that data is no longer needed.

## Office network (LAN) hosting

Step-by-step guide: [LAN_HOSTING.md](LAN_HOSTING.md).

By default the portal is reachable only from this PC at http://localhost:8000. To open it to the office network, change these `.env` settings:

- `WEB_BIND=0.0.0.0` makes it reachable from the office network; `127.0.0.1` limits it to this PC.
- `WEB_PORT` is the port users open (80 lets the address drop the `:port`).
- `DJANGO_ALLOWED_HOSTS` / `DJANGO_CSRF_TRUSTED_ORIGINS` must list every address people type (for example `192.168.0.239` and `jayaprakash`, with the port if it is not 80). Run `docker compose up -d` after any change.

On Windows, run `setup-lan-access.ps1` once as Administrator: it sets the network to Private and allows inbound TCP 80 (edit the script for another port) on Private/Domain networks. Ask the network admin to reserve the PC's IP in the router (DHCP reservation) so the address does not change. Traffic is plain HTTP; add a TLS reverse proxy before using the portal outside the office network.
## Local development

Install `requirements.txt`, then run `python manage.py migrate` and `python manage.py runserver`. Local development defaults to SQLite and `DEBUG=1`; production settings require a unique `DJANGO_SECRET_KEY` and an explicit `DJANGO_ALLOWED_HOSTS` value.

## Current scope

Suppliers and Labour & Composite subcontractors (one list, matching the "Labour & Composite" workbook columns), with trades, materials, brands and projects stored as linked records. Everything is managed in the portal UI by administrators: add, edit, Excel template download and upload for both directories, and user access (Read only / Administrator). The dashboard search (`/search/`) looks across both directories by mobile number (spaces, dashes and +91 ignored), name, vendor code, GSTIN, PAN, email, city and more, and shows which field matched. Django admin is not needed for day-to-day work.
