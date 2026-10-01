import uuid
from django.conf import settings
from django.db import models
from core.model_utils import RetainedModel, money


class ImportBatch(RetainedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    account = models.ForeignKey('accounts.EbayAccount', on_delete=models.PROTECT)
    filename = models.CharField(max_length=255)
    source = models.BinaryField(editable=False)
    preview_cache = models.JSONField(default=dict, blank=True)
    gold_rate = money()
    created_at = models.DateTimeField(auto_now_add=True)
    committed_at = models.DateTimeField(null=True, blank=True)
    created_count = models.PositiveIntegerField(default=0)
