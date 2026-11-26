"""
Create the permissions and roles.

    manage.py setup_access

Run after every deploy, and safe to run again. It also gives a role to anyone
without one: staff become Admin, everyone else Viewer.
"""

from django.core.management.base import BaseCommand

from datahealth import access


class Command(BaseCommand):
    help = "Create the permissions and roles, and place users who have no role."

    def handle(self, *args, **options):
        placed = access.ensure()
        self.stdout.write(f"roles ready; {placed} user(s) placed")
