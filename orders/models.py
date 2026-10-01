from decimal import Decimal
from accounts.access import AccountScopeMixin
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from core.costing import calculate_costing
from core.models import default_fx_rate, default_gold_rate
from core.model_utils import RetainedModel, RetainedQuerySet, money, nonnegative_constraints


class OrderQuerySet(AccountScopeMixin, RetainedQuerySet):
    def for_user(self, user):
        queryset = super().for_user(user)
        return queryset if getattr(user, 'role', None) == 'Owner' else queryset.filter(is_deleted=False)


class OrderManager(models.Manager.from_queryset(OrderQuerySet)):
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class Order(RetainedModel):
    # The database sequence is global. Retained orders keep their serial forever.
    serial_no = models.BigAutoField(primary_key=True, editable=False)
    account = models.ForeignKey('accounts.EbayAccount', on_delete=models.PROTECT, related_name='orders')
    sales_no = models.IntegerField(validators=[MinValueValidator(0)])
    challan_no = models.CharField(max_length=100, blank=True)
    mfg_order_no = models.CharField(max_length=100, blank=True)
    order_date = models.DateField()
    ship_by_date = models.DateField(null=True, blank=True)
    buyer_username = models.CharField(max_length=255)
    item_title = models.CharField(max_length=255)
    quantity = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    image = models.ImageField(upload_to='orders/', blank=True)
    thumbnail = models.ImageField(upload_to='orders/thumbnails/', blank=True, editable=False)
    image2 = models.ImageField(upload_to='orders/', blank=True)
    thumbnail2 = models.ImageField(upload_to='orders/thumbnails/', blank=True, editable=False)
    image_data = models.BinaryField(null=True, blank=True, editable=False)
    thumbnail_data = models.BinaryField(null=True, blank=True, editable=False)
    image2_data = models.BinaryField(null=True, blank=True, editable=False)
    thumbnail2_data = models.BinaryField(null=True, blank=True, editable=False)
    igi_cert_no = models.CharField(max_length=100, blank=True)
    tracking_no = models.CharField(max_length=255, blank=True)
    fulfilment_status = models.CharField(max_length=20, blank=True, default='', choices=[('', '---------'), ('Delivered', 'Delivered'), ('Returned', 'Returned'), ('Cancelled', 'Cancelled')])
    usd_sold = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal('0'))])
    fx_rate = models.DecimalField(max_digits=10, decimal_places=4, default=default_fx_rate, validators=[MinValueValidator(Decimal('0'))])
    inr_sold = money()
    ship_charges = money(default=Decimal('0'))
    platform_fees_inr = money(default=Decimal('0'))
    purity = models.DecimalField(max_digits=6, decimal_places=4, validators=[MinValueValidator(Decimal('0.0001')), MaxValueValidator(Decimal('1'))])
    gross_wt = models.DecimalField(max_digits=12, decimal_places=4, validators=[MinValueValidator(Decimal('0.0001'))])
    dia_ct = models.DecimalField(max_digits=12, decimal_places=4, validators=[MinValueValidator(Decimal('0'))])
    other_wt = models.DecimalField(max_digits=12, decimal_places=4, validators=[MinValueValidator(Decimal('0'))])
    gold_rate = money(default=default_gold_rate)
    lab_rate = money()
    diamond_value = money()
    net_wt = models.DecimalField(max_digits=12, decimal_places=4, editable=False)
    pure_995 = models.DecimalField(max_digits=15, decimal_places=6, editable=False)
    gold_amount = money(editable=False)
    labour_amount = money(editable=False)
    total_bill = money(editable=False)
    # SPEC 5 explicitly permits a loss and asks for a warning in M2.
    net_earnings = models.DecimalField(max_digits=14, decimal_places=2, editable=False)
    version = models.PositiveIntegerField(default=1, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='orders_created')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='orders_updated')
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)
    deleted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='orders_deleted', null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    delete_reason = models.TextField(blank=True)
    objects = OrderManager()
    all_objects = OrderQuerySet.as_manager()

    class Meta:
        base_manager_name = 'all_objects'
        constraints = [
            models.CheckConstraint(condition=models.Q(sales_no__gte=0), name='order_sales_no_nonnegative'),
            models.UniqueConstraint(fields=['account', 'sales_no'], name='order_account_sales_unique'),
            models.CheckConstraint(condition=models.Q(net_wt__gt=0), name='order_net_wt_positive'),
            models.CheckConstraint(condition=models.Q(gross_wt__gt=0), name='order_gross_wt_positive'),
            models.CheckConstraint(condition=models.Q(purity__gte=Decimal('0.0001'), purity__lte=1), name='order_purity_range'),
            models.CheckConstraint(condition=models.Q(quantity__gte=1), name='order_quantity_positive'),
            models.CheckConstraint(condition=models.Q(version__gte=1), name='order_version_positive'),
            models.CheckConstraint(condition=models.Q(ship_by_date__isnull=True) | models.Q(ship_by_date__gte=models.F('order_date')), name='order_ship_date_valid'),
            *nonnegative_constraints('order', ['usd_sold', 'fx_rate', 'inr_sold', 'ship_charges', 'platform_fees_inr', 'gold_rate', 'lab_rate', 'diamond_value', 'gold_amount', 'labour_amount', 'total_bill', 'dia_ct', 'other_wt']),
        ]

    def recalculate(self):
        names = ('gross_wt', 'dia_ct', 'other_wt', 'purity', 'gold_rate', 'lab_rate', 'diamond_value', 'inr_sold', 'ship_charges', 'platform_fees_inr')
        try:
            result = calculate_costing(**{name: getattr(self, name) for name in names})
        except (ValueError, TypeError) as exc:
            raise ValidationError(str(exc)) from exc
        for name, value in result.items():
            setattr(self, 'pure_995' if name == 'pure_995_6dp' else name, value)

    def full_clean(self, *args, **kwargs):
        for field in self._meta.fields:
            value = getattr(self, field.name)
            if isinstance(value, str):
                setattr(self, field.name, value.strip())
        self.buyer_username = self.buyer_username.lower()
        self.tracking_no = self.tracking_no.strip()
        # Validate original inputs before the costing function rounds diamond_value.
        derived = {'net_wt', 'pure_995', 'gold_amount', 'labour_amount', 'total_bill', 'net_earnings'}
        self.clean_fields(exclude=derived)
        for name in ('gross_wt', 'dia_ct', 'other_wt'):
            if getattr(self, name).normalize().as_tuple().exponent < -3:
                raise ValidationError({name: 'Enter weights with at most three decimal places.'})
        self.recalculate()
        return super().full_clean(*args, **kwargs)

    def save(self, *args, **kwargs):
        if kwargs.get('update_fields') is not None:
            kwargs['update_fields'] = set(kwargs['update_fields']) | {'net_wt', 'pure_995', 'gold_amount', 'labour_amount', 'diamond_value', 'total_bill', 'net_earnings', 'updated_at'}
        return super().save(*args, **kwargs)
