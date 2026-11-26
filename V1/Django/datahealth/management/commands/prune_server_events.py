"""
Delete the oldest entries of the server event log.

    python manage.py prune_server_events              entries older than 180 days
    python manage.py prune_server_events --days 365
    python manage.py prune_server_events --dry-run    only say how many

The log grows with use (every sign-in, export and change), and nothing removes
entries by itself. Run this now and then, or from a timer. It never touches the
audit log, which is the record of changes to the data and is kept for good.
"""

import datetime

from django.core.management.base import BaseCommand, CommandError

from datahealth import events
from datahealth.models import ServerEvent, utcnow


class Command(BaseCommand):
    help = "Delete server event log entries older than a number of days."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=180)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, days, dry_run, **options):
        if days < 1:
            raise CommandError("--days must be at least 1.")
        if dry_run:
            cutoff = utcnow() - datetime.timedelta(days=days)
            count = ServerEvent.objects.filter(occurred_at__lt=cutoff).count()
            self.stdout.write(f"{count:,} entries are older than {days} days. Nothing was deleted.")
            return
        self.stdout.write(f"Deleted {events.prune(days):,} entries older than {days} days.")
