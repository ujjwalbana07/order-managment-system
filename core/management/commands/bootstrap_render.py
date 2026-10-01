import os

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = "Optionally create/update an Owner and seed demo data during Render deploys."

    def handle(self, *args, **options):
        email = os.environ.get("BOOTSTRAP_OWNER_EMAIL", "").strip().lower()
        password = os.environ.get("BOOTSTRAP_OWNER_PASSWORD", "")
        seed_demo = os.environ.get("BOOTSTRAP_SEED_DEMO", "").strip().lower() in {"1", "true", "yes", "on"}
        account = os.environ.get("BOOTSTRAP_DEMO_ACCOUNT", "ALK01").strip() or "ALK01"

        if not email and not seed_demo:
            self.stdout.write("No bootstrap env vars set; skipping.")
            return
        if seed_demo and not email:
            raise CommandError("BOOTSTRAP_OWNER_EMAIL is required when BOOTSTRAP_SEED_DEMO=true.")

        if email:
            user = self._ensure_owner(email, password)
            self.stdout.write(self.style.SUCCESS(f"Owner ready: {user.email}"))

        if seed_demo:
            call_command("seed_demo", owner=email, account=account)

    @transaction.atomic
    def _ensure_owner(self, email, password):
        User = get_user_model()
        user = User.objects.filter(email__iexact=email).first()
        created = user is None
        if created:
            if not password:
                raise CommandError("BOOTSTRAP_OWNER_PASSWORD is required to create a new Owner.")
            user = User(email=email, role="Owner", is_staff=True, is_superuser=True, is_active=True)
        else:
            user.role = "Owner"
            user.is_staff = True
            user.is_superuser = True
            user.is_active = True
        if password:
            user.set_password(password)
            user.failed_login_attempts = 0
            user.locked_until = None
        user.save()
        return user
