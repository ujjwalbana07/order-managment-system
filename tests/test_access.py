from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
import pytest
from django.contrib.auth import authenticate
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from accounts.access import can, require
from accounts.models import EbayAccount, User
from accounts.services import save_account, save_user, reset_password
from audit.models import AuditLog
from core.services import save_record
from orders.models import Order
from payments.models import Payment, PaymentAllocation
from documents.models import Invoice

pytestmark = pytest.mark.django_db
PASSWORD = 'River!Cloud-4902-Tree'


@pytest.fixture(autouse=True)
def fast_passwords(settings):
    settings.PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']


@pytest.fixture
def access_data(actor, account):
    def new(code):
        return save_account(actor=actor, data=dict(code=code, display_name=f'Account {code}',
            ebay_username=f'account-{code}', billing_name=code, billing_address='Address', phone='123', email=f'{code}@example.com'))
    b, c = new('B'), new('C')
    users = {}
    for role in ('Accounts', 'Staff'):
        users[role] = save_user(actor=actor, data={'email': f'{role.lower()}@example.com', 'role': role,
            'is_active': True, 'password': PASSWORD, 'ebay_accounts': [account, b]})
    return account, b, c, users


@pytest.mark.parametrize('role,allowed', [
    ('Owner', {'manage_accounts', 'manage_users', 'manage_settings', 'create_order', 'edit_order', 'edit_rates',
               'edit_sensitive', 'delete_order', 'record_payment', 'void_payment', 'approve_overpayment',
               'issue_documents', 'view_payments', 'view_reports', 'export', 'import', 'view_audit', 'backup'}),
    ('Accounts', {'create_order', 'edit_order', 'edit_rates', 'edit_sensitive', 'record_payment',
                  'issue_documents', 'view_payments', 'view_reports', 'export', 'import'}),
    ('Staff', {'create_order', 'edit_order', 'view_payments', 'view_reports', 'import'}),
])
def test_role_matrix(role, allowed):
    user = User(role=role, is_active=True)
    actions = {'manage_accounts', 'manage_users', 'manage_settings', 'create_order', 'edit_order', 'edit_rates',
               'edit_sensitive', 'delete_order', 'record_payment', 'void_payment', 'approve_overpayment',
               'issue_documents', 'view_payments', 'view_reports', 'export', 'import', 'view_audit', 'backup', 'unknown'}
    for action in actions:
        assert can(user, action) == (action in allowed)
        if action not in allowed:
            with pytest.raises(PermissionDenied):
                require(user, action)
    user.is_active = False
    assert not any(can(user, action) for action in actions)
    assert not can(AnonymousUser(), 'view_reports')


@pytest.mark.parametrize('role', ['Staff', 'Accounts'])
def test_queryset_isolation(access_data, make_order, actor, role):
    a, b, c, users = access_data
    user = users[role]
    orders = [save_record(make_order(account=account), actor=actor) for account in (a, b, c)]
    assert set(Order.objects.for_user(user)) == set(orders)
    # Export services must consume this same scoped queryset.
    assert list(Order.objects.for_user(user).order_by('pk').values_list('account_id', flat=True)) == [a.pk, b.pk, c.pk]
    assert set(EbayAccount.objects.for_user(user)) == {a, b, c}
    assert set(Order.objects.for_user(actor)) == set(orders)
    assert not Order.objects.for_user(AnonymousUser()).exists()
    user.is_active = False
    assert not Order.objects.for_user(user).exists()


def test_related_record_scopes(access_data, make_order, actor):
    a, b, c, users = access_data
    for account in (a, c):
        order = save_record(make_order(account=account), actor=actor)
        # Low-level setup only: posting and invoice issuance remain later milestones.
        payment = Payment.objects.create(order=order, payment_date=timezone.localdate(), amount=Decimal('1'), method='Cash', created_by=actor)
        PaymentAllocation.objects.create(payment=payment, component='Gold', amount=Decimal('1'))
        Invoice.objects.create(order=order, issued_by=actor, invoice_no=f'INV-2026-{order.pk:05d}', snapshot={'total': '1'})
    for model in (Payment, PaymentAllocation, Invoice):
        assert model.objects.for_user(users['Staff']).count() == 2
        assert model.objects.for_user(actor).count() == 2
        assert not model.objects.for_user(AnonymousUser()).exists()
    assert not AuditLog.objects.for_user(users['Accounts']).exists()
    assert AuditLog.objects.for_user(actor).exists()


@pytest.mark.parametrize('role', ['Staff', 'Accounts'])
def test_dashboard_and_tampered_account_selection(client, access_data, role):
    a, b, c, users = access_data
    client.force_login(users[role])
    response = client.get('/')
    assert response.status_code == 200
    assert b'Account A' in response.content and b'Account B' in response.content and b'Account C' in response.content
    assert client.post(reverse('switch_account'), {'account_id': c.pk}).status_code == 302
    assert client.post(reverse('switch_account'), {'account_id': 'bad'}).status_code == 404
    assert client.get(reverse('switch_account')).status_code == 405
    assert client.post(reverse('switch_account'), {'account_id': a.pk}).status_code == 302
    assert client.session['account_id'] == a.pk
    assert list(client.get('/').context['rows'].values_list('pk', flat=True)) == [a.pk]
    assert client.post(reverse('switch_account'), {'account_id': 'all'}).status_code == 302
    assert 'account_id' not in client.session


def test_inactive_accounts_disappear_for_employees(client, access_data, actor):
    a, b, c, users = access_data
    user = users['Staff']
    client.force_login(user)
    client.post(reverse('switch_account'), {'account_id': b.pk})
    save_account(actor=actor, account_id=b.pk, data={'active': False})
    response = client.get('/')
    assert response.context['current_account'] is None
    assert b'Account B' not in response.content
    assert 'account_id' not in client.session


@pytest.mark.parametrize('role', ['Staff', 'Accounts'])
@pytest.mark.parametrize('name', ['account_list', 'account_create', 'account_edit', 'user_list', 'user_create', 'user_edit', 'user_password'])
def test_owner_pages_protected(client, access_data, role, name):
    a, b, c, users = access_data
    client.force_login(users[role])
    args = [a.pk] if name == 'account_edit' else [users[role].pk] if name in ('user_edit', 'user_password') else []
    url = reverse(name, args=args)
    assert client.get(url).status_code == 403
    assert client.post(url, {}).status_code == 403


def test_anonymous_redirect_and_csrf(actor):
    client = Client(enforce_csrf_checks=True)
    assert client.get('/').status_code == 302
    assert client.get(reverse('account_list')).status_code == 302
    assert client.post(reverse('login'), {'username': actor.email, 'password': PASSWORD}).status_code == 403
    client.force_login(actor)
    assert client.post(reverse('switch_account'), {'account_id': 'all'}).status_code == 403
    assert client.get(reverse('logout')).status_code == 405
    assert client.post(reverse('logout')).status_code == 403


def test_email_login_and_safe_redirect(client, access_data):
    user = access_data[3]['Staff']
    response = client.post(reverse('login'), {'username': ' STAFF@EXAMPLE.COM ', 'password': PASSWORD, 'next': 'https://evil.example/'})
    assert response.status_code == 302 and response.url == '/'
    assert client.get('/').status_code == 200
    assert client.post(reverse('logout')).status_code == 302
    assert client.get('/').status_code == 302
    assert authenticate(username=user.username, password=PASSWORD) is None


def test_five_failures_lock_fifteen_minutes(access_data):
    user = access_data[3]['Staff']
    now = timezone.now()
    with patch('accounts.services.timezone.now', return_value=now):
        for _ in range(5):
            assert authenticate(email=user.email, password='wrong') is None
        user.refresh_from_db()
        assert user.failed_login_attempts == 5
        assert user.locked_until == now + timedelta(minutes=15)
        assert authenticate(email=user.email, password=PASSWORD) is None
    with patch('accounts.services.timezone.now', return_value=now + timedelta(minutes=14, seconds=59)):
        assert authenticate(email=user.email, password=PASSWORD) is None
    with patch('accounts.services.timezone.now', return_value=now + timedelta(minutes=15)):
        assert authenticate(email=user.email, password=PASSWORD).pk == user.pk
    user.refresh_from_db()
    assert user.failed_login_attempts == 0 and user.locked_until is None


def test_success_resets_failures_and_inactive_user_denied(access_data):
    user = access_data[3]['Staff']
    for _ in range(4):
        assert authenticate(email=user.email, password='wrong') is None
    assert authenticate(email=user.email, password=PASSWORD) == user
    user.refresh_from_db()
    assert user.failed_login_attempts == 0
    user.is_active = False
    user.save()
    assert authenticate(email=user.email, password=PASSWORD) is None
    assert authenticate(email='unknown@example.com', password=PASSWORD) is None


def test_login_errors_do_not_reveal_account(client, access_data):
    user = access_data[3]['Staff']
    known = client.post(reverse('login'), {'username': user.email, 'password': 'wrong'})
    unknown = client.post(reverse('login'), {'username': 'unknown@example.com', 'password': 'wrong'})
    assert known.context['form'].non_field_errors() == unknown.context['form'].non_field_errors()


def test_owner_user_management_and_audit(client, actor, account):
    client.force_login(actor)
    count = AuditLog.objects.count()
    response = client.post(reverse('user_create'), {'email': ' NEW@EXAMPLE.COM ', 'role': 'Accounts',
        'is_active': 'on', 'password': PASSWORD})
    assert response.status_code == 302
    user = User.objects.get(email='new@example.com')
    assert user.check_password(PASSWORD)
    assert list(user.ebay_accounts.all()) == []
    assert AuditLog.objects.count() == count + 1
    log = AuditLog.objects.latest('pk')
    assert log.action == 'create' and log.after['accounts'] == []
    assert 'password' not in str(log.after) and PASSWORD not in str(log.after)
    response = client.post(reverse('user_edit', args=[user.pk]), {'email': user.email, 'role': 'Accounts',
        'is_active': 'on', 'ebay_accounts': [account.pk]})
    assert response.status_code == 302
    user.refresh_from_db()
    assert user.role == 'Accounts'
    assert AuditLog.objects.count() == count + 2
    assert AuditLog.objects.latest('pk').action == 'permission_change'


def test_owner_account_management(client, actor):
    client.force_login(actor)
    data = dict(code='NEW', display_name='New shop', active='on')
    count = AuditLog.objects.count()
    assert client.post(reverse('account_create'), data).status_code == 302
    account = EbayAccount.objects.get(code='NEW')
    assert account.ebay_username == 'NEW' and account.billing_name == 'New shop'
    data.pop('active')
    assert client.post(reverse('account_edit', args=[account.pk]), data).status_code == 302
    account.refresh_from_db()
    assert not account.active
    assert AuditLog.objects.count() == count + 2


def test_employee_assignment_optional_and_password_validation(actor, account):
    count = User.objects.count()
    user = save_user(actor=actor, data={'email': 'n@example.com', 'role': 'Accounts', 'password': PASSWORD})
    assert user.role == 'Accounts'
    with pytest.raises(ValidationError):
        save_user(actor=actor, data={'email': 'n@example.com', 'role': 'Staff', 'password': '123', 'ebay_accounts': [account]})
    assert User.objects.count() == count + 1


def test_last_owner_retained(actor):
    for data in ({'role': 'Staff'}, {'is_active': False}):
        with pytest.raises(ValidationError):
            save_user(actor=actor, user_id=actor.pk, data=data)
    actor.refresh_from_db()
    assert actor.role == 'Owner' and actor.is_active


def test_password_reset_invalidates_sessions(client, actor, access_data):
    user = access_data[3]['Staff']
    client.force_login(user)
    with pytest.raises(PermissionDenied):
        reset_password(actor=user, user_id=actor.pk, password=PASSWORD)
    replacement = 'Fresh!River-8907-Tree'
    count = AuditLog.objects.count()
    reset_password(actor=actor, user_id=user.pk, password=replacement)
    assert AuditLog.objects.count() == count + 1
    assert client.get('/').status_code == 302
    assert authenticate(email=user.email, password=PASSWORD) is None
    assert authenticate(email=user.email, password=replacement).pk == user.pk
    log = AuditLog.objects.get(action='password_reset', object_id=str(user.pk))
    assert log.before == {} and log.after == {}


def test_case_insensitive_email_unique(actor):
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create_user(email=actor.email.upper(), password=PASSWORD)


def test_createsuperuser_bootstraps_owner():
    user = User.objects.create_superuser(email='BOOT@EXAMPLE.COM', password=PASSWORD)
    assert user.role == 'Owner' and user.email == 'boot@example.com'
    assert can(user, 'manage_users')
    assert AuditLog.objects.filter(object_type='accounts.User', object_id=str(user.pk), action='create').count() == 1


def test_service_permissions_cannot_be_bypassed(access_data, actor, make_order):
    a, b, c, users = access_data
    staff = users['Staff']
    for user in users.values():
        with pytest.raises(PermissionDenied):
            save_account(actor=user, data={'code': 'X'})
        with pytest.raises(PermissionDenied):
            save_user(actor=user, user_id=user.pk, data={'role': 'Owner'})
    order = save_record(make_order(account=a), actor=actor)
    order.gold_rate = Decimal('100')
    with pytest.raises(PermissionDenied):
        save_record(order, actor=staff)
    foreign_order = save_record(make_order(account=c, sales_no=909), actor=actor)
    foreign_order.account = a
    save_record(foreign_order, actor=staff)


@pytest.mark.parametrize('name', ['account_list', 'account_create', 'account_edit', 'user_list', 'user_create', 'user_edit', 'user_password'])
def test_owner_pages_render(client, actor, account, name):
    client.force_login(actor)
    args = [account.pk] if name == 'account_edit' else [actor.pk] if name in ('user_edit', 'user_password') else []
    assert client.get(reverse(name, args=args)).status_code == 200


def test_owner_sees_unassigned_accounts(client, actor, access_data):
    client.force_login(actor)
    response = client.get('/')
    assert b'Account C' in response.content
    assert client.post(reverse('switch_account'), {'account_id': access_data[2].pk}).status_code == 302


def test_dashboard_counts_exclude_closed_deleted_and_other_accounts(client, access_data, make_order, actor):
    a, b, c, users = access_data
    save_record(make_order(account=a), actor=actor)
    save_record(make_order(account=a, sales_no=102, fulfilment_status='Delivered', tracking_no='TRACK'), actor=actor)
    save_record(make_order(account=a, sales_no=103, fulfilment_status='Cancelled'), actor=actor)
    save_record(make_order(account=a, sales_no=104, is_deleted=True), actor=actor)
    save_record(make_order(account=c), actor=actor)
    client.force_login(users['Staff'])
    response = client.get('/')
    assert [(row.pk, row.open_orders) for row in response.context['rows']] == [(a.pk, 1), (b.pk, 0), (c.pk, 1)]


def test_deactivation_revokes_existing_session(client, access_data, actor):
    user = access_data[3]['Staff']
    client.force_login(user)
    save_user(actor=actor, user_id=user.pk, data={'is_active': False})
    assert client.get('/').status_code == 302


def test_role_demotion_takes_effect_next_request(client, access_data, actor):
    other_owner = save_user(actor=actor, data={'email': 'other@example.com', 'role': 'Owner', 'password': PASSWORD})
    client.force_login(other_owner)
    assert client.get(reverse('user_list')).status_code == 200
    save_user(actor=actor, user_id=other_owner.pk, data={'role': 'Staff', 'ebay_accounts': [access_data[0]]})
    assert client.get(reverse('user_list')).status_code == 403


def test_owner_reset_form_validation_and_unlock(client, access_data, actor):
    user = access_data[3]['Staff']
    for _ in range(5):
        authenticate(email=user.email, password='wrong')
    client.force_login(actor)
    url = reverse('user_password', args=[user.pk])
    count = AuditLog.objects.filter(action='password_reset').count()
    response = client.post(url, {'password': PASSWORD, 'confirm_password': 'different'})
    assert response.status_code == 200
    assert AuditLog.objects.filter(action='password_reset').count() == count
    new_password = 'New!Stream-8240-Tree'
    assert client.post(url, {'password': new_password, 'confirm_password': new_password}).status_code == 302
    user.refresh_from_db()
    assert user.failed_login_attempts == 0 and user.locked_until is None
    assert user.check_password(new_password)


def test_user_assignment_update_rolls_back_on_invalid_input(actor, access_data):
    user = access_data[3]['Staff']
    count = AuditLog.objects.count()
    with pytest.raises(ValidationError):
        save_user(actor=actor, user_id=user.pk, data={'role': 'Wrong', 'ebay_accounts': []})
    user.refresh_from_db()
    assert user.role == 'Staff'
    assert user.ebay_accounts.count() == 2
    assert AuditLog.objects.count() == count


def test_csrf_valid_login_and_signout(access_data):
    client = Client(enforce_csrf_checks=True)
    client.get(reverse('login'))
    token = client.cookies['csrftoken'].value
    assert client.post(reverse('login'), {'username': 'staff@example.com', 'password': PASSWORD, 'csrfmiddlewaretoken': token}).status_code == 302
    client.get('/')
    assert client.post(reverse('logout'), {'csrfmiddlewaretoken': client.cookies['csrftoken'].value}).status_code == 302


def test_unknown_fields_cannot_escalate_privileges(actor, account):
    with pytest.raises(ValidationError):
        save_user(actor=actor, data={'email': 'x@example.com', 'role': 'Staff', 'is_superuser': True,
            'password': PASSWORD, 'ebay_accounts': [account]})


def test_staff_sensitive_edits_after_payment(access_data, make_order, actor):
    order = save_record(make_order(), actor=actor)
    Payment.objects.create(order=order, payment_date=timezone.localdate(), amount=Decimal('1'), method='Cash', created_by=actor)
    order.diamond_value = Decimal('90000')
    with pytest.raises(PermissionDenied):
        save_record(order, actor=access_data[3]['Staff'])
    save_record(order, actor=access_data[3]['Accounts'])


def test_nonowners_cannot_change_settings_or_delete_orders(access_data, make_order, actor):
    from core.models import Settings
    order = save_record(make_order(), actor=actor)
    order.is_deleted = True
    for user in access_data[3].values():
        with pytest.raises(PermissionDenied):
            save_record(order, actor=user)
        with pytest.raises(PermissionDenied):
            save_record(Settings(), actor=user)


def test_nonowner_cannot_bulk_delete_orders(access_data, make_order, actor, client):
    order = save_record(make_order(), actor=actor)
    client.force_login(access_data[3]['Staff'])
    response = client.post(reverse('order_bulk_delete'), {'order_ids': [str(order.pk)], 'reason': 'No permission'})
    assert response.status_code == 403
    assert Order.objects.filter(pk=order.pk).exists()


def test_deleted_order_hidden_even_in_nonowner_history_scope(access_data, make_order, actor):
    order = save_record(make_order(is_deleted=True), actor=actor)
    assert not Order.all_objects.for_user(access_data[3]['Staff']).filter(pk=order.pk).exists()
    assert Order.all_objects.for_user(actor).filter(pk=order.pk).exists()
    assert not Order.objects.for_user(actor).filter(pk=order.pk).exists()
