"""The six site permissions (decision 006), on a model with no table."""

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Access",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ],
            options={
                "permissions": [
                    ("browse", "Browse records, export and use SQL"),
                    ("edit_records", "Edit and delete efforts and sightings"),
                    ("manage_tracks", "Use the Track File Manager"),
                    ("manage_audit", "Use the Audit Log and restore versions"),
                    ("manage_users", "Manage users and roles"),
                    ("view_server", "View the Server page"),
                ],
                "managed": False,
                "default_permissions": (),
            },
        ),
    ]
