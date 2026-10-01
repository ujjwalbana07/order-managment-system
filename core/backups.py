from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
import json
import os
import sqlite3
import subprocess
import tempfile
from zipfile import ZipFile, ZIP_DEFLATED
from django.conf import settings
from django.db import connection, transaction
from django.core.exceptions import ValidationError
from accounts.access import require
from audit.models import AuditLog
from documents.renderers import workbook_bytes


def add_media(archive):
    root = Path(settings.MEDIA_ROOT)
    if root.exists():
        for path in root.rglob('*'):
            if path.is_file() and not path.is_symlink():
                archive.write(path, 'media/' + path.relative_to(root).as_posix())


@transaction.atomic
def full_backup(*, actor):
    require(actor, 'backup')
    if connection.vendor == 'postgresql':
        with connection.cursor() as cursor:
            cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
    from accounts.models import User, EbayAccount
    from core.models import Settings
    from orders.models import Order
    from payments.models import Payment, PaymentAllocation
    from documents.models import Invoice
    from imports.models import ImportBatch
    sheets = []
    records = {}
    for model in (EbayAccount, Settings, User, Order, Payment, PaymentAllocation, Invoice, AuditLog, ImportBatch):
        fields = [field for field in model._meta.fields if field.name not in ('password', 'source')]
        rows = []
        records[model._meta.label] = []
        for record in model._base_manager.all().iterator():
            row = []
            for field in fields:
                value = field.value_from_object(record)
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, default=str)
                elif isinstance(value, datetime):
                    value = value.isoformat()
                elif value is not None and not isinstance(value, (str, int, bool)) and field.get_internal_type() not in ('DecimalField', 'DateField'):
                    value = str(value)
                row.append(value)
            records[model._meta.label].append(dict(zip([field.name for field in fields], row)))
            rows.append([value if not isinstance(value, str) or len(value) <= 32000 else '[Full value in records.json]' for value in row])
        sheets.append((model._meta.label, [field.name for field in fields], rows, None))
    sheets.append(('Account access', ['User ID', 'Account ID'], list(User.ebay_accounts.through.objects.values_list('user_id', 'ebayaccount_id')), None))
    output = BytesIO()
    with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
        archive.writestr('data.xlsx', workbook_bytes(sheets))
        archive.writestr('records.json', json.dumps(records, default=str))
        for batch in ImportBatch.objects.all():
            archive.writestr(f'imports/{batch.pk}.xlsx', bytes(batch.source))
        archive.writestr('README.txt', 'Business-data export and retained photos. Password hashes are excluded. Original import workbooks are in imports/. Long spreadsheet values are preserved in records.json. Use the nightly database backup for a full restore.\n')
        add_media(archive)
    AuditLog.objects.create(actor=actor, action='backup_download', object_type='system.Backup', object_id='full', after={'format': 'xlsx+photos'})
    return output.getvalue()


def backup_database(directory=None):
    root = Path(directory or settings.BACKUP_ROOT)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    now = datetime.now(timezone.utc)
    filename = root / f'oms_backup_{now:%Y%m%dT%H%M%S%fZ}.zip'
    db = connection.settings_dict
    with tempfile.TemporaryDirectory(prefix='oms-backup-') as temporary:
        source = Path(temporary) / ('database.sqlite3' if connection.vendor == 'sqlite' else 'database.dump')
        if connection.vendor == 'sqlite':
            connection.ensure_connection()
            target = sqlite3.connect(source)
            try:
                connection.connection.backup(target)
            finally:
                target.close()
        elif connection.vendor == 'postgresql':
            env = os.environ.copy()
            env['PGPASSWORD'] = db.get('PASSWORD', '')
            command = ['pg_dump', '--format=custom', '--file', str(source), '--dbname', db['NAME']]
            for key, option in [('USER', '--username'), ('HOST', '--host'), ('PORT', '--port')]:
                if db.get(key):
                    command.extend([option, str(db[key])])
            subprocess.run(command, env=env, check=True, capture_output=True)
        else:
            raise ValidationError('Database backup supports SQLite and PostgreSQL only.')
        temporary_zip = filename.with_suffix('.partial')
        try:
            with ZipFile(temporary_zip, 'w', ZIP_DEFLATED) as archive:
                archive.write(source, source.name)
                archive.writestr('metadata.json', json.dumps({'created_at': now.isoformat(), 'database_vendor': connection.vendor}))
                add_media(archive)
            os.chmod(temporary_zip, 0o600)
            temporary_zip.replace(filename)
        finally:
            temporary_zip.unlink(missing_ok=True)
    cutoff = now - timedelta(days=30)
    for old in root.glob('oms_backup_*.zip'):
        if datetime.fromtimestamp(old.stat().st_mtime, timezone.utc) < cutoff:
            old.unlink()
    with transaction.atomic():
        AuditLog.objects.create(action='backup', object_type='system.Backup', object_id=filename.name,
            after={'filename': filename.name, 'bytes': filename.stat().st_size})
    return filename
