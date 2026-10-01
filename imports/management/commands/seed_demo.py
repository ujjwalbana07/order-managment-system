import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from accounts.models import User, EbayAccount
from accounts.services import save_account
from orders.models import Order
from orders.services import save_order


class Command(BaseCommand):
    help = 'Load the six supplied real demo rows and photos into a selected account.'

    def add_arguments(self, parser):
        parser.add_argument('--owner', required=True, help='Existing active Owner email')
        parser.add_argument('--account', default='ALK01')

    @transaction.atomic
    def handle(self, *args, **options):
        actor = User.objects.filter(email__iexact=options['owner'], role='Owner', is_active=True).first()
        if actor is None:
            raise CommandError('Create an Owner first and pass their email with --owner.')
        account = EbayAccount.objects.filter(code=options['account']).first()
        if account is None:
            account = save_account(actor=actor, data={'code': options['account'], 'display_name': 'AlkanZa demo',
                'ebay_username': f"demo-{options['account']}", 'billing_name': 'AlkanZa demo',
                'billing_address': 'Demo address', 'phone': 'Not entered', 'email': 'demo@example.com'})
        root = settings.BASE_DIR / 'oms-pack/seed'
        rows = json.loads((root / 'seed_rows.json').read_text())
        created = []
        try:
            for row in rows:
                if Order.all_objects.filter(account=account, sales_no=row['sales_no']).exists():
                    continue
                data = {'account': account, 'sales_no': row['sales_no'], 'order_date': date.fromisoformat(row['order_date']),
                    'ship_by_date': date.fromisoformat(row['ship_by']), 'buyer_username': row['buyer'], 'item_title': row['title'],
                    'quantity': row['qty'], 'tracking_no': row['tracking'], 'fx_rate': Decimal(row['implied_fx'])}
                for key in ('usd_sold', 'inr_sold', 'purity', 'gross_wt', 'dia_ct', 'other_wt', 'gold_rate', 'lab_rate', 'diamond_value', 'ship_charges'):
                    data[key] = Decimal(row[key])
                image = SimpleUploadedFile(Path(row['image']).name, (root / row['image']).read_bytes())
                created.append(save_order(actor=actor, data=data, image=image))
        except Exception:
            for order in created:
                for image in (order.image, order.thumbnail):
                    if image:
                        image.storage.delete(image.name)
            raise
        self.stdout.write(self.style.SUCCESS(f'Created {len(created)} orders. Existing sales numbers were skipped.'))
