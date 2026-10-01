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
    result = preview(content, account=account, actor=actor)
    assert result['gaps'] == [(104, 104)]
    assert result['rows'][1]['status'] == 'Difference'
    assert '2513' in ' '.join(result['rows'][1]['messages'])
    assert not result['has_errors']
    assert all(row['image_bytes'] for row in result['rows'])
    batch = create_batch(actor=actor, account=account, upload=SimpleUploadedFile('rows.xlsx', content))
    assert commit_batch(actor=actor, batch_id=batch.pk) == 6
    assert commit_batch(actor=actor, batch_id=batch.pk) == 0
    second = create_batch(actor=actor, account=account, upload=SimpleUploadedFile('rows.xlsx', content))
    assert commit_batch(actor=actor, batch_id=second.pk) == 0
    assert Order.objects.count() == 6
    for row in SEED:
        order = Order.objects.get(sales_no=row['sales_no'])
        assert order.gold_rate == Decimal(row['gold_rate'])
        assert order.total_bill == Decimal(row['total_bill'])
        assert order.net_earnings == Decimal(row['net_earnings'])
        assert order.image and order.thumbnail


def test_blank_other_weight_imports_as_zero(actor, account):
    content = workbook()
    result = preview(content, account=account, actor=actor)
    assert not result['has_errors']
    assert all(row['data']['other_wt'] == Decimal('0') for row in result['rows'])


def test_import_ignores_soft_deleted_sales_numbers(actor, account):
    content = workbook()
    batch = create_batch(actor=actor, account=account, upload=SimpleUploadedFile('rows.xlsx', content))
    assert commit_batch(actor=actor, batch_id=batch.pk) == 6
    Order.objects.filter(account=account).update(is_deleted=True)
    result = preview(content, account=account, actor=actor)
    assert {row['status'] for row in result['rows']} <= {'New', 'Difference'}
    second = create_batch(actor=actor, account=account, upload=SimpleUploadedFile('rows.xlsx', content))
    assert commit_batch(actor=actor, batch_id=second.pk) == 6
    assert Order.objects.count() == 6
    assert Order.all_objects.count() == 12


def test_import_one_bad_row_commits_nothing(actor, account):
    content = workbook(bad=True)
    batch = create_batch(actor=actor, account=account, upload=SimpleUploadedFile('rows.xlsx', content))
    count = AuditLog.objects.count()
    with pytest.raises(ValidationError, match='No orders'):
        commit_batch(actor=actor, batch_id=batch.pk)
    assert not Order.objects.exists()
    assert AuditLog.objects.count() == count


def test_mid_commit_failure_rolls_back_database_audit_and_photos(actor, account, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    batch = create_batch(actor=actor, account=account, upload=SimpleUploadedFile('rows.xlsx', workbook(photos=True)))
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


def test_import_commit_database_error_shows_message(actor, account, client):
    batch = create_batch(actor=actor, account=account, upload=SimpleUploadedFile('rows.xlsx', workbook()))
    client.force_login(actor)
    from django.db import IntegrityError
    with patch('imports.views.commit_batch', side_effect=IntegrityError('duplicate')):
        response = client.post(f'/imports/{batch.pk}/')
    assert response.status_code == 200
    assert b'Import could not be saved' in response.content


def test_import_commit_unexpected_error_shows_message(actor, account, client):
    batch = create_batch(actor=actor, account=account, upload=SimpleUploadedFile('rows.xlsx', workbook()))
    client.force_login(actor)
    with patch('imports.views.commit_batch', side_effect=RuntimeError('boom')):
        response = client.post(f'/imports/{batch.pk}/')
    assert response.status_code == 200
    assert b'Import could not be saved' in response.content


def test_import_review_uses_cached_preview(actor, account, client):
    batch = create_batch(actor=actor, account=account, upload=SimpleUploadedFile('rows.xlsx', workbook()))
    client.force_login(actor)
    with patch('imports.views.preview', side_effect=RuntimeError('boom')):
        response = client.get(f'/imports/{batch.pk}/')
    assert response.status_code == 200
    assert b'Review import' in response.content


def test_older_import_batch_without_cache_redirects_to_upload(actor, account, client):
    batch = create_batch(actor=actor, account=account, upload=SimpleUploadedFile('rows.xlsx', workbook()))
    batch.preview_cache = {}
    batch.save()
    client.force_login(actor)
    response = client.get(f'/imports/{batch.pk}/')
    assert response.status_code == 302
    assert response['Location'] == '/imports/'


def test_import_review_unhandled_error_shows_owner_debug(actor, account, client):
    batch = create_batch(actor=actor, account=account, upload=SimpleUploadedFile('rows.xlsx', workbook()))
    client.force_login(actor)
    with patch('imports.views._review', side_effect=RuntimeError('boom')):
        response = client.get(f'/imports/{batch.pk}/')
    assert response.status_code == 500
    assert b'Import failed' in response.content
    assert b'RuntimeError' in response.content


def test_import_pages_and_other_user_batch_denied(actor, account, client):
    client.force_login(actor)
    assert client.get('/imports/').status_code == 200
    response = client.post('/imports/', {'account': account.pk, 'file': SimpleUploadedFile('rows.xlsx', workbook())})
    assert response.status_code == 302
    assert client.get(response.url).status_code == 200
    other = User.objects.create_user(email='otherimport@example.com', role='Owner')
    client.force_login(other)
    assert client.get(response.url).status_code == 404
    assert client.post(response.url).status_code == 404


def test_import_diagnostics_owner_only(actor, account, client):
    create_batch(actor=actor, account=account, upload=SimpleUploadedFile('rows.xlsx', workbook()))
    client.force_login(actor)
    response = client.get('/manage/import-diagnostics/')
    assert response.status_code == 200
    assert b'Import diagnostics' in response.content
    batch_id = response.context['batches'][0]['id']
    debug_response = client.get(f'/manage/import-diagnostics/{batch_id}/')
    assert debug_response.status_code == 200
    assert b'DRY RUN OK' in debug_response.content
    staff = User.objects.create_user(username='staff-import-diagnostics', email='staff-import-diagnostics@example.com', role='Staff')
    staff.ebay_accounts.add(account)
    client.force_login(staff)
    assert client.get('/manage/import-diagnostics/').status_code == 403


def test_seed_command_uses_six_supplied_photos(actor, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    output = StringIO()
    call_command('seed_demo', owner=actor.email, stdout=output)
    call_command('seed_demo', owner=actor.email, stdout=output)
    assert Order.objects.count() == 6
    assert 'Created 6' in output.getvalue() and 'Created 0' in output.getvalue()
    assert all(order.thumbnail for order in Order.objects.all())
