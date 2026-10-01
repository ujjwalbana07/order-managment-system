"""Role checks and account-scoped querysets shared by every application."""
from django.core.exceptions import PermissionDenied
from django.db import models

ROLE_ACTIONS = {
    'Owner': {'manage_accounts', 'manage_users', 'manage_settings', 'create_order', 'edit_order',
              'edit_rates', 'edit_sensitive', 'delete_order', 'record_payment', 'void_payment',
              'approve_overpayment', 'issue_documents', 'view_payments', 'view_reports',
              'export', 'import', 'view_audit', 'backup'},
    'Accounts': {'create_order', 'edit_order', 'edit_rates', 'edit_sensitive', 'record_payment',
                 'issue_documents', 'view_payments', 'view_reports', 'export', 'import'},
    'Staff': {'create_order', 'edit_order', 'view_payments', 'view_reports'},
}


def can(user, action):
    return bool(user.is_authenticated and user.is_active and action in ROLE_ACTIONS.get(user.role, set()))


def require(user, action):
    if not can(user, action):
        raise PermissionDenied('You do not have permission to do this. Ask an Owner for help.')


class AccountScopeMixin:
    account_path = 'account_id'

    def for_user(self, user):
        if not user.is_authenticated or not user.is_active:
            return self.none()
        if user.role == 'Owner':
            return self.all()
        if user.role not in ROLE_ACTIONS:
            return self.none()
        return self.filter(**{f'{self.account_path}__in': user.ebay_accounts.values('pk')})
