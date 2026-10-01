from decimal import Decimal, DecimalException
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.http import FileResponse, HttpResponse, JsonResponse, Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from accounts.access import require, can
from accounts.context_processors import account_context
from accounts.models import EbayAccount
from accounts.views import form_error
from core.costing import calculate_costing, suggested_inr
from orders.forms import OrderForm
from orders.models import Order
from orders.queries import filtered_orders, order_totals
from orders.services import save_order, set_deleted, order_warnings, INPUT_FIELDS


@login_required
def order_list(request):
    account_context(request)
    try:
        queryset = filtered_orders(request.user, request.GET, request.session.get('account_id'))
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
        queryset = Order.objects.none()
    page = Paginator(queryset, 50).get_page(request.GET.get('page'))
    from payments.services import balances
    page.object_list = list(page.object_list.prefetch_related('payments__allocations'))
    for order in page.object_list:
        order.balance = balances(order)
    params = request.GET.copy()
    params.pop('page', None)
    sort_params = params.copy()
    sort_params.pop('sort', None)
    return render(request, 'orders/list.html', {'page': page, 'totals': order_totals(queryset), 'query': params.urlencode(),
        'sort_query': sort_params.urlencode(), 'statuses': Order._meta.get_field('fulfilment_status').choices,
        'can_delete_orders': can(request.user, 'delete_order')})


@login_required
def bulk_delete(request):
    require(request.user, 'delete_order')
    if request.method != 'POST':
        messages.error(request, 'Use the checkboxes on the Orders page, then click Delete selected.')
        return redirect('order_list')
    order_ids = []
    for raw_id in request.POST.getlist('order_ids'):
        try:
            order_ids.append(int(raw_id))
        except (TypeError, ValueError):
            continue
    reason = request.POST.get('reason', '').strip()
    if not order_ids:
        messages.error(request, 'Select at least one order to delete.')
        return redirect('order_list')
    if not reason:
        messages.error(request, 'Enter a delete reason before deleting selected orders.')
        return redirect('order_list')

    orders = list(Order.objects.for_user(request.user).filter(pk__in=order_ids).only('pk', 'version', 'sales_no'))
    found_ids = {order.pk for order in orders}
    deleted = 0
    failures = []
    for order in orders:
        try:
            set_deleted(actor=request.user, order_id=order.pk, version=order.version, deleted=True,
                reason=reason, confirmation='DELETE')
        except ValidationError as exc:
            failures.append(f'{order.sales_no}: {exc.messages[0]}')
        else:
            deleted += 1
    missing = len(set(order_ids) - found_ids)
    if deleted:
        messages.success(request, f'{deleted} selected order' + (' was' if deleted == 1 else 's were') + ' deleted. History is retained.')
    if missing:
        messages.error(request, f'{missing} selected order' + (' was' if missing == 1 else 's were') + ' no longer available.')
    for failure in failures[:5]:
        messages.error(request, failure)
    if len(failures) > 5:
        messages.error(request, f'{len(failures) - 5} more selected orders could not be deleted.')
    return redirect('order_list')


@login_required
def order_detail(request, pk):
    order = get_object_or_404(Order.objects.for_user(request.user).select_related('account'), pk=pk)
    from payments.services import balances
    return render(request, 'orders/detail.html', {'order': order, 'balance': balances(order),
        'payments': order.payments.prefetch_related('allocations').order_by('payment_date', 'created_at', 'pk'),
        'can_issue': can(request.user, 'issue_documents'), 'invoices': order.invoices.order_by('-issued_at'), 'can_pay': can(request.user, 'record_payment'), 'warnings': order_warnings(order)})


@login_required
def order_edit(request, pk=None):
    require(request.user, 'edit_order' if pk else 'create_order')
    order = get_object_or_404(Order.objects.for_user(request.user), pk=pk) if pk else None
    account_context(request)
    account = order.account if order else EbayAccount.objects.for_user(request.user).filter(pk=request.session.get('account_id')).first()
    form = OrderForm(request.POST if request.method == 'POST' else None, request.FILES or None,
        actor=request.user, instance=order, account=account)
    duplicate = None
    if request.method == 'POST' and form.is_valid():
        try:
            result = save_order(actor=request.user, data={name: form.cleaned_data[name] for name in INPUT_FIELDS},
                order_id=pk, version=form.cleaned_data['version'], image=form.cleaned_data.get('image'),
                image2=form.cleaned_data.get('image2'))
        except (ValidationError, IntegrityError) as exc:
            form_error(form, exc if isinstance(exc, ValidationError) else ValidationError('This sales number already exists in the selected account.'))
            duplicate = Order.all_objects.for_user(request.user).filter(account=form.cleaned_data['account'], sales_no=form.cleaned_data['sales_no']).first()
        else:
            messages.success(request, 'Order saved.')
            for warning in order_warnings(result):
                messages.warning(request, warning)
            return redirect('order_create' if request.POST.get('add_another') else 'order_detail', **({} if request.POST.get('add_another') else {'pk': result.pk}))
    payment_status = None
    if order:
        from payments.services import balances
        payment_status = balances(order)['status']
    return render(request, 'orders/form.html', {'form': form, 'order': order, 'form_account': account, 'duplicate': duplicate,
        'payment_status': payment_status})


@login_required
@require_POST
def costing_preview(request):
    suggestion = None
    try:
        if request.POST.get('usd_sold') and request.POST.get('fx_rate'):
            suggestion = str(suggested_inr(Decimal(request.POST['usd_sold']), Decimal(request.POST['fx_rate'])))
        values = {name: Decimal(request.POST.get(name) or '0') for name in ('gross_wt', 'dia_ct', 'other_wt', 'purity', 'gold_rate', 'lab_rate', 'diamond_value', 'inr_sold', 'ship_charges', 'platform_fees_inr')}
        values['purity'] /= Decimal('100')
        if any(len(str(value)) > 32 for value in values.values()):
            raise ValueError('Check the entered numbers.')
        result = calculate_costing(**values)
    except (ValueError, TypeError, DecimalException) as exc:
        return JsonResponse({'error': 'Check the number of digits and decimal places.' if isinstance(exc, DecimalException) else str(exc), 'suggested_inr': suggestion}, status=400)
    return JsonResponse({**{name: str(value) for name, value in result.items()}, 'suggested_inr': suggestion})


@login_required
def order_photo(request, pk, thumb=False, second=False):
    order = get_object_or_404(Order.objects.for_user(request.user), pk=pk)
    file = (order.thumbnail2 if thumb else order.image2) if second else (order.thumbnail if thumb else order.image)
    data = (order.thumbnail2_data if thumb else order.image2_data) if second else (order.thumbnail_data if thumb else order.image_data)
    if not file:
        if data:
            response = HttpResponse(bytes(data), content_type='image/jpeg')
            response['Cache-Control'] = 'private, no-store'
            return response
        raise Http404('Photo not found.')
    try:
        response = FileResponse(file.open('rb'), content_type='image/jpeg')
    except FileNotFoundError as exc:
        if not data:
            raise Http404('Photo not found.') from exc
        response = HttpResponse(bytes(data), content_type='image/jpeg')
    response['Cache-Control'] = 'private, no-store'
    return response


@login_required
def deleted_orders(request):
    require(request.user, 'delete_order')
    return render(request, 'orders/deleted.html', {'rows': Order.all_objects.for_user(request.user).filter(is_deleted=True).select_related('account')})


@login_required
def order_delete(request, pk, restore=False):
    require(request.user, 'delete_order')
    order = get_object_or_404(Order.all_objects.for_user(request.user), pk=pk)
    if request.method == 'POST':
        try:
            set_deleted(actor=request.user, order_id=pk, version=int(request.POST.get('version', '0')), deleted=not restore,
                reason=request.POST.get('reason', ''), confirmation=request.POST.get('confirmation', ''))
        except (ValidationError, ValueError) as exc:
            messages.error(request, exc.messages[0] if isinstance(exc, ValidationError) else 'Reload and try again.')
        else:
            messages.success(request, 'Order restored.' if restore else 'Order deleted. Its history is retained.')
            return redirect('order_list')
    return render(request, 'orders/delete.html', {'order': order, 'restore': restore})


@login_required
def account_defaults(request, pk):
    require(request.user, 'create_order')
    from core.models import default_gold_rate
    account = get_object_or_404(EbayAccount.objects.for_user(request.user), pk=pk, active=True)
    return JsonResponse({'gold_rate': str(account.default_gold_rate if account.default_gold_rate is not None else default_gold_rate())})
