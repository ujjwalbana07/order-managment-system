from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from accounts.access import require
from audit.models import AuditLog
from core.costing import COMPONENT_FIELDS, payment_balances
from core.services import snapshot
from core.transactions import retry_locked
from orders.models import Order
from payments.models import Payment, PaymentAllocation


def balances(order, through=None):
    payments = list(order.payments.all())
    if through:
        key = (through.payment_date, through.created_at, through.pk)
        payments = [p for p in payments if (p.payment_date, p.created_at, p.pk) <= key]
    allocations = [(allocation.component, allocation.amount) for payment in payments if payment.status == 'Posted'
                   for allocation in payment.allocations.all()]
    return payment_balances({name: getattr(order, field) for name, field in COMPONENT_FIELDS.items()}, allocations)


@retry_locked
@transaction.atomic
def post_payment(*, actor, order_id, payment_date, amount, method, allocations, reference_no='', remarks='', approve_overpayment=False, overpayment_reason=''):
    require(actor, 'record_payment')
    order = get_object_or_404(Order.objects.for_user(actor).select_for_update(), pk=order_id)
    if order.fulfilment_status == 'Cancelled':
        raise ValidationError('This order is cancelled. Restore its fulfilment status before recording a payment.')
    if payment_date > timezone.localdate():
        raise ValidationError('Payment date cannot be in the future.')
    if not isinstance(amount, Decimal):
        raise ValidationError('Enter a valid payment amount.')
    if set(allocations) - set(COMPONENT_FIELDS):
        raise ValidationError('Use Gold, Diamond and Labour allocations only.')
    if any(not isinstance(value, Decimal) or not value.is_finite() or value < 0 for value in allocations.values()):
        raise ValidationError('Enter finite nonnegative allocation amounts.')
    rows = [PaymentAllocation(component=name, amount=value) for name, value in allocations.items() if value]
    payment = Payment(order=order, created_by=actor, payment_date=payment_date, amount=amount, method=method,
        reference_no=reference_no.strip(), remarks=remarks.strip())
    payment.full_clean()
    payment.validate_allocations(rows)
    current = balances(order)
    excessive = [row.component for row in rows if row.amount > current['outstanding'][row.component]]
    if approve_overpayment:
        require(actor, 'approve_overpayment')
        if not overpayment_reason.strip():
            raise ValidationError('Enter a reason for the overpayment approval.')
        payment.overpayment_approved_by = actor
        payment.overpayment_reason = overpayment_reason.strip()
    if excessive and not approve_overpayment:
        raise ValidationError(f'Payment exceeds {excessive[0]} outstanding. Ask an Owner to approve an overpayment with a reason.')
    payment.save()
    for row in rows:
        row.payment = payment
        row.save()
    payment.validate_allocations()
    AuditLog.objects.create(actor=actor, action='create', object_type='payments.Payment', object_id=str(payment.pk),
        account=order.account, after={**snapshot(payment), 'allocations': {row.component: str(row.amount) for row in rows}})
    return payment


@retry_locked
@transaction.atomic
def void_payment(*, actor, payment_id, reason):
    require(actor, 'void_payment')
    target = get_object_or_404(Payment.objects.for_user(actor), pk=payment_id, order__is_deleted=False)
    order = Order.objects.select_for_update().get(pk=target.order_id)
    payment = Payment.objects.select_for_update().get(pk=target.pk)
    if not reason.strip():
        raise ValidationError('Enter a reason to void this payment.')
    if payment.status == 'Voided':
        raise ValidationError('This payment has already been voided.')
    before = snapshot(payment)
    payment.status = 'Voided'
    payment.voided_by = actor
    payment.voided_at = timezone.now()
    payment.void_reason = reason.strip()
    payment.save()
    AuditLog.objects.create(actor=actor, action='void', object_type='payments.Payment', object_id=str(payment.pk),
        account=order.account, before=before, after=snapshot(payment), note=reason.strip())
    return payment
