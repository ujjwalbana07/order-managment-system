from django.db.models import Q, Sum
from django.core.exceptions import ValidationError
from django.utils.dateparse import parse_date
from orders.models import Order


def filtered_orders(user, params, selected=None):
    queryset = Order.objects.for_user(user).select_related('account').order_by('-order_date', '-serial_no')
    account = params.get('account') or selected
    if account and str(account).isdigit():
        queryset = queryset.filter(account_id=account)
    elif account:
        return queryset.none()
    search = params.get('q', '').strip()
    if search:
        conditions = Q(buyer_username__icontains=search) | Q(tracking_no__icontains=search) | Q(challan_no__icontains=search) | Q(mfg_order_no__icontains=search) | Q(item_title__icontains=search)
        if search.isdigit():
            conditions |= Q(sales_no=int(search)) | Q(serial_no=int(search))
        queryset = queryset.filter(conditions)
    if params.get('status'):
        queryset = queryset.filter(fulfilment_status=params['status'])
    for key, lookup in [('from', 'order_date__gte'), ('to', 'order_date__lte')]:
        if params.get(key):
            try:
                value = parse_date(params[key])
            except ValueError:
                value = None
            if value is None:
                raise ValidationError('Enter dates in YYYY-MM-DD format.')
            queryset = queryset.filter(**{lookup: value})
    if params.get('payment_status'):
        from payments.services import balances
        wanted = params['payment_status']
        matching = []
        for order in queryset.prefetch_related('payments__allocations'):
            status = balances(order)['status']
            if status == wanted or (wanted == 'Paid' and status.startswith('Paid (credit')):
                matching.append(order.pk)
        queryset = queryset.filter(pk__in=matching)
    sort = params.get('sort', '-order_date')
    valid = {field.name for field in Order._meta.fields} - {'image', 'thumbnail', 'delete_reason'}
    if sort.lstrip('-') in valid:
        queryset = queryset.order_by(sort, 'serial_no')
    if sort.lstrip('-') in ('received', 'outstanding', 'payment_status'):
        from payments.services import balances
        from django.db.models import Case, When, IntegerField
        key = {'received': 'total_received', 'outstanding': 'total_outstanding', 'payment_status': 'status'}[sort.lstrip('-')]
        rows = [(order.pk, balances(order)[key]) for order in queryset.prefetch_related('payments__allocations')]
        rows.sort(key=lambda row: row[1], reverse=sort.startswith('-'))
        queryset = queryset.order_by(Case(*[When(pk=pk, then=index) for index, (pk, _) in enumerate(rows)], output_field=IntegerField())) if rows else queryset.none()
    return queryset


def order_totals(queryset):
    totals = queryset.aggregate(**{name: Sum(name, default=0) for name in
        ('gross_wt', 'dia_ct', 'other_wt', 'net_wt', 'pure_995', 'gold_amount', 'diamond_value', 'labour_amount', 'total_bill', 'net_earnings')})

    from payments.services import balances
    from decimal import Decimal
    totals.update(received=Decimal('0'), outstanding=Decimal('0'))
    for order in queryset.prefetch_related('payments__allocations'):
        result = balances(order)
        totals['received'] += result['total_received']
        totals['outstanding'] += result['total_outstanding']
    return totals
