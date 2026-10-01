from decimal import Decimal
from django.utils import timezone
from payments.services import balances

ORDER_COLUMNS = [('serial_no', 'SR NO'), ('account', 'Account'), ('sales_no', 'Sales no'), ('order_date', 'Order date'),
    ('ship_by_date', 'Ship by'), ('buyer_username', 'Buyer'), ('item_title', 'Item title'), ('quantity', 'Quantity'),
    ('usd_sold', 'USD sold'), ('fx_rate', 'FX rate'), ('inr_sold', 'INR sold'), ('purity', 'Purity (%)'),
    ('gross_wt', 'Gross weight'), ('dia_ct', 'Diamond carats'), ('other_wt', 'Other weight'), ('net_wt', 'Net weight'),
    ('pure_995', 'Pure 995'), ('igi_cert_no', 'IGI'), ('gold_rate', 'Gold rate'), ('gold_amount', 'Gold amount'),
    ('lab_rate', 'Labour rate'), ('labour_amount', 'Labour amount'), ('diamond_value', 'Diamond value'),
    ('total_bill', 'Total bill'), ('tracking_no', 'Tracking'), ('ship_charges', 'Shipping'), ('platform_fees_inr', 'Platform fees'),
    ('net_earnings', 'Net earnings'), ('challan_no', 'Challan'), ('mfg_order_no', 'Manufacturing'), ('fulfilment_status', 'Order status')]


def order_rows(queryset):
    headers = [label for name, label in ORDER_COLUMNS] + ['Received', 'Outstanding', 'Payment status']
    rows = []
    totals = ['Totals'] + [''] * (len(headers)-1)
    summed = {'gross_wt', 'dia_ct', 'other_wt', 'net_wt', 'pure_995', 'gold_amount', 'labour_amount', 'diamond_value', 'total_bill', 'net_earnings'}
    for order in queryset.prefetch_related('payments__allocations'):
        balance = balances(order)
        row = [str(order.account) if name == 'account' else getattr(order, name) for name, _ in ORDER_COLUMNS]
        row += [balance['total_received'], balance['total_outstanding'], balance['status']]
        rows.append(row)
    for index, (name, _) in enumerate(ORDER_COLUMNS):
        if name in summed:
            totals[index] = sum((row[index] for row in rows), Decimal('0'))
    for index in (-3, -2):
        totals[index] = sum((row[index] for row in rows), Decimal('0'))
    return headers, rows, totals


def account_report(accounts, orders):
    result = {account.pk: {'account': account, 'open_orders': 0, 'total_bill': Decimal('0'), 'total_received': Decimal('0'),
        'total_outstanding': Decimal('0'), 'month_earnings': Decimal('0')} for account in accounts}
    today = timezone.localdate()
    for order in orders.prefetch_related('payments__allocations'):
        if order.account_id not in result:
            continue
        row = result[order.account_id]
        balance = balances(order)
        row['open_orders'] += order.fulfilment_status not in ('Delivered', 'Returned', 'Cancelled')
        for name in ('total_bill', 'total_received', 'total_outstanding'):
            row[name] += balance[name]
        if (order.order_date.year, order.order_date.month) == (today.year, today.month):
            row['month_earnings'] += order.net_earnings
    return list(result.values())
