"""
Add one entry to the server event log from outside the website: the deploy
workflow, a script, an operator at the shell.

    python manage.py log_server_event deploy deployed --actor "GitHub Actions" \
        --message "Deployed abc1234" --detail commit=abc1234 --detail run=1234 \
        --detail-b64 subject=Rml4IHRoZSBleHBvcnQ=

The category and event are short names in lower case (letters, digits and
underscores). A category not in datahealth/events.py CATEGORIES is refused, so a
typo cannot make a category no filter lists. Exits with an error if the entry
could not be written, which the deploy treats as a warning, not a failure.
"""

import base64

from django.core.management.base import BaseCommand, CommandError

from datahealth import events


class Command(BaseCommand):
    help = "Add one entry to the server event log."

    def add_arguments(self, parser):
        parser.add_argument("category", help=", ".join(events.CATEGORIES))
        parser.add_argument("event", help="A short name such as deployed or started.")
        parser.add_argument("--message", default="")
        parser.add_argument("--level", choices=events.LEVELS, default=None)
        parser.add_argument("--actor", default=None, help="Who or what did it. Default: nobody.")
        parser.add_argument("--detail", action="append", default=[], metavar="NAME=VALUE",
                            help="Extra detail to keep with the entry. Repeat for more than one.")
        parser.add_argument("--detail-b64", action="append", default=[], metavar="NAME=BASE64",
                            help="A detail whose value is base64, for text that is not safe on a "
                                 "command line (a commit's subject).")

    def handle(self, category, event, message, level, actor, detail, detail_b64, **options):
        if category not in events.CATEGORIES:
            raise CommandError(f"{category!r} is not a category. Choose from: {', '.join(events.CATEGORIES)}.")
        if not events.valid_slug(event):
            raise CommandError("The event is a short name in lower case: letters, digits and underscores.")
        details = {}
        for pair in detail:
            name, sep, value = pair.partition("=")
            if not sep or not name:
                raise CommandError(f"{pair!r} is not NAME=VALUE.")
            details[name] = value
        for pair in detail_b64:
            name, sep, value = pair.partition("=")
            try:
                details[name] = base64.b64decode(value, validate=True).decode("utf-8", errors="replace").strip()[:300]
            except ValueError:
                raise CommandError(f"The value of {name!r} is not base64.")
            if not sep or not name:
                raise CommandError(f"{pair!r} is not NAME=BASE64.")
        # A name that collides with record's own arguments would be swallowed or raise.
        for reserved in ("request", "user", "level", "message", "actor", "path", "occurred_at"):
            if reserved in details:
                raise CommandError(f"{reserved!r} cannot be used as a detail name.")
        entry = events.record(category, event, level=level, message=message, actor=actor or "", **details)
        if entry is None:
            raise CommandError("The entry could not be written. Has `manage.py migrate` been run?")
        self.stdout.write(f"Logged {category}/{event} as entry {entry.pk}.")
