from decimal import Decimal
from django import forms
from django.utils import timezone
from django.db.models import Q
from accounts.models import EbayAccount
from accounts.access import can
from core.models import default_gold_rate, default_fx_rate
from orders.models import Order
from orders.services import INPUT_FIELDS


class OrderForm(forms.Form):
    def __init__(self, *args, actor, instance=None, account=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance = instance
        if not instance and self.is_bound:
            submitted = self.data.get('account', '')
            if str(submitted).isdigit():
                account = EbayAccount.objects.for_user(actor).filter(pk=submitted, active=True).first()
        for name in INPUT_FIELDS:
            if name != 'purity':
                self.fields[name] = Order._meta.get_field(name).formfield()
        self.fields['account'].queryset = EbayAccount.objects.for_user(actor).filter(Q(active=True) | Q(pk=instance.account_id if instance else None))
        self.fields['purity'] = forms.DecimalField(label='Purity (%)', min_value=Decimal('0.01'), max_value=Decimal('100'), decimal_places=2, max_digits=5,
            help_text='Enter a percentage, for example 59.5.')
        self.fields['purity_confirm'] = forms.BooleanField(required=False, label='I confirm purity is below 1%')
        self.fields['version'] = forms.IntegerField(widget=forms.HiddenInput, initial=instance.version if instance else 1)
        self.fields['image'] = forms.FileField(required=False, label='Photo', help_text='JPEG, PNG or WebP. Maximum 5 MB.')
        self.initial.update({'account': account, 'order_date': timezone.localdate(), 'quantity': 1,
            'fx_rate': default_fx_rate(), 'gold_rate': default_gold_rate(), 'lab_rate': Decimal('0'),
            'ship_charges': Decimal('0'), 'platform_fees_inr': Decimal('0'), 'other_wt': Decimal('0'), 'dia_ct': Decimal('0'), 'fulfilment_status': 'New'})
        if account and account.default_gold_rate is not None:
            self.initial['gold_rate'] = account.default_gold_rate
        if instance:
            self.initial.update({name: getattr(instance, name) for name in INPUT_FIELDS})
            self.initial['purity'] = instance.purity * Decimal('100')
        for name in ('order_date', 'ship_by_date'):
            self.fields[name].widget = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')
        for name in ('gross_wt', 'dia_ct', 'other_wt'):
            self.fields[name].decimal_places = 3
            self.fields[name].widget.attrs['step'] = '0.001'
        self.fields['purity'].widget.attrs['step'] = '0.01'
        if not can(actor, 'edit_rates'):
            for name in ('gold_rate', 'lab_rate'):
                self.fields[name].disabled = True
        if instance and instance.payments.exists() and not can(actor, 'edit_sensitive'):
            for name in ('diamond_value', 'purity', 'gross_wt', 'dia_ct', 'other_wt'):
                self.fields[name].disabled = True

    def clean(self):
        data = super().clean()
        raw = str(self.data.get('purity', '')).strip()
        try:
            raw_value = Decimal(raw)
        except Exception:
            return data
        if raw_value.is_finite() and 0 < raw_value < 1 and not data.get('purity_confirm'):
            self.add_error('purity', f'Did you mean {raw_value * 100}%? Otherwise confirm the low purity below.')
        if 'purity' in data:
            data['purity'] /= Decimal('100')
        return data

    @property
    def groups(self):
        names = [ ('Identity', INPUT_FIELDS[:12]), ('Sale', INPUT_FIELDS[12:17]),
                  ('Metal and weight', ('purity', 'gross_wt', 'dia_ct', 'other_wt', 'purity_confirm')),
                  ('Rates', ('gold_rate', 'lab_rate', 'diamond_value')) ]
        return [(title, [self[name] for name in fields]) for title, fields in names]
