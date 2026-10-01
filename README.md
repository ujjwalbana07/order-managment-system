# Order Management System

Django 5.2 / Python 3.12 application for jewellery order costing, allocated payments and billing across eBay accounts. The M0-M6 implementation is present. Automated verification and local browser checks are recorded in `UAT.md`; production deployment and Owner acceptance are separate operational steps.

## Run locally

```sh
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python manage.py migrate
python manage.py createsuperuser --email owner@example.com
python manage.py runserver
```

In this prepared workspace, the existing `.venv/bin/python` can run management commands directly.

Visit `http://127.0.0.1:8000/`. The bootstrap command creates an Owner. No default password is installed. Owners configure company details in Settings, add eBay accounts, then add users and their assignments under Users and access.

Optional demo, using the supplied six real rows and photos:

```sh
python manage.py seed_demo --owner owner@example.com --account ALK01
```

Re-running the command skips existing account/sales-number pairs. Demo data is never loaded automatically.

## Features

- Case-insensitive email login; five consecutive failed attempts lock a user for 15 minutes. Owners reset passwords and locks. Resetting a password invalidates the user's existing sessions; an Owner resetting their own password keeps the current session.
- Owner, Accounts and Staff roles; assigned-account querysets are used for detail views, searches, photos, reports and exports. Owners see all accounts. The account switcher rechecks assignments on every request. Inactive accounts remain visible for history.
- Order creation/editing, searchable spreadsheet grid, sorting, account/date/status filters, 50-row pages, totals over the entire filter, and expandable phone cards. Calculated values are read-only and recomputed by the server.
- Optimistic version checks prevent stale edits. Deletion requires Owner permission, DELETE confirmation and a reason. Restore retains serial and sales numbers.
- Image content validation, 5 MB limit, metadata removal, 1600 px maximum size, generated thumbnails and authenticated photo URLs.
- Decimal costing with 28-digit precision and half-up rounding. Full-precision pure gold feeds the formula; six-decimal storage is only for display. Live preview and INR suggestions call the same server calculation module.
- Payments allocated to Gold, Diamond and Labour; exact sum validation, component balance checks, row locking, Owner-only overpayment approval with reason, and immutable payments corrected by voiding. History retains voided entries.
- Sequential invoice numbers, immutable issue-time snapshots, revised invoices, A4 invoice/receipt PDFs, and optional GST shown separately. Receipts calculate remaining balances in payment-date/creation order.
- Scoped Excel/PDF order and payment exports, outstanding reports, account statements and dashboard totals. Excel values are literal, headers frozen, numeric formats applied and formula-like text escaped. Wide PDFs use column panels with repeated headings.
- Excel import with dry-run New/Duplicate/Error/Difference rows, legacy rounding comparisons, gaps as information, embedded images, transactional commit and idempotent duplicate handling.
- Owner audit viewer, append-only audit events, request IDs, friendly error pages, database health endpoint, nightly backup command and Owner business-data/photograph downloads.

## Business decisions

The supplied `SPEC.md` decides conflicts. The matching copy and instructions are in `oms-pack/`; golden tests read the original JSON unchanged.

- Negative net earnings are allowed, as section 5 calls for a warning on losses. Other money is nonnegative; payments and allocations are strictly positive.
- Gold defaults to 15000.00 and FX to 91.0000 until company settings exist. An account-specific default gold rate takes precedence on its order form. Defaults are copied onto orders, so later setting changes do not rewrite history.
- Weights are entered to three decimals and stored to four. Purity is a fraction in storage and a percentage in forms; sub-1% entries require explicit confirmation. The import accepts either percentage values over 1 or fraction values up to 1, matching the supplied sheet.
- Staff can create orders using the default gold rate and a zero labour rate. The spec provides no default labour rate and prohibits Staff from changing rates; Accounts or Owner must set labour rates. No invented company labour default was added.
- Open orders exclude Shipped, Cancelled and soft-deleted orders. Monthly earnings use order date. Orders/statements use order-date filters; payment exports use payment dates.
- Paid out is the default payment direction; the setting changes labels only. GST does not alter component payment allocation amounts.
- All business changes use atomic services. Audit entries represent business operations, including their allocation or permission changes. Internal counters and session storage are not separate business events. Credentials and password hashes are never included in business audit snapshots.
- At least one active Owner must remain. Imported pre-M1 non-Owner users start unassigned until an Owner grants account access.
- Original images are retained after replacements for history and included in backups. Imported source workbooks are retained privately in the database.

## Tests

```sh
pytest
python manage.py check
python manage.py makemigrations --check --dry-run
```

Tests cover exact golden costing and payment cases, model/database constraints, role/account isolation, CSRF, lockout expiry, revoked access, private photos, stale writes, payment concurrency, immutable invoices, readable PDFs, Excel contents, import rollback/idempotency, audit events and backup restoration.

Optional browser smoke test is `tests/browser_smoke.py`. It requires Playwright, installed Chrome, an isolated running application containing company settings and an active eBay account, and a private credentials file:

```json
{"email": "test-owner@example.com", "password": "test-only-password", "account_id": 1}
```

```sh
OMS_SMOKE_CREDENTIALS=/private/path/credentials.json \
OMS_SMOKE_URL=http://127.0.0.1:8765 python tests/browser_smoke.py
```

Run against a fresh test database because it creates sales numbers 501 and 502 and records payments. It exercises desktop and 390 px phone flows, saves PDFs/Excel and screenshots in `artifacts/`, and checks for browser errors and page overflow. Never use production credentials for this test.

## Deployment

Use one managed host with PostgreSQL and persistent media/backup disks. Install `requirements.txt` (development browser tools are optional), set the environment from `.env.example`, and use a private random secret. Django does not automatically load `.env`; configure the host environment or explicitly source your private file.

```sh
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py check --deploy
gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 2 --access-logfile -
```

Use `DJANGO_DEBUG=false`, the real hostname in `DJANGO_ALLOWED_HOSTS`, HTTPS and an HTTPS-terminating reverse proxy. Set `TRUST_HTTPS_PROXY=true` only when the trusted proxy replaces `X-Forwarded-Proto` itself. HSTS, secure cookies, CSRF protection, password validation, nosniff and a restrictive referrer policy are enabled in production. Serve static assets through WhiteNoise. Do not expose `MEDIA_ROOT`, backups or the database as public static paths; order images are served through scoped authenticated views.

`GET /healthz` answers `OK` only when a database query succeeds. Log output includes request IDs for failures. Set the reverse proxy's maximum upload size to 12 MB; the application separately validates 5 MB images and 10 MB workbooks, limits workbook expansion and limits row counts.

Database migrations are additive. M1 normalizes user emails and fails explicitly if existing emails are empty or collide case-insensitively; correct those records before retrying. No destructive migration was introduced.

## Backups and restore

Nightly command (requires PostgreSQL `pg_dump` on production hosts):

```sh
python manage.py backup_db
```

The command writes private `oms_backup_<UTC timestamp>.zip` archives to `BACKUP_ROOT`, using SQLite's consistent backup API or PostgreSQL custom-format dumps, and includes retained media and a metadata file. It removes only its own archives older than 30 days. Configure the host scheduler, for example at 02:00 UTC daily:

```cron
0 2 * * * cd /srv/oms && /srv/oms/.venv/bin/python manage.py backup_db >> /srv/oms/backup.log 2>&1
```

The scheduled process must receive the same environment as the web application. Store another copy off-host using the host's backup facilities. The local implementation does not configure a remote host or scheduler automatically.

Restore into a separate validation environment first:

1. Stop application writers. Retain a copy of the current database and media.
2. Unpack a trusted backup into a private directory and inspect `metadata.json` for database vendor.
3. SQLite: replace the configured database file with `database.sqlite3` while all application processes are stopped. Run `PRAGMA integrity_check` on the restored database.
4. PostgreSQL: create an empty target database and run `pg_restore --no-owner --exit-on-error --dbname=<target> database.dump` using the configured database credentials. Do not restore over a live database.
5. Restore the archive's `media/` contents into `MEDIA_ROOT`, preserving private filesystem permissions. Keep database and media from the same backup together.
6. Run `python manage.py migrate`, `python manage.py check`, and verify `/healthz`. Sign in and check account access, representative orders, payments and downloaded documents before enabling writers.

The Owner **Download full backup** button returns a ZIP containing `data.xlsx`, complete `records.json` values for data too long for an Excel cell, original import workbooks and photos. Password hashes are excluded from this business export. It is useful for review and portability; use nightly database archives for a complete application restore.

The SQLite backup/restore and competing-payment tests run locally. PostgreSQL is configured but was not available in this workspace; validate PostgreSQL concurrency, `pg_dump`/`pg_restore`, persistent storage and the scheduler on the deployment host before launch.
