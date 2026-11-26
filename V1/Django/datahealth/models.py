"""The server event log: one row for each thing worth knowing that the server did.

Sign-ins, exports, changes to the data, GPS file checks, deploys, pipeline runs,
errors. Written through datahealth/events.py, read by the Server page of the
Django admin (datahealth/server_views.py). This is the only table the
datahealth app owns; the survey data is untouched.

Times are UTC, stored without a zone, as the rest of the site does (USE_TZ is off).
"""

import datetime

from django.db import models


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


class ServerEvent(models.Model):
    LEVELS = [("info", "Info"), ("warning", "Warning"), ("error", "Error")]

    occurred_at = models.DateTimeField(default=utcnow, db_index=True)
    category = models.CharField(max_length=20)
    event = models.CharField(max_length=40)
    level = models.CharField(max_length=10, choices=LEVELS, default="info")
    # The name as shown, kept as text so the entry still reads right after a
    # user is deleted or renamed. A failed sign-in holds the name that was tried.
    actor = models.CharField(max_length=150, blank=True, default="")
    actor_id = models.IntegerField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    path = models.CharField(max_length=300, blank=True, default="")
    message = models.TextField(blank=True, default="")
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-occurred_at", "-id"]
        indexes = [
            models.Index(fields=["category", "-occurred_at"], name="serverevent_category_idx"),
            models.Index(fields=["level", "-occurred_at"], name="serverevent_level_idx"),
        ]

    def __str__(self):
        return f"{self.occurred_at:%Y-%m-%d %H:%M:%S} {self.category}/{self.event}"


class ServerSample(models.Model):
    """One reading of the machine, about a minute apart, for the graph on the Server
    page. Written by datahealth/serverhealth.py while the site is in use; a week is kept."""

    # The minute it was taken, so two workers sampling at once keep one reading.
    taken_at = models.DateTimeField(unique=True)
    cpu = models.FloatField(null=True)        # percent
    memory = models.FloatField(null=True)     # percent
    disk = models.FloatField(null=True)       # percent, of the fullest disk
    database_ms = models.FloatField(null=True)

    class Meta:
        ordering = ["taken_at"]
