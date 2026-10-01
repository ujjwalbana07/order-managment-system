from datetime import date
from decimal import Decimal
import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from accounts.models import EbayAccount
from audit.models import AuditLog
from core.models import Settings
from core.services import save_record
from orders.models import Order
from payments.models import Payment, PaymentAllocation

pytestmark = pytest.mark.django_db


def test_unique_account_sales(make_order, actor, account):
    first = save_record(make_order(), actor=actor)
    with pytest.raises(ValidationError):
        save_record(make_order(), actor=actor)
    second_account = save_record(EbayAccount(code='B', display_name='B', ebay_username='b', billing_name='B',
        billing_address='Address', phone='123', email='b@example.com'), actor=actor)
    second = save_record(make_order(account=second_account), actor=actor)
    assert first.serial_no != second.serial_no
    with pytest.raises(IntegrityError), transaction.atomic():
        Order.all_objects.filter(pk=second.pk).update(account=account)


@pytest.mark.parametrize('value', ['0', '-1'])
def test_net_weight_model_and_database(make_order, actor, value):
    with pytest.raises(ValidationError):
        save_record(make_order(gross_wt=Decimal('1.512') + Decimal(value)), actor=actor)
    order = save_record(make_order(), actor=actor)
    with pytest.raises(IntegrityError), transaction.atomic():
        Order.all_objects.filter(pk=order.pk).update(net_wt=Decimal(value))


@pytest.mark.parametrize('field', ['usd_sold', 'fx_rate', 'inr_sold', 'ship_charges', 'platform_fees_inr', 'gold_rate', 'lab_rate', 'diamond_value'])
def test_negative_money_model_and_database(make_order, actor, field):
    with pytest.raises(ValidationError):
        save_record(make_order(**{field: Decimal('-0.01')}), actor=actor)
    order = save_record(make_order(), actor=actor)
    with pytest.raises(IntegrityError), transaction.atomic():
        Order.all_objects.filter(pk=order.pk).update(**{field: Decimal('-0.01')})


@pytest.mark.parametrize('field', ['gold_amount', 'labour_amount', 'total_bill'])
def test_derived_money_database_constraint(make_order, actor, field):
    order = save_record(make_order(), actor=actor)
    with pytest.raises(IntegrityError), transaction.atomic():
        Order.all_objects.filter(pk=order.pk).update(**{field: Decimal('-0.01')})


@pytest.mark.parametrize('changes', [dict(purity=Decimal('0')), dict(purity=Decimal('1.0001')),
    dict(quantity=0), dict(ship_by_date=date(2025, 12, 31)), dict(fulfilment_status='Shipped', tracking_no='  '),
    dict(dia_ct=Decimal('-1')), dict(other_wt=Decimal('-1')), dict(inr_sold=Decimal('NaN')),
    dict(diamond_value=Decimal('1.001'))])
def test_order_validation(make_order, actor, changes):
    with pytest.raises(ValidationError):
        save_record(make_order(**changes), actor=actor)


def test_recalculation_audit_and_retention(make_order, actor):
    order = make_order(gold_amount=Decimal('0'))
    save_record(order, actor=actor)
    assert order.gold_amount == Decimal('24469.75')
    assert order.buyer_username == 'buyer'
    order.gold_rate = Decimal('10000')
    save_record(order, actor=actor)
    order.refresh_from_db()
    assert order.gold_amount == Decimal('16313.17')
    logs = AuditLog.objects.filter(object_type='orders.Order', object_id=str(order.pk))
    assert logs.count() == 2
    assert logs.latest('timestamp').before['gold_rate'] == '15000.00'
    with pytest.raises(ValidationError):
        order.delete()
    with pytest.raises(ValidationError):
        Order.all_objects.filter(pk=order.pk).delete()
    order.is_deleted = True
    save_record(order, actor=actor)
    assert not Order.objects.filter(pk=order.pk).exists()
    assert Order.all_objects.filter(pk=order.pk).exists()
    assert save_record(make_order(sales_no=102), actor=actor).pk > order.pk


def test_settings_snapshot_singleton(make_order, actor):
    config = save_record(Settings(company_name='Company', address='Address', phone='123', email='c@example.com'), actor=actor)
    values = make_order().__dict__.copy()
    values.pop('_state')
    values.pop('gold_rate')
    values.pop('fx_rate')
    order = save_record(Order(**values), actor=actor)
    config.default_gold_rate = Decimal('20000')
    config.default_fx_rate = Decimal('99')
    save_record(config, actor=actor)
    order.refresh_from_db()
    assert order.gold_rate == Decimal('15000')
    assert order.fx_rate == Decimal('91')
    assert Order().gold_rate == Decimal('20000')
    config.pk = 2
    with pytest.raises(ValidationError):
        config.save()


def test_audit_append_only(account, actor):
    log = AuditLog.objects.first()
    with pytest.raises(ValidationError):
        log.save()
    with pytest.raises(ValidationError):
        log.delete()
    with pytest.raises(ValidationError):
        AuditLog.objects.update(note='changed')
    with pytest.raises(ValidationError):
        AuditLog.objects.all().delete()


@pytest.mark.parametrize('model,field', [(Settings, 'default_gold_rate'), (Settings, 'default_fx_rate'), (EbayAccount, 'default_gold_rate')])
def test_configuration_negative_money(model, field, actor, account):
    record = account if model is EbayAccount else Settings(company_name='C', address='A', phone='1', email='c@example.com')
    setattr(record, field, Decimal('-1'))
    with pytest.raises(ValidationError):
        save_record(record, actor=actor)


@pytest.mark.parametrize('amount', ['0', '-0.01'])
def test_payment_and_allocation_positive(make_order, actor, amount):
    order = save_record(make_order(), actor=actor)
    payment = Payment(order=order, payment_date=date(2026, 1, 1), amount=Decimal(amount), method='Cash', created_by=actor)
    with pytest.raises(ValidationError):
        payment.full_clean()
    allocation = PaymentAllocation(payment=payment, component='Gold', amount=Decimal(amount))
    with pytest.raises(ValidationError):
        allocation.full_clean()


def test_allocation_collection_exact_sum():
    payment = Payment(amount=Decimal('10000.00'))
    payment.validate_allocations([PaymentAllocation(component='Gold', amount=Decimal('10000.00'))])
    with pytest.raises(ValidationError, match='exactly'):
        payment.validate_allocations([PaymentAllocation(component='Gold', amount=Decimal('9999.99'))])
    with pytest.raises(ValidationError, match='one allocation'):
        payment.validate_allocations([PaymentAllocation(component='Gold', amount=Decimal('5000.00'))] * 2)


def test_invoice_number_and_snapshot(make_order, actor):
    from documents.models import Invoice
    order = save_record(make_order(), actor=actor)
    invoice = Invoice(order=order, issued_by=actor, snapshot={'total': '115619.75'}, invoice_no='bad')
    with pytest.raises(ValidationError):
        invoice.full_clean()
    invoice.invoice_no = 'INV-2026-00001'
    # Persistence here deliberately tests the low-level immutable model.
    invoice.save()
    invoice.snapshot = {'total': '0.00'}
    with pytest.raises(ValidationError):
        invoice.save()


def test_three_decimal_weight_entry(make_order, actor):
    with pytest.raises(ValidationError, match='three decimal'):
        save_record(make_order(dia_ct=Decimal('7.5601')), actor=actor)


def test_zero_default_gold_rate(make_order, actor):
    save_record(Settings(company_name='C', address='A', phone='1', email='c@example.com',
        default_gold_rate=Decimal('0')), actor=actor)
    assert Order().gold_rate == Decimal('0')


def test_failed_write_rolls_back_audit(make_order, actor):
    count = AuditLog.objects.count()
    with pytest.raises(ValidationError):
        save_record(make_order(inr_sold=Decimal('-1')), actor=actor)
    assert AuditLog.objects.count() == count
    assert Order.all_objects.count() == 0
