from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from accounts.access import require, can
from accounts.models import EbayAccount
from core.models import default_gold_rate
from core.services import save_record
from core.transactions import retry_locked
from orders.models import Order
from orders.images import prepare_image

INPUT_FIELDS = ('account', 'sales_no', 'challan_no', 'mfg_order_no', 'order_date', 'ship_by_date',
    'buyer_username', 'item_title', 'quantity', 'igi_cert_no', 'tracking_no', 'fulfilment_status',
    'payment_status_override', 'usd_sold', 'fx_rate', 'inr_sold', 'ship_charges', 'platform_fees_inr', 'purity', 'gross_wt',
    'dia_ct', 'other_wt', 'gold_rate', 'lab_rate', 'diamond_value')


@retry_locked
@transaction.atomic
def save_order(*, actor, data, order_id=None, version=None, image=None, image2=None):
    require(actor, 'edit_order' if order_id else 'create_order')
    if set(data) - set(INPUT_FIELDS):
        raise ValidationError('Some submitted fields cannot be changed here.')
    order = get_object_or_404(Order.objects.for_user(actor).select_for_update(), pk=order_id) if order_id else Order(created_by=actor)
    if order_id and version != order.version:
        raise ValidationError('Someone else just changed this order. Your changes were not saved. Reload to see theirs.')
    account = data.get('account', order.account if order_id else None)
    if account is None or not EbayAccount.objects.for_user(actor).filter(pk=account.pk).exists():
        raise ValidationError('Select an account you have access to.')
    if not account.active and (not order_id or account.pk != order.account_id):
        raise ValidationError('This account is inactive. Select an active account.')
    if not can(actor, 'edit_rates'):
        gold = order.gold_rate if order_id else account.default_gold_rate if account.default_gold_rate is not None else default_gold_rate()
        labour = order.lab_rate if order_id else Decimal('0')
        if data.get('gold_rate', gold) != gold or data.get('lab_rate', labour) != labour:
            raise ValidationError('Ask Accounts or an Owner to change rates.')
        data = {**data, 'gold_rate': gold, 'lab_rate': labour}
    for field, value in data.items():
        setattr(order, field, value)
    order.updated_by = actor
    order.full_clean()
    stored = []
    try:
        for upload, image_field, thumb_field in ((image, order.image, order.thumbnail), (image2, order.image2, order.thumbnail2)):
            if upload:
                photo, thumb = prepare_image(upload)
                photo_bytes = photo.read()
                thumb_bytes = thumb.read()
                photo.seek(0)
                thumb.seek(0)
                image_field.save(photo.name, photo, save=False)
                stored.append((image_field.storage, image_field.name))
                thumb_field.save(thumb.name, thumb, save=False)
                stored.append((thumb_field.storage, thumb_field.name))
                if image_field.field.name == 'image':
                    order.image_data = photo_bytes
                    order.thumbnail_data = thumb_bytes
                else:
                    order.image2_data = photo_bytes
                    order.thumbnail2_data = thumb_bytes
        return save_record(order, actor=actor)
    except Exception:
        for storage, name in stored:
            storage.delete(name)
        raise


@retry_locked
@transaction.atomic
def set_deleted(*, actor, order_id, version, deleted, reason='', confirmation=''):
    require(actor, 'delete_order')
    order = get_object_or_404(Order.all_objects.for_user(actor).select_for_update(), pk=order_id)
    if order.version != version:
        raise ValidationError('Someone else just changed this order. Reload and try again.')
    if deleted and (confirmation != 'DELETE' or not reason.strip()):
        raise ValidationError('Type DELETE and enter a reason to delete this order.')
    order.is_deleted = deleted
    order.deleted_by = actor if deleted else None
    order.deleted_at = timezone.now() if deleted else None
    order.delete_reason = reason.strip() if deleted else ''
    order.updated_by = actor
    return save_record(order, actor=actor, note=reason.strip())


def order_warnings(order):
    warnings = []
    if not order.dia_ct and order.diamond_value:
        warnings.append('Diamond value is entered but diamond weight is zero. Please check both values.')
    if order.dia_ct and not order.diamond_value:
        warnings.append('Diamond weight is entered but diamond value is zero. Please check both values.')
    if order.net_earnings < 0:
        warnings.append('Net earnings are negative. Please check the sale price and costs.')
    default = default_gold_rate()
    if abs(order.gold_rate - default) > default * Decimal('0.10'):
        warnings.append('Gold rate differs from the company default by more than 10 percent.')
    return warnings
