"""
Create the named logins.

    manage.py make_users

Named accounts rather than one shared password, because the audit log records
who made a change and a shared login would record nobody. Each password is read
from the environment, so none is ever committed.

Running it again resets the passwords rather than failing.
"""

import os

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

# username, first name, last name, environment variable, admin panel access
PEOPLE = [
    ("brandon", "Brandon", "Connely", "BRANDON_PASSWORD", True),
    ("doug", "Doug", "Sandilands", "DOUG_PASSWORD", True),
    ("jenn", "Jenn", "Tackaberry", "JENN_PASSWORD", True),
    ("james", "James", "Fahlbusch", "JAMES_PASSWORD", True),
]


class Command(BaseCommand):
    help = "Create or update the named logins."

    def handle(self, *args, **options):
        missing = [v for _, _, _, v, _ in PEOPLE if not os.environ.get(v)]
        if missing:
            raise CommandError(
                "not set: " + ", ".join(missing) +
                ". Put them in the environment, not in a file that gets committed.")

        for username, first, last, variable, is_staff in PEOPLE:
            user, created = User.objects.get_or_create(username=username)
            user.first_name = first
            user.last_name = last
            user.is_staff = is_staff
            user.is_active = True
            user.set_password(os.environ[variable])
            user.save()
            self.stdout.write(
                f"{'created' if created else 'updated'} {username}"
                f"{' (admin)' if is_staff else ''}")
