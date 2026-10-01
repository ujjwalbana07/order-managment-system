from datetime import date
from decimal import Decimal
import pytest
from accounts.models import EbayAccount, User
from core.services import save_record
from orders.models import Order


@pytest.fixture
def actor(db):
    return User.objects.create_user(username='owner', role='Owner', email='owner@example.com', password='test-only-password')


@pytest.fixture
def account(actor):
    return save_record(EbayAccount(code='A', display_name='Account A', ebay_username='account-a',
        billing_name='Account A', billing_address='Address', phone='123', email='a@example.com'), actor=actor)


@pytest.fixture
def make_order(account, actor):
    def make(**overrides):
        values = dict(account=account, sales_no=101, order_date=date(2026, 1, 1),
            buyer_username=' Buyer ', item_title='Ring', purity=Decimal('0.595'),
            gross_wt=Decimal('4.24'), dia_ct=Decimal('7.56'), other_wt=Decimal('0'),
            gold_rate=Decimal('15000'), lab_rate=Decimal('1250'), diamond_value=Decimal('87740'),
            inr_sold=Decimal('169192.66'), ship_charges=Decimal('5000'), created_by=actor, updated_by=actor)
        return Order(**(values | overrides))
    return make
