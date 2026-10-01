from decimal import Decimal
from django.db import models
from core.model_utils import RetainedModel, money, nonnegative_constraints


class Settings(RetainedModel):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    company_name = models.CharField(max_length=255)
    address = models.TextField()
    phone = models.CharField(max_length=50)
    email = models.EmailField()
    tax_id = models.CharField(max_length=100, blank=True)
    logo = models.ImageField(upload_to="company/", blank=True)
    default_gold_rate = money(default=Decimal("15000.00"))
    default_fx_rate = models.DecimalField(max_digits=10, decimal_places=4, default=Decimal("91.0000"))
    invoice_footer_text = models.TextField(blank=True)
    payment_direction = models.CharField(max_length=8, choices=[("paid_out", "Paid out"), ("received", "Received")], default="paid_out")
    gst_enabled = models.BooleanField(default=False)
    gst_rate_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0"))

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(id=1), name="settings_singleton"),
            models.CheckConstraint(condition=models.Q(gst_rate_percent__gte=0, gst_rate_percent__lte=100), name="settings_gst_range"),
            *nonnegative_constraints("settings", ["default_gold_rate", "default_fx_rate"])]


def default_gold_rate():
    value = Settings.objects.filter(pk=1).values_list("default_gold_rate", flat=True).first()
    return value if value is not None else Decimal("15000.00")


def default_fx_rate():
    value = Settings.objects.filter(pk=1).values_list("default_fx_rate", flat=True).first()
    return value if value is not None else Decimal("91.0000")
