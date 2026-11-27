"""The six site permissions (decision 006), declared on a model that has no table."""

from django.db import models


class Access(models.Model):
    """Holds the permissions the five role groups are built from."""

    class Meta:
        managed = False
        default_permissions = ()
        permissions = [
            ("browse", "Browse records, export and use SQL"),
            ("edit_records", "Edit and delete efforts and sightings"),
            ("manage_tracks", "Use the Track File Manager"),
            ("manage_audit", "Use the Audit Log and restore versions"),
            ("manage_users", "Manage users and roles"),
            ("view_server", "View the Server page"),
        ]

    def __str__(self) -> str:
        return "Access"
