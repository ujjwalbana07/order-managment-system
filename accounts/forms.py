from django import forms
from django.contrib.auth.forms import AuthenticationForm
from accounts.models import User, EbayAccount


class EmailLoginForm(AuthenticationForm):
    username = forms.EmailField(label='Email', widget=forms.EmailInput(attrs={'autocomplete': 'username', 'autofocus': True}))
    error_messages = {'invalid_login': 'Unable to sign in. Check your email and password. After five failed attempts, wait 15 minutes before trying again.',
                      'inactive': 'Unable to sign in. Ask an Owner for help.'}


class AccountForm(forms.ModelForm):
    class Meta:
        model = EbayAccount
        fields = ['code', 'display_name', 'ebay_username', 'active', 'billing_name', 'billing_address',
                  'phone', 'email', 'tax_id', 'default_gold_rate', 'notes']
        widgets = {'billing_address': forms.Textarea(attrs={'rows': 3}), 'notes': forms.Textarea(attrs={'rows': 3})}


class UserForm(forms.ModelForm):
    password = forms.CharField(label='Initial password', required=False, strip=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}))

    class Meta:
        model = User
        fields = ['email', 'first_name', 'last_name', 'role', 'is_active', 'ebay_accounts']
        widgets = {'ebay_accounts': forms.CheckboxSelectMultiple}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['ebay_accounts'].queryset = EbayAccount.objects.order_by('display_name')
        if self.instance.pk:
            self.fields.pop('password')
        else:
            self.fields['password'].required = True

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('A user already has this email. Use another email address.')
        return email

    def clean(self):
        data = super().clean()
        if data.get('role') != 'Owner' and not data.get('ebay_accounts'):
            self.add_error('ebay_accounts', 'Assign at least one eBay account.')
        return data


class ResetPasswordForm(forms.Form):
    password = forms.CharField(label='New password', strip=False, widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}))
    confirm_password = forms.CharField(label='Confirm password', strip=False, widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}))

    def clean(self):
        data = super().clean()
        if data.get('password') != data.get('confirm_password'):
            self.add_error('confirm_password', 'The passwords do not match. Enter them again.')
        return data
