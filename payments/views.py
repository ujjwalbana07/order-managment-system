from decimal import Decimal, DecimalException
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from accounts.access import require
from accounts.views import form_error
from core.costing import split_automatically, COMPONENT_FIELDS
from orders.models import Order
from payments.models import Payment
from payments.forms import PaymentForm
from payments.services import post_payment, void_payment, balances


@login_required
def record_payment(request, pk):
    require(request.user, 'record_payment')
    order = get_object_or_404(Order.objects.for_user(request.user), pk=pk)
    form = PaymentForm(request.POST if request.method == 'POST' else None, actor=request.user)
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data.copy()
        allocations = {name: data.pop(name) for name in COMPONENT_FIELDS}
        try:
            post_payment(actor=request.user, order_id=pk, allocations=allocations, **data)
        except ValidationError as exc:
            form_error(form, exc)
        else:
            messages.success(request, 'Payment recorded.')
            return redirect('order_detail', pk=pk)
    balance = balances(order)
    return render(request, 'payments/form.html', {'form': form, 'order': order, 'balance': balance,
        'identity_fields': [form[name] for name in ('payment_date', 'amount', 'method', 'reference_no', 'remarks')],
        'allocation_rows': [{'name': name, 'field': form[name], 'outstanding': balance['outstanding'][name]} for name in COMPONENT_FIELDS]})


@login_required
@require_POST
def split_payment(request, pk):
    require(request.user, 'record_payment')
    order = get_object_or_404(Order.objects.for_user(request.user), pk=pk)
    try:
        value = Decimal(request.POST.get('amount', '0'))
        if len(str(value)) > 24:
            raise ValueError('Check the payment amount.')
        result = split_automatically(value, balances(order)['outstanding'])
    except (DecimalException, ValueError):
        return JsonResponse({'error': 'Enter a valid payment amount.'}, status=400)
    return JsonResponse({key: str(value) for key, value in result.items()})


@login_required
def void(request, pk):
    require(request.user, 'void_payment')
    payment = get_object_or_404(Payment.objects.for_user(request.user), pk=pk, order__is_deleted=False)
    if request.method == 'POST':
        try:
            void_payment(actor=request.user, payment_id=pk, reason=request.POST.get('reason', ''))
        except ValidationError as exc:
            messages.error(request, exc.messages[0])
        else:
            messages.success(request, 'Payment voided.')
            return redirect('order_detail', pk=payment.order_id)
    return render(request, 'payments/void.html', {'payment': payment})
