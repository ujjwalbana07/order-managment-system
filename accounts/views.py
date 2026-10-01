from functools import wraps
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from accounts.access import require
from accounts.context_processors import account_context
from accounts.forms import AccountForm, UserForm, ResetPasswordForm, EmailLoginForm
from accounts.models import EbayAccount, User
from accounts.services import save_account, save_user, reset_password


class SignInView(LoginView):
    authentication_form = EmailLoginForm
    template_name = 'accounts/login.html'
    redirect_authenticated_user = True


class SignOutView(LogoutView):
    next_page = 'login'


def owner_required(view):
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        require(request.user, 'manage_users')
        return view(request, *args, **kwargs)
    return wrapped


def form_error(form, error):
    for message in error.messages:
        form.add_error(None, message)


@login_required
def dashboard(request):
    context = account_context(request)
    accounts = EbayAccount.objects.for_user(request.user).order_by('display_name')
    if context['current_account']:
        accounts = accounts.filter(pk=context['current_account'].pk)
    accounts = accounts.annotate(open_orders=Count('orders', filter=Q(orders__is_deleted=False) &
        ~Q(orders__fulfilment_status__in=['Delivered', 'Returned', 'Cancelled'])))
    from documents.reports import account_report
    from orders.models import Order
    financials = account_report(accounts, Order.objects.for_user(request.user).filter(account__in=accounts))
    by_id = {row['account'].pk: row for row in financials}
    for account in accounts:
        account.financials = by_id[account.pk]
    return render(request, 'accounts/dashboard.html', {'rows': accounts})


@login_required
@require_POST
def switch_account(request):
    value = request.POST.get('account_id', '')
    if value == 'all':
        request.session.pop('account_id', None)
    else:
        try:
            account_id = int(value)
        except (TypeError, ValueError):
            raise Http404('Account not found.')
        account = get_object_or_404(EbayAccount.objects.for_user(request.user), pk=account_id)
        request.session['account_id'] = account.pk
    return redirect('dashboard')


@owner_required
def account_list(request):
    return render(request, 'accounts/account_list.html', {'rows': EbayAccount.objects.for_user(request.user).order_by('display_name')})


@owner_required
def account_edit(request, pk=None):
    account = get_object_or_404(EbayAccount.objects.for_user(request.user), pk=pk) if pk else None
    form = AccountForm(request.POST if request.method == 'POST' else None, instance=account)
    if request.method == 'POST' and form.is_valid():
        try:
            save_account(actor=request.user, data=form.cleaned_data, account_id=pk)
        except ValidationError as exc:
            form_error(form, exc)
        except IntegrityError:
            form.add_error(None, 'Another record already uses these details. Reload and check for duplicates.')
        else:
            messages.success(request, 'Account saved.')
            return redirect('account_list')
    return render(request, 'accounts/form.html', {'form': form, 'title': 'Edit account' if pk else 'Add account', 'cancel_url': 'account_list'})


@owner_required
def user_list(request):
    return render(request, 'accounts/user_list.html', {'rows': User.objects.prefetch_related('ebay_accounts').order_by('email')})


@owner_required
def user_edit(request, pk=None):
    user = get_object_or_404(User, pk=pk) if pk else None
    form = UserForm(request.POST if request.method == 'POST' else None, instance=user)
    if request.method == 'POST' and form.is_valid():
        try:
            save_user(actor=request.user, data=form.cleaned_data, user_id=pk)
        except ValidationError as exc:
            form_error(form, exc)
        except IntegrityError:
            form.add_error(None, 'Another record already uses these details. Reload and check for duplicates.')
        else:
            messages.success(request, 'User and account access saved.')
            return redirect('user_list')
    return render(request, 'accounts/form.html', {'form': form, 'title': 'Edit user' if pk else 'Add user', 'cancel_url': 'user_list'})


@owner_required
def user_password(request, pk):
    user = get_object_or_404(User, pk=pk)
    form = ResetPasswordForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        try:
            updated = reset_password(actor=request.user, user_id=user.pk, password=form.cleaned_data['password'])
        except ValidationError as exc:
            form_error(form, exc)
        except IntegrityError:
            form.add_error(None, 'Another record already uses these details. Reload and check for duplicates.')
        else:
            if updated.pk == request.user.pk:
                update_session_auth_hash(request, updated)
            messages.success(request, 'Password reset. Share the new password with the user securely.')
            return redirect('user_list')
    return render(request, 'accounts/form.html', {'form': form, 'title': f'Reset password for {user.email}', 'cancel_url': 'user_list'})
