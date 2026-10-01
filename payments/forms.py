from decimal import Decimal
from django import forms
from django.utils import timezone
from accounts.access import can
from payments.models import Payment


class PaymentForm(forms.Form):
    payment_date = forms.DateField(initial=timezone.localdate, widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'))
    amount = forms.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0.01'))
    method = forms.ChoiceField(choices=Payment._meta.get_field('method').choices)
    reference_no = forms.CharField(required=False, max_length=255)
    remarks = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 3}))
    Gold = forms.DecimalField(max_digits=14, decimal_places=2, min_value=0, initial=0)
    Diamond = forms.DecimalField(max_digits=14, decimal_places=2, min_value=0, initial=0)
    Labour = forms.DecimalField(max_digits=14, decimal_places=2, min_value=0, initial=0)
    approve_overpayment = forms.BooleanField(required=False, label='Approve overpayment')
    overpayment_reason = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 2}))

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        if not can(actor, 'approve_overpayment'):
            self.fields.pop('approve_overpayment')
            self.fields.pop('overpayment_reason')
