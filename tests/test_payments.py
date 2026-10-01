import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from threading import Barrier
import pytest
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import close_old_connections
from django.utils import timezone
from accounts.models import User
from core.services import save_record
from core.costing import split_automatically
from orders.services import save_order
from payments.services import post_payment, void_payment, balances
from payments.models import Payment
from audit.models import AuditLog

GOLDEN = json.loads((Path(__file__).resolve().parents[1] / 'oms-pack/golden_cases.json').read_text())
pytestmark = pytest.mark.django_db


def pay(order, actor, amount, gold=None, **kwargs):
    return post_payment(actor=actor, order_id=order.pk, payment_date=timezone.localdate(), amount=Decimal(amount),
        method='Cash', allocations={'Gold': Decimal(gold if gold is not None else amount)}, **kwargs)


def test_every_golden_payment_step(make_order, actor):
    case = next(case for case in GOLDEN['calc_cases'] if case['sales_no'] == 106)
    order = save_record(make_order(**{name: Decimal(value) for name, value in case['inputs'].items()}), actor=actor)
    first = None
    for index, step in enumerate(GOLDEN['payment_cases']['steps']):
        if index == 0:
            first = pay(order, actor, '10000')
        elif index == 1:
            post_payment(actor=actor, order_id=order.pk, payment_date=timezone.localdate(), amount=Decimal('20685.30'), method='Cash',
                allocations={'Gold': Decimal('7760.30'), 'Diamond': Decimal('10450'), 'Labour': Decimal('2475')})
        elif index == 2:
            void_payment(actor=actor, payment_id=first.pk, reason='Correction')
        elif index == 3:
            with pytest.raises(ValidationError, match='equal'):
                pay(order, actor, '10000', gold='9999.99')
        elif index == 4:
            fresh = save_record(make_order(sales_no=200, **{name: Decimal(value) for name, value in case['inputs'].items()}), actor=actor)
            with pytest.raises(ValidationError, match='exceeds Gold'):
                pay(fresh, actor, '17760.31')
        elif index == 5:
            with pytest.raises(ValidationError, match='lower than what is already paid for Gold'):
                save_order(actor=actor, order_id=order.pk, version=order.version, data={'gold_rate': Decimal('0')})
        elif index == 6:
            order = fresh
        if isinstance(step['expect'], dict):
            balance = balances(order)
            keys = {f'{name.lower()}_out': value for name, value in balance['outstanding'].items()}
            keys.update(total_out=balance['total_outstanding'], status=balance['status'])
            for key, expected in step['expect'].items():
                assert keys[key] == (expected if key == 'status' else Decimal(expected))
    assert Payment.objects.count() == 2


def test_owner_overpayment_and_void_requirements(make_order, actor):
    order = save_record(make_order(), actor=actor)
    amount = str(order.gold_amount + Decimal('1'))
    with pytest.raises(ValidationError, match='reason'):
        pay(order, actor, amount, approve_overpayment=True)
    payment = pay(order, actor, amount, approve_overpayment=True, overpayment_reason='Agreed advance')
    assert payment.overpayment_approved_by == actor
    assert balances(order)['outstanding']['Gold'] == Decimal('-1')
    with pytest.raises(ValidationError, match='reason'):
        void_payment(actor=actor, payment_id=payment.pk, reason='')
    void_payment(actor=actor, payment_id=payment.pk, reason='Reverse advance')
    assert balances(order)['status'] == 'Unpaid'
    assert order.payments.count() == 1


def test_payment_validation_and_audit(make_order, actor):
    order = save_record(make_order(), actor=actor)
    count = AuditLog.objects.count()
    with pytest.raises(ValidationError):
        post_payment(actor=actor, order_id=order.pk, amount=Decimal('1'), allocations={'Gold': Decimal('1')},
            payment_date=timezone.localdate() + timedelta(days=1), method='Cash')
    with pytest.raises(ValidationError):
        post_payment(actor=actor, order_id=order.pk, amount=Decimal('1'), allocations={'Gold': Decimal('1')},
            payment_date=timezone.localdate(), method='UPI', reference_no='  ')
    assert AuditLog.objects.count() == count and not Payment.objects.exists()
    payment = pay(order, actor, '1')
    assert AuditLog.objects.count() == count + 1
    assert split_automatically(Decimal('2'), {'Gold': Decimal('1'), 'Diamond': Decimal('2'), 'Labour': Decimal('0')}) == {'Gold': Decimal('1'), 'Diamond': Decimal('1'), 'Labour': Decimal('0')}
    payment.amount = Decimal('2')
    with pytest.raises(ValidationError):
        payment.save()


def test_payment_roles_and_scoped_urls(make_order, actor, account, client):
    order = save_record(make_order(), actor=actor)
    staff = User.objects.create_user(email='staffp@example.com', role='Staff')
    accounts = User.objects.create_user(email='accountsp@example.com', role='Accounts')
    staff.ebay_accounts.add(account)
    accounts.ebay_accounts.add(account)
    with pytest.raises(PermissionDenied):
        pay(order, staff, '1')
    payment = pay(order, accounts, '1')
    with pytest.raises(PermissionDenied):
        void_payment(actor=accounts, payment_id=payment.pk, reason='Not allowed')
    with pytest.raises(PermissionDenied):
        pay(order, accounts, '1', approve_overpayment=True, overpayment_reason='Not allowed')
    client.force_login(actor)
    assert client.get(f'/orders/{order.pk}/payments/new/').status_code == 200
    assert client.get(f'/orders/{order.pk}/').status_code == 200
    staff.ebay_accounts.clear()
    client.force_login(staff)
    for suffix in ('', 'photo/', 'edit/'):
        assert client.get(f'/orders/{order.pk}/{suffix}').status_code == 404


@pytest.mark.django_db(transaction=True)
def test_simultaneous_payments_only_one_succeeds(make_order, actor):
    order = save_record(make_order(), actor=actor)
    barrier = Barrier(2)
    def run():
        close_old_connections()
        user = User.objects.get(pk=actor.pk)
        barrier.wait(timeout=5)
        try:
            pay(order, user, str(order.gold_amount))
            return 'posted'
        except ValidationError:
            return 'rejected'
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert sorted(results) == ['posted', 'rejected']
    assert Payment.objects.filter(order=order).count() == 1


def test_payment_queryset_cannot_rewrite_history(make_order, actor):
    order = save_record(make_order(), actor=actor)
    payment = pay(order, actor, '1')
    with pytest.raises(ValidationError):
        Payment.objects.filter(pk=payment.pk).update(amount=Decimal('2'))
    with pytest.raises(ValidationError):
        payment.allocations.update(amount=Decimal('2'))
