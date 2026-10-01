from django.contrib.auth.models import AbstractUser, UserManager as DjangoUserManager
from django.db import transaction
from django.db.models.functions import Lower
from accounts.access import AccountScopeMixin
from core.model_utils import RetainedQuerySet
from django.db import models
from core.model_utils import RetainedModel, money, nonnegative_constraints


class UserManager(DjangoUserManager):
    @transaction.atomic
    def _create_user(self, username, email, password, **extra_fields):
        import uuid
        from audit.models import AuditLog
        if not email or not email.strip():
            raise ValueError('An email address is required.')
        email = email.strip().lower()
        user = super()._create_user(username or uuid.uuid4().hex, email, password, **extra_fields)
        AuditLog.objects.create(actor=user, action='create', object_type='accounts.User',
            object_id=str(user.pk), after={'email': user.email, 'role': user.role})
        return user

    def create_user(self, username=None, email=None, password=None, **extra_fields):
        return super().create_user(username, email, password, **extra_fields)

    def create_superuser(self, username=None, email=None, password=None, **extra_fields):
        extra_fields['role'] = 'Owner'
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    class Role(models.TextChoices):
        OWNER = 'Owner', 'Owner'
        ACCOUNTS = 'Accounts', 'Accounts'
        STAFF = 'Staff', 'Staff'

    email = models.EmailField(unique=True)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.STAFF)
    ebay_accounts = models.ManyToManyField('EbayAccount', blank=True, related_name='assigned_users')
    failed_login_attempts = models.PositiveSmallIntegerField(default=0, editable=False)
    locked_until = models.DateTimeField(null=True, blank=True, editable=False)
    objects = UserManager()
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    class Meta:
        constraints = [models.UniqueConstraint(Lower('email'), name='user_email_case_unique'),
            models.CheckConstraint(condition=models.Q(role__in=['Owner', 'Accounts', 'Staff']), name='user_role_valid')]

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()
        return super().save(*args, **kwargs)


class EbayAccountQuerySet(AccountScopeMixin, RetainedQuerySet):
    account_path = 'pk'


class EbayAccount(RetainedModel):
    objects = EbayAccountQuerySet.as_manager()
    code = models.CharField(max_length=32, unique=True)
    display_name = models.CharField(max_length=255)
    ebay_username = models.CharField(max_length=255, unique=True)
    active = models.BooleanField(default=True)
    billing_name = models.CharField(max_length=255)
    billing_address = models.TextField()
    phone = models.CharField(max_length=50)
    email = models.EmailField()
    tax_id = models.CharField(max_length=100, blank=True)
    default_gold_rate = money(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        constraints = nonnegative_constraints("account", ["default_gold_rate"])

    def __str__(self):
        return f"{self.code} - {self.display_name}"
