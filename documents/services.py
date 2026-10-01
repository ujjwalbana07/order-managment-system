import base64
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from accounts.access import require
from audit.models import AuditLog
from core.costing import gst_amount
from core.models import Settings
from core.transactions import retry_locked
from documents.models import Invoice, DocumentSequence
from orders.models import Order
from payments.services import balances


def bill_snapshot(order, issuer, balance):
    account = order.account
    result = {
        'issuer': {name: getattr(issuer, name) for name in ('company_name', 'address', 'phone', 'email', 'tax_id', 'invoice_footer_text')},
        'bill_to': {name: getattr(account, name) for name in ('billing_name', 'billing_address', 'phone', 'email', 'tax_id')},
        'order': {'serial_no': order.serial_no, 'sales_no': order.sales_no, 'challan_no': order.challan_no,
            'mfg_order_no': order.mfg_order_no, 'item_title': order.item_title, 'quantity': order.quantity,
            'order_date': order.order_date.isoformat(), 'version': order.version},
        'lines': [{'component': 'Gold', 'weight': str(order.pure_995), 'rate': str(order.gold_rate), 'amount': str(order.gold_amount)},
                  {'component': 'Diamond', 'weight': str(order.dia_ct), 'rate': '', 'amount': str(order.diamond_value)},
                  {'component': 'Labour', 'weight': str(order.net_wt), 'rate': str(order.lab_rate), 'amount': str(order.labour_amount)}],
        'totals': {key: str(balance[key]) for key in ('total_bill', 'total_received', 'total_outstanding')},
        'payment_direction': issuer.payment_direction,
        'gst_rate_percent': str(issuer.gst_rate_percent if issuer.gst_enabled else 0),
        'gst_amount': str(gst_amount(order.total_bill, issuer.gst_rate_percent) if issuer.gst_enabled else 0),
    }
    for key, file in [('photo', order.thumbnail), ('logo', issuer.logo)]:
        if file:
            with file.open('rb') as stream:
                result[key] = base64.b64encode(stream.read()).decode('ascii')
    return result


@retry_locked
@transaction.atomic
def issue_invoice(*, actor, order_id):
    require(actor, 'issue_documents')
    order = get_object_or_404(Order.objects.for_user(actor).select_for_update().select_related('account'), pk=order_id)
    issuer = Settings.objects.filter(pk=1).first()
    if issuer is None:
        raise ValidationError('Ask an Owner to complete company settings before issuing an invoice.')
    year = timezone.localdate().year
    sequence, _ = DocumentSequence.objects.get_or_create(key=f'invoice-{year}')
    sequence = DocumentSequence.objects.select_for_update().get(pk=sequence.pk)
    sequence.value += 1
    sequence.save(update_fields=['value'])
    number = f'INV-{year}-{sequence.value:05d}'
    snapshot = bill_snapshot(order, issuer, balances(order))
    snapshot.update(invoice_no=number, issued_at=timezone.localtime().isoformat(), issued_by=actor.email)
    invoice = Invoice(order=order, issued_by=actor, invoice_no=number, snapshot=snapshot)
    invoice.save()
    superseded = []
    for previous in order.invoices.filter(status='Issued').exclude(pk=invoice.pk):
        previous.status = 'Superseded'
        previous.save()
        superseded.append(previous.invoice_no)
    AuditLog.objects.create(actor=actor, action='issue', object_type='documents.Invoice', object_id=str(invoice.pk),
        account=order.account, after={'invoice_no': number, 'snapshot': snapshot, 'supersedes': superseded})
    return invoice
