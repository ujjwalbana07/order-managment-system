from accounts.access import AccountScopeMixin
from core.model_utils import RetainedQuerySet
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from core.model_utils import RetainedModel


class InvoiceQuerySet(AccountScopeMixin, RetainedQuerySet):
    def update(self, **kwargs):
        raise ValidationError('These records cannot be edited directly. Use the correction workflow.')

    def bulk_update(self, *args, **kwargs):
        raise ValidationError('These records cannot be edited directly. Use the correction workflow.')

    account_path = 'order__account_id'


class Invoice(RetainedModel):
    objects = InvoiceQuerySet.as_manager()
    invoice_no = models.CharField(max_length=30, unique=True, editable=False, validators=[RegexValidator(r'^INV-[0-9]{4}-[0-9]{5,}$', 'Use an invoice number in INV-YYYY-00001 format.')])
    order = models.ForeignKey('orders.Order', on_delete=models.PROTECT, related_name='invoices')
    issued_at = models.DateTimeField(auto_now_add=True)
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    snapshot = models.JSONField()
    status = models.CharField(max_length=12, choices=[('Issued', 'Issued'), ('Superseded', 'Superseded')], default='Issued')

    def clean(self):
        if not self._state.adding:
            old = type(self).objects.get(pk=self.pk)
            if any(getattr(self, name) != getattr(old, name) for name in
                   ('invoice_no', 'order_id', 'issued_at', 'issued_by_id', 'snapshot')):
                raise ValidationError('Issued invoices cannot be changed. Issue a revised invoice.')


class DocumentSequence(models.Model):
    key = models.CharField(max_length=30, primary_key=True)
    value = models.PositiveBigIntegerField(default=0)
