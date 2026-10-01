"""Transactional identity management. Never put credentials in audit snapshots."""
import uuid
from datetime import timedelta
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from accounts.access import require
from accounts.models import User, EbayAccount
from audit.models import AuditLog
from core.services import save_record


def user_snapshot(user):
    return {'email': user.email, 'first_name': user.first_name, 'last_name': user.last_name,
            'role': user.role, 'is_active': user.is_active,
            'accounts': list(user.ebay_accounts.order_by('pk').values_list('pk', flat=True))}


@transaction.atomic
def save_user(*, actor, data, user_id=None):
    require(actor, 'manage_users')
    # Serialise Owner membership changes so the final active Owner is retained.
    owners = list(User.objects.select_for_update().filter(role=User.Role.OWNER, is_active=True).order_by('pk'))
    user = User.objects.select_for_update().get(pk=user_id) if user_id else User(username=uuid.uuid4().hex)
    before = user_snapshot(user) if user_id else {}
    allowed = {'email', 'first_name', 'last_name', 'role', 'is_active', 'ebay_accounts', 'password'}
    if set(data) - allowed:
        raise ValidationError('Some submitted fields cannot be changed here.')
    for field in ('email', 'first_name', 'last_name', 'role', 'is_active'):
        if field in data:
            setattr(user, field, data[field])
    assigned = list(data.get('ebay_accounts', user.ebay_accounts.all() if user_id else []))
    if len(owners) == 1 and owners[0].pk == user.pk and (user.role != User.Role.OWNER or not user.is_active):
        raise ValidationError('Keep at least one active Owner. Assign another Owner first.')
    if not user_id:
        password = data.get('password', '')
        validate_password(password, user)
        user.set_password(password)
    elif 'password' in data:
        raise ValidationError('Use Reset password to change a password.')
    user.email = user.email.strip().lower()
    user.full_clean()
    user.save()
    user.ebay_accounts.set(assigned)
    AuditLog.objects.create(actor=actor, action='permission_change' if user_id else 'create',
        object_type='accounts.User', object_id=str(user.pk), before=before, after=user_snapshot(user))
    return user


@transaction.atomic
def reset_password(*, actor, user_id, password):
    require(actor, 'manage_users')
    user = User.objects.select_for_update().get(pk=user_id)
    validate_password(password, user)
    user.set_password(password)
    user.failed_login_attempts = 0
    user.locked_until = None
    user.save(update_fields=['password', 'failed_login_attempts', 'locked_until'])
    AuditLog.objects.create(actor=actor, action='password_reset', object_type='accounts.User', object_id=str(user.pk))
    return user


@transaction.atomic
def save_account(*, actor, data, account_id=None):
    require(actor, 'manage_accounts')
    account = EbayAccount.objects.select_for_update().get(pk=account_id) if account_id else EbayAccount()
    allowed = {'code', 'display_name', 'ebay_username', 'active', 'billing_name', 'billing_address',
               'phone', 'email', 'tax_id', 'default_gold_rate', 'notes'}
    if set(data) - allowed:
        raise ValidationError('Some submitted fields cannot be changed here.')
    for name, value in data.items():
        setattr(account, name, value.strip() if isinstance(value, str) else value)
    return save_record(account, actor=actor)


@transaction.atomic
def attempt_login(email, password):
    user = User.objects.select_for_update().filter(email__iexact=email.strip()).first()
    if user is None:
        # Match the expensive password-hash work for an unknown email.
        User().set_password(password)
        return None
    now = timezone.now()
    if not user.is_active or (user.locked_until and user.locked_until > now):
        User().set_password(password)
        return None
    if user.locked_until:
        user.failed_login_attempts = 0
        user.locked_until = None
    valid = user.check_password(password)
    if valid:
        user.failed_login_attempts = 0
        user.locked_until = None
    else:
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= 5:
            user.locked_until = now + timedelta(minutes=15)
    user.save(update_fields=['failed_login_attempts', 'locked_until'])
    AuditLog.objects.create(actor=user, action='login_success' if valid else 'login_failed',
        object_type='accounts.User', object_id=str(user.pk),
        after={'failed_attempts': user.failed_login_attempts, 'locked': user.locked_until is not None})
    return user if valid else None
