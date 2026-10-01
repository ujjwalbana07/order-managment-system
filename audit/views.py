from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render
from django.utils.dateparse import parse_date
from accounts.access import require
from audit.models import AuditLog


@login_required
def audit_list(request):
    require(request.user, 'view_audit')
    logs = AuditLog.objects.for_user(request.user).select_related('actor', 'account').order_by('-timestamp', '-pk')
    for param, field in [('actor', 'actor__email__icontains'), ('account', 'account_id'), ('action', 'action__icontains'),
                         ('object_type', 'object_type__icontains'), ('object_id', 'object_id')]:
        value = request.GET.get(param, '').strip()
        if value:
            if param == 'account' and not value.isdigit():
                logs = logs.none()
            else:
                logs = logs.filter(**{field: value})
    for param, field in [('from', 'timestamp__date__gte'), ('to', 'timestamp__date__lte')]:
        if request.GET.get(param):
            try:
                date = parse_date(request.GET[param])
            except ValueError:
                date = None
            logs = logs.filter(**{field: date}) if date else logs.none()
    params = request.GET.copy()
    params.pop('page', None)
    return render(request, 'audit/list.html', {'page': Paginator(logs, 50).get_page(request.GET.get('page')), 'query': params.urlencode()})
