"""
Settings for the self-contained tests in unit_tests/: no database, no GDAL, no
bucket. Just enough of Django for the code under test to import.

    python manage.py test unit_tests --settings=config.unit_settings
"""

SECRET_KEY = "unit-tests-only"
INSTALLED_APPS = ["django.contrib.auth", "django.contrib.contenttypes"]
DATABASES = {}
USE_TZ = False
LOGIN_URL = "/login/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
ROOT_URLCONF = "unit_tests.urls"

# The checks of GPS files written in a test land here, never beside the real ones.
import tempfile as _tempfile  # noqa: E402

TRACK_CHECKS_DIR = _tempfile.mkdtemp(prefix="unit-checks-")
