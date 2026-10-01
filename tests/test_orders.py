from io import BytesIO
from decimal import Decimal
import pytest
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError
from django.urls import reverse
from audit.models import AuditLog
from orders.models import Order
from orders.services import save_order, set_deleted, INPUT_FIELDS
from orders.forms import OrderForm
from core.services import save_record

pytestmark = pytest.mark.django_db


def data_for(order):
    return {name: getattr(order, name) for name in INPUT_FIELDS}


def test_version_conflict_and_single_audit(make_order, actor):
    order = save_order(actor=actor, data=data_for(make_order()))
    count = AuditLog.objects.count()
    updated = save_order(actor=actor, order_id=order.pk, version=1, data={'item_title': 'Changed'})
    assert updated.version == 2 and AuditLog.objects.count() == count + 1
    with pytest.raises(ValidationError, match='Someone else'):
        save_order(actor=actor, order_id=order.pk, version=1, data={'item_title': 'Stale'})
    order.refresh_from_db()
    assert order.item_title == 'Changed'
    assert AuditLog.objects.count() == count + 1


def test_delete_requires_confirmation_restore_preserves_identity(make_order, actor):
    order = save_order(actor=actor, data=data_for(make_order()))
    with pytest.raises(ValidationError):
        set_deleted(actor=actor, order_id=order.pk, version=1, deleted=True)
    set_deleted(actor=actor, order_id=order.pk, version=1, deleted=True, confirmation='DELETE', reason='Duplicate entry')
    assert not Order.objects.filter(pk=order.pk).exists()
    restored = set_deleted(actor=actor, order_id=order.pk, version=2, deleted=False)
    assert restored.pk == order.pk and restored.version == 3
    assert restored.delete_reason == ''


def test_photo_sanitized_private_and_invalid_rejected(make_order, actor, client, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    output = BytesIO()
    photo = Image.new('RGB', (2000, 1200), 'red')
    exif = Image.Exif()
    exif[270] = 'Sensitive metadata'
    photo.save(output, 'JPEG', exif=exif)
    upload = SimpleUploadedFile('anything.exe', output.getvalue(), content_type='application/octet-stream')
    order = save_order(actor=actor, data=data_for(make_order()), image=upload)
    with Image.open(order.image.path) as saved:
        assert max(saved.size) == 1600
        assert not saved.getexif()
    with Image.open(order.thumbnail.path) as saved:
        assert max(saved.size) <= 240
    assert client.get(reverse('order_photo', args=[order.pk])).status_code == 302
    client.force_login(actor)
    assert client.get(reverse('order_photo', args=[order.pk])).status_code == 200
    with pytest.raises(ValidationError, match='image'):
        save_order(actor=actor, data=data_for(make_order(sales_no=102)), image=SimpleUploadedFile('fake.jpg', b'not an image'))
    assert Order.objects.count() == 1


def test_order_pages_and_form_save(make_order, actor, client):
    client.force_login(actor)
    data = {key: str(value.pk if key == 'account' else value) if value is not None else '' for key, value in data_for(make_order()).items()}
    data.update(purity='59.5', version='1')
    response = client.post(reverse('order_create'), data)
    assert response.status_code == 302, response.context['form'].errors if response.status_code == 200 else ''
    order = Order.objects.get()
    for name in ('order_detail', 'order_edit', 'order_delete'):
        assert client.get(reverse(name, args=[order.pk])).status_code == 200
    assert client.get(reverse('order_list')).status_code == 200
    duplicate = client.post(reverse('order_create'), data)
    assert duplicate.status_code == 200 and duplicate.context['duplicate'] == order
    assert Order.objects.count() == 1


def test_totals_and_search_cover_filter(make_order, actor, client):
    one = save_record(make_order(), actor=actor)
    save_record(make_order(sales_no=102, buyer_username='another'), actor=actor)
    client.force_login(actor)
    response = client.get(reverse('order_list'), {'q': '101'})
    assert response.context['page'].paginator.count == 1
    assert response.context['totals']['total_bill'] == one.total_bill
    assert client.get(reverse('order_list'), {'from': 'invalid'}).status_code == 200


def test_purity_fraction_prompts_and_low_percent_confirmed(actor, make_order):
    data = data_for(make_order())
    data['account'] = data['account'].pk
    data.update(purity='0.595', version=1)
    form = OrderForm(data, actor=actor)
    assert not form.is_valid()
    assert 'Did you mean 59.500%' in str(form.errors)
    data.update(purity='0.5', purity_confirm=True)
    form = OrderForm(data, actor=actor)
    assert form.is_valid(), form.errors
    assert form.cleaned_data['purity'] == Decimal('0.005')


def test_server_sale_suggestion_and_account_rate(make_order, actor, account, client):
    client.force_login(actor)
    response = client.post('/orders/preview/', {'usd_sold': '10.11', 'fx_rate': '91.0000'})
    assert response.json()['suggested_inr'] == '920.01'
    account.default_gold_rate = Decimal('16000')
    save_record(account, actor=actor)
    assert client.get(f'/orders/account-defaults/{account.pk}/').json()['gold_rate'] == '16000.00'


@pytest.mark.parametrize('value', ['1e99999999', 'NaN'])
def test_costing_preview_rejects_extreme_numbers(actor, client, value):
    client.force_login(actor)
    response = client.post('/orders/preview/', {'gross_wt': value, 'purity': '59.5', 'gold_rate': '15000'})
    assert response.status_code == 400 and 'error' in response.json()


def test_negative_sales_number_rejected(make_order, actor):
    with pytest.raises(ValidationError):
        save_order(actor=actor, data=data_for(make_order(sales_no=-1)))
