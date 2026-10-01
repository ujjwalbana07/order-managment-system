from decimal import Decimal
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpResponse, Http404
from django.shortcuts import get_object_or_404, render, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST
from accounts.access import require, can
from accounts.context_processors import account_context
from accounts.models import EbayAccount
from accounts.views import form_error
from core.models import Settings
from core.services import save_record
from documents.models import Invoice
from documents.services import issue_invoice
from documents.renderers import invoice_pdf, receipt_pdf, workbook_bytes, report_pdf
from documents.reports import order_rows, account_report
from orders.queries import filtered_orders
from orders.models import Order
from payments.models import Payment
from payments.services import balances


def download(content, filename, mime):
    response = HttpResponse(content, content_type=mime)
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response['Cache-Control'] = 'private, no-store'
    return response


@login_required
@require_POST
def issue(request, pk):
    require(request.user, 'issue_documents')
    try:
        invoice = issue_invoice(actor=request.user, order_id=pk)
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
        return redirect('order_detail', pk=pk)
    return redirect('invoice_download', pk=invoice.pk)


@login_required
def invoice_download(request, pk):
    invoice = get_object_or_404(Invoice.objects.for_user(request.user), pk=pk, order__is_deleted=False)
    return download(invoice_pdf(invoice.snapshot), f'{invoice.invoice_no}.pdf', 'application/pdf')


@login_required
def receipt_download(request, pk):
    payment = get_object_or_404(Payment.objects.for_user(request.user).select_related('order__account', 'created_by'), pk=pk, order__is_deleted=False)
    direction = Settings.objects.filter(pk=1).values_list('payment_direction', flat=True).first() or 'paid_out'
    return download(receipt_pdf(payment, balances(payment.order, through=payment), direction), f'{payment.receipt_no}.pdf', 'application/pdf')


@login_required
def reports(request):
    require(request.user, 'view_reports')
    account_context(request)
    try:
        orders = filtered_orders(request.user, request.GET, request.session.get('account_id'))
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
        orders = Order.objects.none()
    accounts = EbayAccount.objects.for_user(request.user)
    selected = request.GET.get('account') or request.session.get('account_id')
    if selected and str(selected).isdigit():
        accounts = accounts.filter(pk=selected)
    return render(request, 'documents/reports.html', {'rows': account_report(accounts, orders), 'can_export': can(request.user, 'export'), 'query': request.GET.urlencode()})


@login_required
def export(request, kind, fmt):
    require(request.user, 'export')
    if kind not in ('orders', 'payments', 'outstanding', 'statement') or fmt not in ('xlsx', 'pdf'):
        raise Http404('Report not found.')
    account_context(request)
    params = request.GET.copy()
    if kind == 'payments':
        params.pop('from', None)
        params.pop('to', None)
    try:
        orders = filtered_orders(request.user, params, request.session.get('account_id'))
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
        return redirect('reports')
    if kind in ('orders', 'statement'):
        headers, rows, totals = order_rows(orders)
        if kind == 'statement':
            indices = [0, 1, 2, 3, 23, len(headers)-3, len(headers)-2]
            headers, rows, totals = [headers[i] for i in indices], [[row[i] for i in indices] for row in rows], [totals[i] for i in indices]
    elif kind == 'payments':
        payments = Payment.objects.for_user(request.user).filter(order__in=orders).select_related('order__account').prefetch_related('allocations').order_by('payment_date', 'created_at')
        from django.utils.dateparse import parse_date
        for name, lookup in [('from', 'payment_date__gte'), ('to', 'payment_date__lte')]:
            if request.GET.get(name):
                try:
                    date = parse_date(request.GET[name])
                except ValueError:
                    date = None
                if date is None:
                    messages.error(request, 'Enter dates in YYYY-MM-DD format.')
                    return redirect('reports')
                payments = payments.filter(**{lookup: date})
        headers = ['Receipt', 'Account', 'Sales no', 'Payment date', 'Method', 'Reference', 'Status', 'Amount', 'Gold', 'Diamond', 'Labour']
        rows = []
        for payment in payments:
            amounts = {row.component: row.amount for row in payment.allocations.all()}
            rows.append([payment.receipt_no, str(payment.order.account), payment.order.sales_no, payment.payment_date,
                payment.method, payment.reference_no, payment.status, payment.amount, *[amounts.get(name, Decimal('0')) for name in ('Gold', 'Diamond', 'Labour')]])
        totals = ['Posted totals'] + ['']*6 + [sum((row[i] for row in rows if row[6] == 'Posted'), Decimal('0')) for i in range(7, 11)]
    else:
        headers = ['Account', 'Open orders', 'Bill', 'Received', 'Outstanding', 'This month earnings']
        summary = account_report(EbayAccount.objects.for_user(request.user).filter(pk__in=orders.values('account_id')), orders)
        rows = [[str(row['account']), row['open_orders'], row['total_bill'], row['total_received'], row['total_outstanding'], row['month_earnings']] for row in summary]
        totals = ['Totals'] + [sum((row[i] for row in rows), Decimal('0')) for i in range(1, 6)]
    direction = Settings.objects.filter(pk=1).values_list('payment_direction', flat=True).first() or 'paid_out'
    if direction == 'paid_out':
        headers = ['Paid out' if header == 'Received' else header for header in headers]
    label = 'ALL'
    selected = request.GET.get('account') or request.session.get('account_id')
    if selected and str(selected).isdigit():
        account = EbayAccount.objects.for_user(request.user).filter(pk=selected).first()
        if account:
            label = ''.join(char for char in account.code if char.isalnum() or char in '_-') or str(account.pk)
    filename = f'{kind}_{label}_{timezone.localdate():%Y%m%d}.{fmt}'
    if fmt == 'xlsx':
        data = workbook_bytes([(kind.title(), headers, rows, totals)])
        mime = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    else:
        data = report_pdf(kind.title(), headers, rows + [totals], request.GET.urlencode() or f'Account {label}', timezone.localtime().strftime('%d-%b-%Y %H:%M %Z'))
        mime = 'application/pdf'
    return download(data, filename, mime)


class SettingsForm(forms.ModelForm):
    def clean_logo(self):
        logo = self.cleaned_data.get('logo')
        from django.core.files.uploadedfile import UploadedFile
        if isinstance(logo, UploadedFile):
            from orders.images import prepare_image
            logo, _ = prepare_image(logo)
        return logo

    class Meta:
        model = Settings
        exclude = ['id']


@login_required
def company_settings(request):
    require(request.user, 'manage_settings')
    instance = Settings.objects.filter(pk=1).first()
    form = SettingsForm(request.POST if request.method == 'POST' else None, request.FILES or None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        try:
            save_record(form.save(commit=False), actor=request.user)
        except ValidationError as exc:
            form_error(form, exc)
        else:
            messages.success(request, 'Company settings saved. Existing order rates are unchanged.')
            return redirect('company_settings')
    return render(request, 'documents/settings.html', {'form': form})
