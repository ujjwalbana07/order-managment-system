# Acceptance and release checklist

Engineering verification date: 01-Oct-2026 (UTC).

Implementation coverage: M0-M6 application code is present. M6 is not declared operationally closed until the deployment-host checks and Owner acceptance below are completed.

## Recorded verification

```text
Python 3.12.14 / Django 5.2.17 / SQLite
pytest: 137 passed in 13.01s
Django system check: no issues
Migration drift check: no changes detected
Production-mode check --deploy: no issues
```

Chrome / Playwright browser smoke, isolated database and test credentials:

```text
1440px desktop: login, order/photo, costing preview, allocated payment,
invoice PDF, receipt PDF, Excel export and layout passed.
390px phone: the same flow passed; expandable order cards visible;
no page overflow or JavaScript errors.
```

Browser artifacts are in `artifacts/`. The source test is `tests/browser_smoke.py`. Browser verification used an isolated temporary SQLite database, not the application database.

## Engineering acceptance

- [x] All six supplied costing cases match exact Decimal results.
- [x] Every supplied payment-case step is exercised, including allocation mismatch, voiding, overpayment rejection, paid/unpaid status and edits below paid amounts.
- [x] Duplicate account/sales numbers, nonpositive net weight, negative money and negative sales numbers are rejected.
- [x] Gold rate snapshots remain unchanged after Settings edits.
- [x] Role policy and account-scoped reads are tested. Unassigned order, photo and invoice URLs do not expose data; exports use the same account scope.
- [x] Owner-only account/user management, audit access, backups and password resets reject other roles.
- [x] Five failed logins lock access for 15 minutes. Password resets, role changes, deactivation and revoked account assignments take effect.
- [x] CSRF is enforced on writes and logout is POST-only.
- [x] Stale order versions are rejected; Owner deletion needs confirmation and a reason; restoration keeps order identity.
- [x] Images are checked by content, resized, stripped of metadata and served through authenticated routes.
- [x] Two competing payments on SQLite result in exactly one successful payment when their combined allocation would exceed the component balance.
- [x] Invoice revisions preserve previous snapshots and receive new sequential numbers. PDFs are parsed successfully; monetary values are checked against the snapshot.
- [x] Receipt balances follow payment-date and creation order.
- [x] Filtered Excel exports contain the expected rows, totals, frozen headers and number formats; formula-like strings remain literal text.
- [x] Import preview shows the legacy rounding difference and sales-number gap. All six supplied photos are attached to the right rows.
- [x] Re-import creates no duplicate orders. A bad row commits nothing. An error during commit rolls back orders, audit entries and newly saved image files.
- [x] Atomic service writes produce matching audit events; payment and audit history cannot be rewritten through queryset update operations.
- [x] Health check fails when the database does not answer; errors carry request IDs and a friendly error page.
- [x] Full business export includes retained/deleted records and photographs without password hashes. Long values are preserved outside Excel's cell-length limit.
- [x] SQLite database archive restores successfully and passes integrity checking; retention removes only the application's expired backups.
- [x] Desktop and 390px phone workflows have been exercised in Chrome.
- [x] Migrations apply, no migration drift remains, and production security checks pass with production settings.

Engineering verification: completed by Codex using automated tests and browser inspection. This is an engineering record, not an Owner's signature.

## Deployment-host verification

The workspace has no configured production host and no local PostgreSQL server. These items remain for that environment:

- [ ] Configure the real hostname, private secret, PostgreSQL credentials and persistent private media/backup storage.
- [ ] Apply migrations, collect static assets, run `check --deploy`, and verify HTTPS/proxy behavior with secure cookies.
- [ ] Run the suite, especially the transaction/concurrency test, against PostgreSQL.
- [ ] Run `backup_db` with the production PostgreSQL tools and restore a copy into an isolated database with `pg_restore`.
- [ ] Configure and observe the nightly scheduler, 30-day retention and off-host copying.
- [ ] Verify that media and backup directories cannot be fetched as public static URLs.
- [ ] Confirm `/healthz`, application logging and a representative invoice, receipt and image after deployment.

## Owner acceptance

- [ ] Confirm company issuer details, account billing profiles, payment direction and GST setting.
- [ ] Confirm account assignments for Owner, Accounts and Staff users using real roles.
- [ ] Review the provisional Staff labour-rate behavior: Staff cannot edit rates and new Staff orders start with zero labour rate until Accounts or Owner sets it.
- [ ] Review a representative real order, split payment, correction/void, revised invoice, receipt and account statement.
- [ ] Review a dry run of the operational workbook before committing it.
- [ ] Approve the desktop and phone workflow and the backup/restore operating instructions.

Owner name: ____________________

Acceptance date: ____________________

Signature or recorded approval reference: ____________________
