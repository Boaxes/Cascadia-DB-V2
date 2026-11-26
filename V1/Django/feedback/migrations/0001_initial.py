import feedback.models
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="FeedbackPicture",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("token", models.CharField(default=feedback.models.new_token, max_length=64, unique=True)),
                ("content_type", models.CharField(max_length=40)),
                ("data", models.BinaryField()),
                ("created", models.DateTimeField(auto_now_add=True)),
            ],
        ),
    ]
