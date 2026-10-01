"""Atomic, audited persistence with role and account checks.

Identity management lives in accounts.services. Payment posting and invoice
issuance get dedicated services in M3 and M4.
"""
import json
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.core.exceptions import ValidationError
from core.transactions import retry_locked
from audit.models import AuditLog


def snapshot(instance):
    return json.loads(json.dumps({field.attname: field.value_from_object(instance)
        for field in instance._meta.concrete_fields}, cls=DjangoJSONEncoder, default=str))


@retry_locked
@transaction.atomic
def save_record(instance, *, actor, note='', ip=None):
    if instance._meta.label not in {'accounts.EbayAccount', 'core.Settings', 'orders.Order'}:
        raise ValueError('Use the dedicated service for this record type.')
    from accounts.access import require
    if instance._meta.label == 'accounts.EbayAccount':
        require(actor, 'manage_accounts')
    elif instance._meta.label == 'core.Settings':
        require(actor, 'manage_settings')
    else:
        require(actor, 'create_order' if instance._state.adding else 'edit_order')
        from accounts.models import EbayAccount
        if not EbayAccount.objects.for_user(actor).filter(pk=instance.account_id).exists():
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied('You do not have access to this account.')
    adding = instance._state.adding
    old = None if adding else type(instance)._base_manager.select_for_update().get(pk=instance.pk)
    if instance._meta.label == 'orders.Order' and old is not None:
        from django.core.exceptions import PermissionDenied
        if not EbayAccount.objects.for_user(actor).filter(pk=old.account_id).exists():
            raise PermissionDenied('You do not have access to this account.')
        if old.is_deleted != instance.is_deleted:
            require(actor, 'delete_order')
        if any(getattr(old, field) != getattr(instance, field) for field in ('gold_rate', 'lab_rate')):
            require(actor, 'edit_rates')
        sensitive = ('diamond_value', 'purity', 'gross_wt', 'dia_ct', 'other_wt')
        if old.payments.exists() and any(getattr(old, field) != getattr(instance, field) for field in sensitive):
            require(actor, 'edit_sensitive')
    if instance._meta.label == 'orders.Order' and old is not None:
        if instance.version != old.version:
            raise ValidationError('Someone else just changed this order. Your changes were not saved. Reload to see theirs.')
        instance.version = old.version + 1
    if instance._meta.label == 'orders.Order' and old is not None:
        from payments.services import balances
        from core.costing import COMPONENT_FIELDS
        instance.full_clean()
        received = balances(old)['received']
        for component, field in COMPONENT_FIELDS.items():
            if getattr(instance, field) < received[component] and getattr(instance, field) < getattr(old, field):
                raise ValidationError(f'This change would make the bill lower than what is already paid for {component}. Ask an Owner to void a payment first.')
    before = snapshot(old) if old else {}
    instance.save()
    account_id = instance.pk if instance._meta.label == 'accounts.EbayAccount' else getattr(instance, 'account_id', None)
    action = 'create' if adding else 'update'
    if old is not None and hasattr(instance, 'is_deleted') and old.is_deleted != instance.is_deleted:
        action = 'delete' if instance.is_deleted else 'restore'
    AuditLog.objects.create(actor=actor, action=action,
        object_type=instance._meta.label, object_id=str(instance.pk), account_id=account_id,
        before=before, after=snapshot(instance), note=note, ip=ip)
    return instance
