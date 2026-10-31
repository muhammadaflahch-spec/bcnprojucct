from django.contrib.auth.models import User
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Disable all known demo accounts and remove staff privileges; retain booking history.'

    def handle(self, *args, **options):
        users = User.objects.filter(email__endswith='@parkwise.demo')
        count = 0
        for user in users:
            user.is_active = False
            user.is_staff = False
            user.is_superuser = False
            user.set_unusable_password()
            user.save()
            count += 1
        self.stdout.write(self.style.SUCCESS(f'Retired {count} demo accounts. Also set PARKWISE_DEMO_MODE=0 before restarting.'))
