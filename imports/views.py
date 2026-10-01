import logging
import traceback

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render, redirect
from accounts.access import require
from accounts.models import EbayAccount
from accounts.views import form_error
from imports.models import ImportBatch
from imports.services import create_batch, preview, commit_batch
from orders.models import Order

logger = logging.getLogger(__name__)


class ImportForm(forms.Form):
    account = forms.ModelChoiceField(queryset=EbayAccount.objects.none())
    file = forms.FileField(label='Excel workbook (.xlsx)')

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['account'].queryset = EbayAccount.objects.for_user(actor).filter(active=True)


@login_required
def diagnostics(request, batch_id=None):
    require(request.user, 'view_audit')
    batch_debug = ''
    if batch_id:
        try:
            batch = get_object_or_404(ImportBatch.objects.select_related('account', 'actor'), pk=batch_id, account__in=EbayAccount.objects.for_user(request.user))
            with transaction.atomic():
                count = commit_batch(actor=batch.actor, batch_id=batch_id)
                batch_debug = f'DRY RUN OK: commit would create {count} orders. Transaction rolled back.'
                transaction.set_rollback(True)
        except Exception:
            batch_debug = traceback.format_exc()
    constraints = []
    with connection.cursor() as cursor:
        if connection.vendor == 'postgresql':
            cursor.execute("""
                select conname || ': ' || pg_get_constraintdef(oid)
                from pg_constraint
                where conrelid = 'orders_order'::regclass and conname like 'order%account%sales%'
                order by conname
            """)
            constraints = [row[0] for row in cursor.fetchall()]
        else:
            constraints = [name for name in connection.introspection.get_constraints(cursor, 'orders_order') if 'sales' in name]
        cursor.execute("select count(*) from django_migrations where app = 'orders' and name = '0008_remove_order_order_account_sales_unique_and_more'")
        migration_0008 = cursor.fetchone()[0] > 0
    accounts = []
    for account in EbayAccount.objects.for_user(request.user).order_by('code'):
        rows = Order.all_objects.filter(account=account)
        accounts.append({'account': account, 'active': rows.filter(is_deleted=False).count(),
            'deleted': rows.filter(is_deleted=True).count(), 'total': rows.count()})
    batches = []
    for batch in ImportBatch.objects.filter(account__in=EbayAccount.objects.for_user(request.user)).select_related('account').order_by('-created_at')[:10]:
        try:
            result = preview(bytes(batch.source), account=batch.account, actor=request.user, gold_rate=batch.gold_rate)
            statuses = {}
            for row in result['rows']:
                statuses[row['status']] = statuses.get(row['status'], 0) + 1
            summary = ', '.join(f'{key}: {value}' for key, value in sorted(statuses.items())) or 'No rows'
        except Exception as exc:
            summary = exc.__class__.__name__
        batches.append({**batch.__dict__, 'account': batch.account, 'preview_summary': summary})
    return render(request, 'imports/diagnostics.html', {'vendor': connection.vendor, 'migration_0008': migration_0008,
        'constraints': constraints, 'accounts': accounts, 'batches': batches, 'batch_debug': batch_debug})


@login_required
def upload(request):
    require(request.user, 'import')
    form = ImportForm(request.POST if request.method == 'POST' else None, request.FILES or None, actor=request.user,
        initial={'account': request.session.get('account_id')})
    if request.method == 'POST' and form.is_valid():
        try:
            batch = create_batch(actor=request.user, account=form.cleaned_data['account'], upload=form.cleaned_data['file'])
        except ValidationError as exc:
            form_error(form, exc)
        else:
            return redirect('import_preview', pk=batch.pk)
    return render(request, 'imports/upload.html', {'form': form})


@login_required
def review(request, pk):
    try:
        return _review(request, pk)
    except Http404:
        raise
    except Exception:
        logger.exception('Unhandled import page failure for batch %s', pk)
        if request.user.is_authenticated and request.user.role == 'Owner':
            return HttpResponse('<h1>Import failed</h1><p>Send this debug text to developer:</p><pre>' + traceback.format_exc() + '</pre>', status=500)
        raise


def _review(request, pk):
    require(request.user, 'import')
    batch = get_object_or_404(ImportBatch.objects, pk=pk, actor=request.user, account__in=EbayAccount.objects.for_user(request.user))
    if request.method == 'POST':
        try:
            count = commit_batch(actor=request.user, batch_id=pk)
        except ValidationError as exc:
            messages.error(request, exc.messages[0])
        except (DatabaseError, IntegrityError, OSError) as exc:
            logger.exception('Import commit failed for batch %s', pk)
            messages.error(request, 'Import could not be saved. Wait for the latest deploy to finish, then try again. If this repeats, Render logs will show: ' + exc.__class__.__name__)
        except Exception as exc:
            logger.exception('Unexpected import commit failure for batch %s', pk)
            messages.error(request, 'Import could not be saved. Render logs will show: ' + exc.__class__.__name__)
        else:
            messages.success(request, f'Import complete. {count} orders created.')
            return redirect('order_list')
    try:
        result = preview(bytes(batch.source), account=batch.account, actor=request.user, gold_rate=batch.gold_rate)
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
        return redirect('import_upload')
    except Exception as exc:
        logger.exception('Import preview failed for batch %s', pk)
        messages.error(request, 'Import preview failed. Render logs will show: ' + exc.__class__.__name__)
        return redirect('import_upload')
    return render(request, 'imports/preview.html', {'batch': batch, **result})
