# SPEC - Order Management System

Sources merged: "Order Processing & Billing" requirements PDF (costing, payments, documents) and the
AlkanZa_jewels.xlsx sheet (eBay order columns, real sample rows). Where they differ, this file decides.

## 1. Scope

In: orders for ~12 eBay accounts, automatic costing, part-payments with component allocation, invoices,
receipts, outstanding balances, search/filter, Excel and PDF export, Excel import, audit log, backups.

Out: payment gateway, eBay API sync, inventory, shipping label purchase, multi-currency accounting,
tax filing. (GST line is supported but off by default, see 7.3.)

## 2. Users and roles

| Role | Can do |
|---|---|
| Owner | Everything. Manage accounts, users, settings. Approve overpayment. Void payments. Delete orders. View audit log. Import. Backup. |
| Accounts | Create and edit orders, record payments, issue invoices and receipts, run reports, export. Cannot void payments, delete orders, or change rates in Settings. |
| Staff | Create and edit orders (not rates, not payments). View only for payments and reports. |

- Each user is assigned to one or more eBay accounts (Owner sees all). A user never sees an unassigned account's data.
- Login by email and password. Password reset by Owner. Lock for 15 minutes after 5 failed attempts.
- Sensitive edits (gold rate, labour rate, diamond value, purity, weights after a payment exists) need Accounts or Owner.

## 3. Data model

### 3.1 EbayAccount
code (short, unique, e.g. ALK01), display_name, ebay_username (unique), active (bool), billing_name,
billing_address, phone, email, tax_id (optional), default_gold_rate (optional), notes.
About 12 rows. Never deleted, only deactivated. Inactive accounts stay visible in history.

### 3.2 Order
Identity
- account (FK, required)
- serial_no: system generated, globally unique, never reused, shown as SR NO. Not editable.
- sales_no: eBay sales record number. Integer. Unique per account. Required.
- challan_no: text, optional.
- mfg_order_no: text, optional (example 26/J/1430).
- order_date (required), ship_by_date (optional, not before order_date)
- buyer_username (trimmed, lowercased), item_title (required, max 255), quantity (int >= 1, informational)
- image (optional, jpg/png/webp, max 5 MB, resized to max 1600 px, thumbnail generated)
- igi_cert_no (optional), tracking_no (optional, trimmed)
- fulfilment_status: New, In production, Ready, Shipped, Cancelled. Shipped requires tracking_no.

Sale side
- usd_sold Decimal(12,2) optional, fx_rate Decimal(10,4) default from Settings (91.0000 today)
- inr_sold Decimal(14,2) required. Form auto-suggests usd_sold * fx_rate, user may overwrite (real payouts differ).
- ship_charges Decimal(14,2) default 0 (INR)
- platform_fees_inr Decimal(14,2) default 0 (eBay fees, so earnings are not overstated)

Metal and weight (all are order totals, not per piece)
- purity Decimal(6,4) fraction, 0.0001 to 1.0000 (UI takes percent, example 59.5)
- gross_wt Decimal(12,4) > 0, dia_ct Decimal(12,4) >= 0, other_wt Decimal(12,4) >= 0

Rates and inputs
- gold_rate Decimal(14,2): INR per gram of pure 995 gold. Defaults from Settings at creation, then snapshotted on the order so old orders never change when the daily rate changes.
- lab_rate Decimal(14,2): INR per gram of net gold weight.
- diamond_value Decimal(14,2): entered, not calculated.

Derived (stored on save by `core/costing.py`, never editable, never accepted from a form)
net_wt, pure_995, gold_amount, labour_amount, total_bill, net_earnings.

System fields: version (int, starts 1), created_by, created_at, updated_by, updated_at, is_deleted, deleted_by, deleted_at, delete_reason.

Constraints: unique(account, sales_no); unique(serial_no); check net_wt > 0; all money >= 0; purity between 0 and 1.
Orders with is_deleted=true are hidden everywhere except the audit log and an Owner-only "Deleted orders" list with Restore.

### 3.3 Payment
order (FK), payment_date, amount Decimal(14,2) > 0, method (Cash, Bank Transfer, UPI, Cheque, Other),
reference_no (required for Bank Transfer, UPI, Cheque), remarks, receipt_no (system, unique),
created_by, created_at, status (Posted or Voided), voided_by, voided_at, void_reason, overpayment_approved_by, overpayment_reason.

### 3.4 PaymentAllocation
payment (FK), component (Gold, Diamond, Labour), amount Decimal(14,2) > 0. One row per component used.
Rule: sum(allocations) == payment.amount, exactly.

Payments are immutable. To correct a mistake: Owner voids it with a reason, then records a new one. Voided payments stay visible, struck through, and are excluded from all sums.

### 3.5 Invoice
invoice_no (system, unique, format INV-YYYY-00001), order (FK), issued_at, issued_by, snapshot (JSON of issuer, bill-to, lines, totals at issue time).
Re-downloading always renders from the snapshot so a printed invoice never changes later. If the order changes after issue, the UI offers "Issue revised invoice" which creates a new number and marks the old one Superseded.

### 3.6 Settings (single row, Owner edit)
company_name, address, phone, email, tax_id, logo, default_gold_rate, default_fx_rate, invoice_footer_text,
payment_direction ("paid_out" or "received", only changes labels and titles, default paid_out),
gst_enabled (default off), gst_rate_percent.

### 3.7 AuditLog (append only, no edit, no delete, not even in admin)
timestamp, actor, action, object_type, object_id, account, before (JSON), after (JSON), note, ip.

## 4. Calculation rules (single source: core/costing.py)

Use a Decimal context with 28 digits. Rounding is ROUND_HALF_UP, applied only where stated.

| Field | Rule |
|---|---|
| net_wt | gross_wt - (dia_ct / 5) - other_wt. Must be > 0 or the order is rejected. |
| pure_995 | net_wt * purity / 0.995. Full precision. Display 3 dp, store 6 dp for display only. Never feed a rounded value back into a formula. |
| gold_amount | round2(pure_995_full * gold_rate) |
| labour_amount | round2(net_wt * lab_rate) |
| diamond_value | round2(input) |
| total_bill | gold_amount + diamond_value + labour_amount (sum of rounded components) |
| net_earnings | inr_sold - total_bill - ship_charges - platform_fees_inr |

Why components are rounded before summing: outstanding must be able to reach exactly 0.00 so status can become Paid. Comparing against an unrounded bill would leave 0.0003 outstanding forever.

Payment math (always computed from Posted allocations, never stored as totals):
- component_received = sum of Posted allocations for that component
- component_outstanding = component bill - component_received
- total_received, total_outstanding likewise
- Status: Unpaid if total_received = 0; Paid if total_outstanding = 0 and total_bill > 0; otherwise Partially Paid. Overpaid (approved) shows "Paid (credit 1,234.00)".

Legacy note: the old Excel divides by 0.995 in Pure 995 and uses gold rate 15000 in "Gold Ret". Both are confirmed by the sample rows and reproduced here. See golden_cases.json (6 real rows, exact expected values).

Recalculation: when any input changes the server recomputes all derived fields. The form shows a live preview via JS that mirrors the rules, but the saved numbers always come from the server. If a payment exists and an edit would push any component's bill below its received amount, reject with: "This change would make the bill lower than what is already paid for Gold. Ask an Owner to void a payment first."

## 5. Validation (server side, all of it)

- Required fields present; text trimmed; buyer_username lowercased; tracking_no and sales_no trimmed.
- Numbers: reject negative, NaN, more than allowed decimals (weights 3 dp entry, money 2 dp entry, fx 4 dp).
- Purity entered as percent 0.01 to 100. If someone types 0.595 the UI asks "Did you mean 59.5%?" instead of silently accepting.
- Duplicate sales_no within the same account is blocked with a link to the existing order.
- Warn (not block) if: dia_ct is 0 while diamond_value > 0; diamond_value is 0 while dia_ct > 0; net earnings negative; gold_rate differs from Settings default by more than 10 percent.
- Image: type by content not extension, max 5 MB, strip EXIF location.
- Payment: amount > 0; allocations sum exactly to amount; each allocation <= that component's outstanding unless overpayment approved; payment_date not in the future; reference_no rules per method; order not deleted or Cancelled.
- Overpayment: only an Owner can approve, must enter a reason, recorded on the payment and in the audit log.

## 6. Screens (keep them few and obvious)

Global: top bar with Account switcher (All accounts, then 12 names, big and searchable), user menu, search box. Current account is always visible as a coloured tag so nobody enters an order under the wrong ID. Order form has the account pre-filled from the switcher and shows it in the page title.

1. Dashboard: table, one row per account: open orders, total bill, received, outstanding, this month net earnings. Click a row to open that account's orders.
2. Orders list (spreadsheet-style grid): columns follow the reference image, then billing columns. Sticky header and first 3 columns, horizontal scroll, footer totals row for weights, gold amount, diamond value, labour amount, total bill, received, outstanding, net earnings. Search: sales no, serial no, challan no, mfg order no, buyer, tracking. Filters: date range, account, payment status, fulfilment status. Sort by any column. Page size 50. Totals reflect the filter, not just the page. Under 768 px wide, show expandable cards instead of the grid.
3. Order form: single page, grouped cards in this order: Identity, Sale, Metal and weight, Rates, Live costing preview (read only), Photo. Save and "Save and add another". Unsaved changes warning.
4. Order detail: costing breakdown table (Gold, Diamond, Labour, Total with Bill, Received, Outstanding), payment history oldest first, status chip, buttons Record payment, Download invoice, Edit, Delete (Owner).
5. Record payment: date, amount, method, reference, remarks. Allocation table with three rows (Gold, Diamond, Labour), each showing outstanding. One helper button only: "Split automatically" (fills gold, then diamond, then labour, up to each outstanding). Otherwise the user types amounts. Live line: "Left to allocate: 0.00" and Save stays disabled until it is exactly 0.00.
6. Receipt: one per payment, shows allocation and remaining balances after that payment. PDF, A4.
7. Reports: Outstanding by account; Orders export; Payments export; Account statement PDF (orders, bill, paid, balance). All respect filters and the user's account access. Export to .xlsx and .pdf.
8. Import: see section 9.
9. Audit log (Owner): filter by user, account, date, object, action.
10. Admin area (Owner): eBay accounts, users and access, settings, deleted orders, backups.

Design: clean minimalism, one accent colour, large tap targets, at least 16 px text, high contrast, no hidden gestures, no modal stacks. Destructive buttons are red and always ask to confirm. Deleting an order needs typing DELETE and a reason. Tooltips on every calculated field show its formula.

## 7. Documents

### 7.1 Invoice (PDF, A4)
Header: issuer from Settings. Bill-to: the eBay account's billing profile (snapshotted). Meta: invoice no, date, order refs (sales no, challan, mfg order no), item title, quantity.
Line items, always three: Gold (pure 995 weight, rate, amount), Diamond (carats, value), Labour (net weight, rate, amount). Then total, received to date, outstanding. Footer text from Settings. Item photo thumbnail if present.
### 7.2 Receipt (PDF, A4 or half page)
Receipt no, date, order refs, method, reference, amount, allocation by component, remaining balance per component and total after this payment, who recorded it.
### 7.3 Tax
Off by default. If gst_enabled, add a GST line computed on total_bill at gst_rate_percent, shown separately, rounded half up to 2 dp. Do not build tax logic beyond this.

## 8. Exports
- Excel: openpyxl, values not formulas, header row frozen, number formats applied (weights 0.000, money #,##0.00), totals row at bottom, sheet per export type, filter = what is on screen.
- PDF: reportlab, landscape for lists, repeat header on every page, page numbers, generated-on stamp, filter summary printed at the top.
- File names: `orders_<account or ALL>_<yyyymmdd>.xlsx`.

## 9. Excel import (for the existing AlkanZa layout)
Owner or Accounts user picks an eBay account and uploads .xlsx.
Expected headers (case and spacing tolerant): Sales No., Order Date, Ship By Date, Buyer Username, Photos, Item Title, Quantity, $ me Sold For, INR RS., PURITY, GROSS WT, TTL DIA WT CTS., OTHER, NET WT, PURE 995, IGI, LAB RATE, LAB AMOUNT, DIAMOND VALUE, AMOUNT, Gold Ret, Tracking No., Ship Charges, NET Earnings.
- Dry run first. Preview table with a status per row: New, Duplicate (same account and sales_no, skipped), Error (reason), Difference (sheet value vs system value, flagged, still importable).
- System recalculates everything. Sheet values for NET WT, PURE 995, LAB AMOUNT, AMOUNT, Gold Ret, NET Earnings are read only to compare, never stored.
- `$ me Sold For` may be text with a "$" or a number. Parse both. Trim trailing spaces in usernames and tracking numbers.
- Gold rate is not a column. Gold Ret = PURE 995 * 15000, so default gold_rate to 15000 for imported rows unless the user sets another in the import form.
- Photos: read embedded images and attach to the row they are anchored to.
- Commit is all or nothing in one transaction. Re-importing the same file creates zero new rows.
- A gap in Sales No. (example 104 missing) is shown as information, not an error.
- Seed data: `seed/seed_rows.json` and `seed/images/` hold the 6 real rows and their photos for first-run demo and tests.

## 10. Reliability and security
- Optimistic locking with `version`. On conflict: "Someone else just changed this order. Your changes were not saved. Reload to see theirs."
- Payment creation locks the order row (`select_for_update`) so two simultaneous payments cannot both pass the outstanding check.
- Nightly database backup (management command `backup_db`, scheduled by the host), 30 days retained. Owner button "Download full backup" gives an .xlsx of everything plus a zip of photos. Backup restore steps documented in README.
- `/healthz` returns OK only if the database answers.
- HTTPS only, secure cookies, CSRF on, password validators on, login throttling, file upload limits, admin URL not at /admin/.
- Friendly 403, 404, 500 pages. Errors logged with request id.
- Migrations are additive. No destructive migration without a written note.

## 11. Acceptance tests (must exist and pass)

Costing
- All calc_cases in golden_cases.json match exactly.
- Changing gold_rate on Settings does not change any existing order.
- Net weight <= 0 is rejected.

Payments
- All payment_cases steps in golden_cases.json behave as listed.
- Two simultaneous payments that together exceed the outstanding: exactly one succeeds.
- Voided payments are excluded from sums and still listed.
- Receipt shows correct remaining balances after each payment, in date and creation order.

Access
- A user assigned to accounts A and B cannot fetch, list, export, or guess the URL of an order in account C.
- Staff cannot record payments. Accounts cannot void. Only Owner can approve overpayment.

Integrity
- Duplicate (account, sales_no) blocked. Same sales_no in different accounts allowed.
- Stale version save is rejected.
- Every write in the tests produced exactly one matching AuditLog row.
- Import twice = zero duplicates. Import with one bad row commits nothing.

UI smoke (Playwright, optional)
- Create order, record split payment, download invoice and receipt, export Excel, on desktop and 390 px wide.

## 12. Milestones (stop and report after each)

| # | Deliver | Done when |
|---|---|---|
| M0 | Project scaffold, settings, models, migrations, `core/costing.py`, golden tests | `pytest` green, golden tests pass, no UI yet |
| M1 | Auth, roles, eBay accounts, user-account access, account switcher, dashboard shell | Access tests pass |
| M2 | Order CRUD, grid, filters, totals, image upload, soft delete, versioning | Order and integrity tests pass |
| M3 | Payments, allocation, void, overpayment approval, status | All payment cases pass, concurrency test passes |
| M4 | Invoice, receipt, Excel and PDF exports, reports | Files open correctly, numbers match screen |
| M5 | Excel import with dry run and photos, seed command | Import tests pass on the real file |
| M6 | Audit viewer, backups, healthz, error pages, mobile cards, deploy notes, README, UAT checklist | `check --deploy` clean, UAT checklist signed |

## 13. Assumptions and open questions (defaults in bold)

| # | Question | Default used |
|---|---|---|
| 1 | Do payments mean money paid out to the manufacturer, or received from a customer? | **Paid out** (labels only, flip in Settings) |
| 2 | Round amounts to 2 decimals or whole rupees? The old sheet hand-rounded labour to whole rupees in one row. | **2 decimals, half up** |
| 3 | Is the gold rate one daily rate for everyone, or set per order? | **Default from Settings, snapshotted per order, editable by Accounts or Owner** |
| 4 | Serial number per account or across all accounts? | **Across all accounts, never reused** |
| 5 | Is quantity > 1 possible with totals entered per order? | **Yes, weights and values are order totals** |
| 6 | Who is the invoice issuer and who is billed? | **Issuer = Settings company, bill-to = eBay account profile** |
| 7 | GST needed on invoices? | **Off** |
| 8 | Hosting | **Managed host with Postgres and daily backups, one URL for all staff** |
