from django.contrib.auth.decorators import login_required
from django.db import connection, DatabaseError
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from accounts.access import require
from audit.models import AuditLog
from core.backups import full_backup
from documents.views import download


def healthz(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
    except DatabaseError:
        return HttpResponse('Unavailable', status=503, content_type='text/plain')
    return HttpResponse('OK', content_type='text/plain')


@login_required
def backups(request):
    require(request.user, 'backup')
    if request.method == 'POST':
        return download(full_backup(actor=request.user), f'full_backup_{timezone.localdate():%Y%m%d}.zip', 'application/zip')
    return render(request, 'core/backups.html', {'recent': AuditLog.objects.filter(action='backup').order_by('-timestamp')[:10]})


def not_found(request, exception):
    return render(request, '404.html', status=404)


def server_error(request):
    # No database-backed context processors: this page also works during DB outages.
    from django.template.loader import get_template
    return HttpResponse(get_template('500.html').render({'request_id': getattr(request, 'request_id', '')}), status=500)
