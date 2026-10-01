from accounts.access import AccountScopeMixin
from core.model_utils import RetainedQuerySet
import uuid
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from core.model_utils import RetainedModel, money


def receipt_number():
    return f'RCT-{uuid.uuid4().hex.upper()}'


class PaymentQuerySet(AccountScopeMixin, RetainedQuerySet):
    def update(self, **kwargs):
        raise ValidationError('These records cannot be edited directly. Use the correction workflow.')

    def bulk_update(self, *args, **kwargs):
        raise ValidationError('These records cannot be edited directly. Use the correction workflow.')

    account_path = 'order__account_id'


class Payment(RetainedModel):
    objects = PaymentQuerySet.as_manager()
    order = models.ForeignKey('orders.Order', on_delete=models.PROTECT, related_name='payments')
    payment_date = models.DateField()
    amount = money()
    method = models.CharField(max_length=20, choices=[(x, x) for x in ('Cash', 'Bank Transfer', 'UPI', 'Cheque', 'Other')])
    reference_no = models.CharField(max_length=255, blank=True)
    remarks = models.TextField(blank=True)
    receipt_no = models.CharField(max_length=50, unique=True, default=receipt_number, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='payments_created')
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=[('Posted', 'Posted'), ('Voided', 'Voided')], default='Posted')
    voided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='payments_voided', null=True, blank=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.TextField(blank=True)
    overpayment_approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='overpayments_approved', null=True, blank=True)
    overpayment_reason = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name='payment_amount_positive'),
            models.CheckConstraint(condition=~models.Q(method__in=['Bank Transfer', 'UPI', 'Cheque']) | ~models.Q(reference_no=''), name='payment_reference_required'),
            models.CheckConstraint(condition=~models.Q(status='Voided') | (models.Q(voided_by__isnull=False, voided_at__isnull=False) & ~models.Q(void_reason='')), name='payment_void_details'),
            models.CheckConstraint(condition=models.Q(overpayment_approved_by__isnull=True) | ~models.Q(overpayment_reason=''), name='payment_approval_reason'),
        ]

    def validate_allocations(self, allocations=None):
        """Validate the complete collection, inside the future posting transaction.

        A row CHECK cannot enforce a sum across child rows. M3 will call this
        after assembling allocations and before committing a payment.
        """
        if allocations is None:
            allocations = self.allocations.all()
        allocations = list(allocations)
        components = [allocation.component for allocation in allocations]
        if len(components) != len(set(components)):
            raise ValidationError('Use one allocation per component.')
        if any(allocation.amount <= 0 for allocation in allocations):
            raise ValidationError('Allocation amounts must be greater than zero.')
        if sum((allocation.amount for allocation in allocations), Decimal('0')) != self.amount:
            raise ValidationError('Allocations must equal the payment amount exactly.')

    def clean(self):
        self.reference_no = self.reference_no.strip()
        if not self._state.adding:
            old = type(self).objects.get(pk=self.pk)
            mutable = {'status', 'voided_by', 'voided_at', 'void_reason'}
            if old.status == 'Voided' or self.status != 'Voided' or any(
                getattr(old, f.attname) != getattr(self, f.attname)
                for f in self._meta.concrete_fields if f.name not in mutable
            ):
                raise ValidationError('Payments cannot be edited. Void the payment and record a new one.')


class AllocationQuerySet(AccountScopeMixin, RetainedQuerySet):
    def update(self, **kwargs):
        raise ValidationError('These records cannot be edited directly. Use the correction workflow.')

    def bulk_update(self, *args, **kwargs):
        raise ValidationError('These records cannot be edited directly. Use the correction workflow.')

    account_path = 'payment__order__account_id'


class PaymentAllocation(RetainedModel):
    objects = AllocationQuerySet.as_manager()
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name='allocations')
    component = models.CharField(max_length=10, choices=[(x, x) for x in ('Gold', 'Diamond', 'Labour')])
    amount = money()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['payment', 'component'], name='allocation_component_unique'),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name='allocation_amount_positive')]

    def clean(self):
        if not self._state.adding:
            raise ValidationError('Payment allocations cannot be edited. Void the payment instead.')
