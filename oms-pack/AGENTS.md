# AGENTS.md - Order Management System (12 eBay accounts)

Read SPEC.md fully before writing code. Read golden_cases.json before touching any calculation.
Work one milestone at a time (SPEC section 12). Stop after each milestone and report what passes.

## Mission
A simple, rigid web app where non-technical staff manage jewellery orders for about 12 eBay accounts:
order entry, automatic costing (gold, diamond, labour), part-payments allocated by component,
invoices, receipts, outstanding balances, Excel/PDF export. No payment gateway. Manual payment entry only.

## Non-negotiables
1. It must not break. Boring, proven tech only. Fewer moving parts beats features.
2. All money and weights use `decimal.Decimal`. Never float. Never store a rounded value as an input.
3. One calculation module (`core/costing.py`) is the only place formulas live. Views, templates, JS,
   exports and importer all call it. No formula is duplicated anywhere else.
4. The browser is never trusted. The server recalculates and validates everything. JS is preview only.
5. Every write goes through a service function inside `transaction.atomic()`. Views never write directly.
6. Every create, update, void, delete, import and permission change writes an append-only AuditLog row.
7. Nothing is hard deleted. Orders are soft deleted. Payments are voided, never edited or deleted.
8. Two people editing the same order must never silently overwrite each other (version check).
9. A user only ever sees accounts they are assigned to. Enforce in the queryset layer, not in templates.
10. Every user-facing error is plain English and says what to do next. No stack traces, no raw codes.

## Stack (do not swap without asking)
- Python 3.12, Django 5.x, server-rendered templates, plain CSS (one file), tiny vanilla JS. No SPA, no npm build.
- PostgreSQL in production, SQLite for local dev and tests. Settings via environment variables.
- Libraries: openpyxl (Excel in/out), reportlab (PDF), Pillow (images), whitenoise, gunicorn, pytest-django.
- Media files (order photos) on a persistent disk or S3-compatible bucket, configured by env var.

## Conventions
- Apps: `core` (costing, money utils), `accounts` (eBay accounts, users, access), `orders`, `payments`,
  `documents` (invoice, receipt, exports), `imports`, `audit`.
- Money: stored Decimal(14,2). Weights: Decimal(12,4). Purity: Decimal(6,4) as a fraction (0.595).
- UI shows purity as a percent (59.5) and converts on save. Display weights 3 dp, money 2 dp, Indian digit grouping.
- Dates stored as dates, displayed `dd-mmm-yyyy`. Timezone Asia/Kolkata for display, UTC in DB.
- No em dashes anywhere in UI copy, docs or comments. Use plain hyphens or commas.
- Copy style in UI: short, calm, polite. Buttons say what they do ("Record payment", "Download invoice").

## Testing rules
- `pytest` must pass before any milestone is called done. Add tests with the code, not after.
- `tests/test_costing_golden.py` loads golden_cases.json and asserts exact Decimal equality. Never loosen it.
- Add tests for every validation rule and every permission rule in SPEC.
- Run `python manage.py check --deploy` and fix warnings before M6 closes.

## When unsure
Choose the option that is harder to misuse for a non-technical person. If a rule is ambiguous in SPEC,
pick the safest reading, implement it, and list it under "Assumptions" in your milestone report.
Do not add features that are not in SPEC.
