from decimal import Decimal
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models


def money(**kwargs):
    return models.DecimalField(max_digits=14, decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))], **kwargs)


def nonnegative_constraints(prefix, fields):
    return [models.CheckConstraint(condition=models.Q(**{f"{field}__gte": 0}),
            name=f"{prefix}_{field}_nonnegative") for field in fields]


class RetainedQuerySet(models.QuerySet):
    def delete(self):
        raise ValidationError("Historical records cannot be deleted.")


class RetainedModel(models.Model):
    objects = RetainedQuerySet.as_manager()

    class Meta:
        abstract = True

    def delete(self, *args, **kwargs):
        raise ValidationError("Historical records cannot be deleted.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
