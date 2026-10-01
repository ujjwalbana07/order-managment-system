from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from core.model_utils import RetainedModel, RetainedQuerySet


class AuditQuerySet(RetainedQuerySet):
    def for_user(self, user):
        from accounts.access import can
        return self.all() if can(user, 'view_audit') else self.none()

    def update(self, **kwargs):
        raise ValidationError('Audit records cannot be changed.')

    def bulk_update(self, *args, **kwargs):
        raise ValidationError('Audit records cannot be changed.')


class AuditLog(RetainedModel):
    timestamp = models.DateTimeField(auto_now_add=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    action = models.CharField(max_length=100)
    object_type = models.CharField(max_length=100)
    object_id = models.CharField(max_length=100)
    account = models.ForeignKey('accounts.EbayAccount', on_delete=models.PROTECT, null=True, blank=True)
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    note = models.TextField(blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    objects = AuditQuerySet.as_manager()

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError('Audit records cannot be changed.')
        if self.ip is None:
            from core.request_context import request_ip
            self.ip = request_ip.get()
        return super().save(*args, **kwargs)
