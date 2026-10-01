from accounts.models import EbayAccount


def account_context(request):
    if not request.user.is_authenticated:
        return {}
    accounts = list(EbayAccount.objects.for_user(request.user).order_by('display_name'))
    selected = next((account for account in accounts if account.pk == request.session.get('account_id')), None)
    if selected is None and 'account_id' in request.session:
        del request.session['account_id']
    from core.models import Settings
    direction = Settings.objects.filter(pk=1).values_list('payment_direction', flat=True).first() or 'paid_out'
    return {'received_label': 'Paid out' if direction == 'paid_out' else 'Received', 'payment_direction': direction, 'accessible_accounts': accounts, 'current_account': selected, 'is_owner': request.user.role == 'Owner'}
