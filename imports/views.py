from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, render, redirect
from accounts.access import require
from accounts.models import EbayAccount
from accounts.views import form_error
from imports.models import ImportBatch
from imports.services import create_batch, preview, commit_batch


class ImportForm(forms.Form):
    account = forms.ModelChoiceField(queryset=EbayAccount.objects.none())
    file = forms.FileField(label='Excel workbook (.xlsx)')

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['account'].queryset = EbayAccount.objects.for_user(actor).filter(active=True)


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
    require(request.user, 'import')
    batch = get_object_or_404(ImportBatch.objects, pk=pk, actor=request.user, account__in=EbayAccount.objects.for_user(request.user))
    if request.method == 'POST':
        try:
            count = commit_batch(actor=request.user, batch_id=pk)
        except ValidationError as exc:
            messages.error(request, exc.messages[0])
        else:
            messages.success(request, f'Import complete. {count} orders created.')
            return redirect('order_list')
    try:
        result = preview(bytes(batch.source), account=batch.account, actor=request.user, gold_rate=batch.gold_rate)
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
        return redirect('import_upload')
    return render(request, 'imports/preview.html', {'batch': batch, **result})
