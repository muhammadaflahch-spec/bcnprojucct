"""Check a local Parkwise install and explain anything that is misconfigured.

    python manage.py doctor

Verifies settings, migrations, seed data and — most importantly — that every
static file (CSS, JS, fonts) really is reachable over HTTP.
"""
import os
import urllib.error
import urllib.request
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from parking.models import Lot, ParkingSlot, Place

STATIC_FILES = [
    'parking/css/styles.css',
    'parking/js/app.js',
    'parking/fonts/dm-sans.ttf',
    'parking/fonts/plus-jakarta-sans.ttf',
]


class Command(BaseCommand):
    help = 'Diagnose a local Parkwise setup (settings, database, static files, seeding).'

    def add_arguments(self, parser):
        parser.add_argument('--url', default='http://127.0.0.1:8000',
                            help='Running server to test static files against (default http://127.0.0.1:8000)')

    def handle(self, *args, **options):
        problems = []
        notes = []

        # ---------------------------------------------------------- settings
        self.stdout.write(self.style.MIGRATE_HEADING('1. Settings'))
        self.stdout.write(f'   DEBUG              : {settings.DEBUG}')
        self.stdout.write(f'   DEMO_MODE          : {settings.DEMO_MODE}')
        self.stdout.write(f'   STATIC_URL         : {settings.STATIC_URL}')
        self.stdout.write(f'   STATIC_VERSION     : {getattr(settings, "STATIC_VERSION", "-")}')
        self.stdout.write(f'   PREVIEW_MODE       : {os.environ.get("PREVIEW_MODE", "0")}')
        self.stdout.write(f'   Serve static via Django: '
                          f'{os.environ.get("PARKWISE_SERVE_STATIC", "0" if settings.DEBUG else "1 (fallback)")}')

        # ---------------------------------------------------------- static files
        self.stdout.write(self.style.MIGRATE_HEADING('2. Static files on disk'))
        static_dir = Path(settings.BASE_DIR) / 'static'
        if not static_dir.is_dir():
            problems.append(f'The static folder is missing: {static_dir}')
        for relative in STATIC_FILES:
            path = static_dir / relative
            if path.is_file() and path.stat().st_size > 0:
                self.stdout.write(f'   ok   {relative} ({path.stat().st_size:,} bytes)')
            else:
                problems.append(f'Missing or empty static file: {path}')

        # ---------------------------------------------------------- database
        self.stdout.write(self.style.MIGRATE_HEADING('3. Database'))
        self.stdout.write(f'   Engine             : {settings.DATABASES["default"]["ENGINE"]}')
        self.stdout.write(f'   File               : {settings.DATABASES["default"]["NAME"]}')
        try:
            pending = MigrationExecutor(connection).migration_plan(
                MigrationExecutor(connection).loader.graph.leaf_nodes())
        except Exception as exc:  # noqa: BLE001 - report any failure plainly
            pending = None
            problems.append(f'Cannot inspect migrations: {exc}')
        if pending:
            problems.append(f'{len(pending)} migration(s) are not applied — run: python manage.py migrate')
        elif pending is not None:
            self.stdout.write('   ok   all migrations applied')
        try:
            places = Place.objects.count()
            lots = Lot.objects.count()
            slots = ParkingSlot.objects.count()
            self.stdout.write(f'   Data               : {places} places, {lots} lots, {slots} slots')
            if places == 0:
                problems.append('No places in the database — run: python manage.py seed_demo')
        except Exception as exc:  # noqa: BLE001
            problems.append(f'Database tables are not ready ({exc.__class__.__name__}). '
                            'Run: python manage.py migrate && python manage.py seed_demo')

        # ---------------------------------------------------------- over HTTP
        self.stdout.write(self.style.MIGRATE_HEADING('4. Serving over HTTP'))
        base = options['url'].rstrip('/')
        for relative in STATIC_FILES:
            url = f'{base}{settings.STATIC_URL}{relative}'
            try:
                with urllib.request.urlopen(url, timeout=5) as response:
                    length = len(response.read())
                if length > 0:
                    self.stdout.write(f'   ok   {response.status} {url}')
                else:
                    problems.append(f'{url} returned an empty body')
            except urllib.error.HTTPError as exc:
                problems.append(f'{url} -> HTTP {exc.code}. '
                                'Static files are not being served (set DEBUG=1, or keep '
                                'PARKWISE_SERVE_STATIC=1, or run: python manage.py runserver --insecure)')
            except Exception as exc:  # noqa: BLE001 - server probably not running
                notes.append(f'Could not reach {base} ({exc.__class__.__name__}). '
                             'Start the server first: python manage.py runserver')
                break

        # ---------------------------------------------------------- summary
        self.stdout.write('')
        if notes:
            for note in notes:
                self.stdout.write(self.style.WARNING('note   ' + note))
        if problems:
            self.stdout.write(self.style.ERROR(f'{len(problems)} problem(s) found:'))
            for index, problem in enumerate(problems, 1):
                self.stdout.write(self.style.ERROR(f'  {index}. {problem}'))
            self.stdout.write('')
            self.stdout.write('Most local "CSS does not load" reports are fixed by one of:')
            self.stdout.write('  • do not set DJANGO_DEBUG=0 while developing (leave it unset)')
            self.stdout.write('  • python manage.py runserver --insecure   (if you must use DEBUG=0)')
            self.stdout.write('  • hard-refresh the browser once after updating CSS/JS (Ctrl/Cmd+Shift+R)')
        else:
            self.stdout.write(self.style.SUCCESS('All checks passed — Parkwise looks healthy.'))
