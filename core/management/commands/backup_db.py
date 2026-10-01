from django.core.management.base import BaseCommand, CommandError
from core.backups import backup_database


class Command(BaseCommand):
    help = 'Create a consistent database backup and copy retained photos; keep 30 days.'

    def add_arguments(self, parser):
        parser.add_argument('--directory')

    def handle(self, *args, **options):
        try:
            result = backup_database(options['directory'])
        except Exception as exc:
            raise CommandError('Backup failed. Check directory permissions and database backup tools.') from exc
        self.stdout.write(self.style.SUCCESS(str(result)))
