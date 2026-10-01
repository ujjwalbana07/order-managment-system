from io import BytesIO, StringIO
import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
import pytest
from openpyxl import Workbook
from openpyxl.drawing.image import Image
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from accounts.models import User
from audit.models import AuditLog
from imports.services import HEADERS, preview, create_batch, commit_batch
from orders.models import Order
from orders.services import save_order

pytestmark = pytest.mark.django_db
ROOT = Path(__file__).resolve().parents[1] / 'oms-pack/seed'
SEED = json.loads((ROOT / 'seed_rows.json').read_text())


def workbook(bad=False, photos=False):
    book = Workbook()
    sheet = book.active
    sheet.append(list(HEADERS))
    mapping = {'ship_by_date': 'ship_by', 'buyer_username': 'buyer', 'item_title': 'title', 'quantity': 'qty', 'tracking_no': 'tracking'}
    for index, source in enumerate(SEED, 2):
        row = [source.get(mapping.get(name, name)) if name != 'image' else None for name in HEADERS.values()]
        if bad and index == 3:
            row[list(HEADERS.values()).index('gross_wt')] = '-1'
        if index == 3:
            row[list(HEADERS.values()).index('labour_amount')] = '2513'
            row[list(HEADERS.values()).index('net_earnings')] = '22048.65'
        sheet.append(row)
        if photos:
            photo = Image(ROOT / source['image'])
            sheet.add_image(photo, f'E{index}')
    output = BytesIO()
    book.save(output)
    return output.getvalue()


def test_real_rows_preview_differences_images_and_idempotency(actor, account, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    content = workbook(photos=True)
    result = preview(content, account=account, actor=actor, gold_rate=Decimal('15000'))
    assert result['gaps'] == [(104, 104)]
    assert result['rows'][1]['status'] == 'Difference'
    assert '2513' in ' '.join(result['rows'][1]['messages'])
    assert not result['has_errors']
    assert all(row['image_bytes'] for row in result['rows'])
    batch = create_batch(actor=actor, account=account, upload=SimpleUploadedFile('rows.xlsx', content), gold_rate=Decimal('15000'))
    assert commit_batch(actor=actor, batch_id=batch.pk) == 6
    assert commit_batch(actor=actor, batch_id=batch.pk) == 0
    second = create_batch(actor=actor, account=account, upload=SimpleUploadedFile('rows.xlsx', content), gold_rate=Decimal('15000'))
    assert commit_batch(actor=actor, batch_id=second.pk) == 0
    assert Order.objects.count() == 6
    for row in SEED:
        order = Order.objects.get(sales_no=row['sales_no'])
        assert order.total_bill == Decimal(row['total_bill'])
        assert order.net_earnings == Decimal(row['net_earnings'])
        assert order.image and order.thumbnail


def test_import_one_bad_row_commits_nothing(actor, account):
    content = workbook(bad=True)
    batch = create_batch(actor=actor, account=account, upload=SimpleUploadedFile('rows.xlsx', content), gold_rate=Decimal('15000'))
    count = AuditLog.objects.count()
    with pytest.raises(ValidationError, match='No orders'):
        commit_batch(actor=actor, batch_id=batch.pk)
    assert not Order.objects.exists()
    assert AuditLog.objects.count() == count


def test_mid_commit_failure_rolls_back_database_audit_and_photos(actor, account, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    batch = create_batch(actor=actor, account=account, upload=SimpleUploadedFile('rows.xlsx', workbook(photos=True)), gold_rate=Decimal('15000'))
    count = AuditLog.objects.count()
    calls = 0
    def fail_second(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValidationError('Simulated failure')
        return save_order(**kwargs)
    with patch('imports.services.save_order', side_effect=fail_second), pytest.raises(ValidationError):
        commit_batch(actor=actor, batch_id=batch.pk)
    assert not Order.objects.exists()
    assert AuditLog.objects.count() == count
    assert not list(tmp_path.rglob('*.jpg'))


def test_import_pages_and_other_user_batch_denied(actor, account, client):
    client.force_login(actor)
    assert client.get('/imports/').status_code == 200
    response = client.post('/imports/', {'account': account.pk, 'gold_rate': '15000', 'file': SimpleUploadedFile('rows.xlsx', workbook())})
    assert response.status_code == 302
    assert client.get(response.url).status_code == 200
    other = User.objects.create_user(email='otherimport@example.com', role='Owner')
    client.force_login(other)
    assert client.get(response.url).status_code == 404
    assert client.post(response.url).status_code == 404


def test_seed_command_uses_six_supplied_photos(actor, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    output = StringIO()
    call_command('seed_demo', owner=actor.email, stdout=output)
    call_command('seed_demo', owner=actor.email, stdout=output)
    assert Order.objects.count() == 6
    assert 'Created 6' in output.getvalue() and 'Created 0' in output.getvalue()
    assert all(order.thumbnail for order in Order.objects.all())
