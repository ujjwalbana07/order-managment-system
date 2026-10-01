from django.urls import path
from accounts import views
from orders import views as orders
from payments import views as payments
from documents import views as documents
from imports import views as imports
from core import views as core
from audit import views as audit

handler404 = core.not_found
handler500 = core.server_error

urlpatterns = [
    path('healthz', core.healthz, name='healthz'),
    path('manage/backups/', core.backups, name='backups'),
    path('manage/audit/', audit.audit_list, name='audit_log'),
    path('imports/', imports.upload, name='import_upload'),
    path('manage/import-diagnostics/', imports.diagnostics, name='import_diagnostics'),
    path('imports/<uuid:pk>/', imports.review, name='import_preview'),
    path('orders/<int:pk>/invoice/', documents.issue, name='issue_invoice'),
    path('invoices/<int:pk>/download/', documents.invoice_download, name='invoice_download'),
    path('payments/<int:pk>/receipt/', documents.receipt_download, name='receipt_download'),
    path('reports/', documents.reports, name='reports'),
    path('reports/<str:kind>.<str:fmt>', documents.export, name='export'),
    path('manage/settings/', documents.company_settings, name='company_settings'),
    path('orders/<int:pk>/payments/new/', payments.record_payment, name='record_payment'),
    path('orders/<int:pk>/payments/split/', payments.split_payment, name='split_payment'),
    path('payments/<int:pk>/void/', payments.void, name='void_payment'),
    path('orders/', orders.order_list, name='order_list'),
    path('orders/new/', orders.order_edit, name='order_create'),
    path('orders/account-defaults/<int:pk>/', orders.account_defaults, name='account_defaults'),
    path('orders/preview/', orders.costing_preview, name='costing_preview'),
    path('orders/deleted/', orders.deleted_orders, name='deleted_orders'),
    path('orders/bulk-delete/', orders.bulk_delete, name='order_bulk_delete'),
    path('orders/<int:pk>/', orders.order_detail, name='order_detail'),
    path('orders/<int:pk>/edit/', orders.order_edit, name='order_edit'),
    path('orders/<int:pk>/delete/', orders.order_delete, name='order_delete'),
    path('orders/<int:pk>/restore/', orders.order_delete, {'restore': True}, name='order_restore'),
    path('orders/<int:pk>/photo/', orders.order_photo, name='order_photo'),
    path('orders/<int:pk>/thumbnail/', orders.order_photo, {'thumb': True}, name='order_thumbnail'),
    path('orders/<int:pk>/photo/2/', orders.order_photo, {'second': True}, name='order_photo2'),
    path('orders/<int:pk>/thumbnail/2/', orders.order_photo, {'thumb': True, 'second': True}, name='order_thumbnail2'),
    path('', views.dashboard, name='dashboard'),
    path('login/', views.SignInView.as_view(), name='login'),
    path('logout/', views.SignOutView.as_view(), name='logout'),
    path('switch-account/', views.switch_account, name='switch_account'),
    path('manage/accounts/', views.account_list, name='account_list'),
    path('manage/accounts/new/', views.account_edit, name='account_create'),
    path('manage/accounts/<int:pk>/', views.account_edit, name='account_edit'),
    path('manage/users/', views.user_list, name='user_list'),
    path('manage/users/new/', views.user_edit, name='user_create'),
    path('manage/users/<int:pk>/', views.user_edit, name='user_edit'),
    path('manage/users/<int:pk>/password/', views.user_password, name='user_password'),
]
