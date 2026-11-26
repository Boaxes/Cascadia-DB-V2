"""
Settings for the Cascadia Marine Mammal Survey application.

The survey site reads SEDB and writes nothing to it. Only the login, the
session and the admin panel write anything at all.
"""

import os
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(DJANGO_DEBUG=(bool, False))
environ.Env.read_env(BASE_DIR / ".env")


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env("DJANGO_DEBUG")

# The droplet's address, or a domain pointed at it, goes in
# DJANGO_ALLOWED_HOSTS. The local names stay so the same file runs a
# development server with nothing set.
# The blank filter matters: an .env line left empty reads as one empty name,
# and an empty CSRF origin fails Django's own startup check.
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]", "testserver"] + [
    host for host in env.list("DJANGO_ALLOWED_HOSTS", default=[]) if host]

# Needed once the site answers on https, where Django checks the Origin header
# of a form post against this list rather than against ALLOWED_HOSTS.
CSRF_TRUSTED_ORIGINS = [
    origin for origin in env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[]) if origin]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.gis",
    "django.contrib.humanize",
    "survey",
    "admintools",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # The Explore map's two payloads are mostly repeated digits and compress
    # by roughly four to one, which is the difference between a map that
    # opens instantly and one that visibly waits. Nothing served in Phase 1
    # is secret or user specific; if Phase 2 puts a session token into a
    # compressed page, revisit this for BREACH.
    "django.middleware.gzip.GZipMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Locally, turns "relation auth_user does not exist" into instructions to
    # run ops/pull-db.sh. Does nothing when DEBUG is off.
    "survey.middleware.EmptyDatabaseMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

# Django defaults this to "same-origin", which strips the Referer header from
# every cross-origin request. OpenStreetMap's tile servers reject requests
# without one, so with the default every basemap tile comes back 403 "Access
# blocked". This sends the origin, and nothing else, to other hosts.
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "survey.context_processors.colour_profile",
            ],
        },
    },
]


# ---------------------------------------------------------------------------
# Database
#
# The survey tables live on a DigitalOcean managed PostgreSQL cluster, which
# runs continuously, so a connection is worth keeping rather than paying for
# a TLS handshake on every request. CONN_MAX_AGE holds one open per worker
# for a minute.
# ---------------------------------------------------------------------------

DATABASES = {
    "default": {
        **env.db("DATABASE_URL"),
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "OPTIONS": {
            # The models name views without a schema, so the search path is
            # what resolves them. public comes first so that migrate creates
            # Django's own tables there -- it uses the first schema on the path,
            # and putting them in `app` would mean the import dropping the
            # login table every time it rebuilt the views. Then app for the
            # views the application reads, and dbo for the tables underneath,
            # which the history panel and the track tool query directly.
            # Nothing in public shares a name with anything in app or dbo.
            "options": "-c search_path=public,app,dbo",
        },
        # A DigitalOcean connection pool is PgBouncer in transaction mode, which
        # does not keep a named cursor between statements. Pointed at a pool
        # rather than the database itself, an export large enough for
        # .iterator() to page dies asking for its second chunk.
        "DISABLE_SERVER_SIDE_CURSORS": env.bool("DB_POOLED", default=False),
        "CONN_MAX_AGE": 60,
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Tests run against a fresh copy of the `reference` database. See
# config/test_runner.py for why.
TEST_RUNNER = "config.test_runner.ReferenceCopyRunner"


# ---------------------------------------------------------------------------
# Time
#
# The survey records carry no timezone, so Django must not assume one:
# USE_TZ = False keeps dates and times exactly as recorded.
#
# TIME_ZONE = "UTC" matters for one reason. track.start_time_utc and
# end_time_utc are the only "timestamp with time zone" columns in the
# database and they are UTC. With USE_TZ off, Postgres renders those columns
# in the connection's timezone, so anything other than UTC here would
# silently shift every track time.
# ---------------------------------------------------------------------------

TIME_ZONE = "UTC"
USE_TZ = False
USE_I18N = False


# ---------------------------------------------------------------------------
# Cache
#
# Species lists, vessel lists and filter dropdown options are identical on
# every request. Local memory is enough; there is nothing to share between
# processes in Phase 1.
# ---------------------------------------------------------------------------

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "TIMEOUT": 60 * 60,
    }
}

# A session holds the login and the export's filter values. The database
# backend keeps both server side, so a session can be ended by deleting its
# row in django_session.
SESSION_ENGINE = "django.contrib.sessions.backends.db"


# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

# nginx tells browsers to keep static files for a month, which is right for
# files that never change and wrong for files that do. Hashing the contents
# into the name makes both true at once: an edited file gets a new name, so a
# browser fetches it, and an unchanged one keeps its name and stays cached.
# Without this, a deploy leaves everyone on the previous month's JavaScript.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage",
    },
}
if DEBUG:
    STORAGES["staticfiles"]["BACKEND"] = "config.storage.DevStaticStorage"


# ---------------------------------------------------------------------------
# The rebuild's working space
#
# A rebuild reads the exports and the GPS files the operator sends it, and the
# rebuild tool reads folders, so an upload has to land here on the way through.
# One directory per run, deleted when the run ends. Nothing here outlives a
# rebuild: see admintools/uploads.py for why that matters.
#
# It needs room for the raw GPS files and the cleaned copies at once, about
# 1.2 GB today.
# ---------------------------------------------------------------------------

SEDB_RUN_ROOT = env("SEDB_RUN_ROOT", default=str(BASE_DIR / "run"))

# An upload arrives in batches of about 16 MB. Anything above this is written
# to a temporary file rather than held in memory, which is what keeps a
# 2 GB droplet out of trouble.
FILE_UPLOAD_MAX_MEMORY_SIZE = 4 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 4 * 1024 * 1024

# One batch is many files. The default of 1000 is generous already, but a
# batch of small GPS files can pass it.
DATA_UPLOAD_MAX_NUMBER_FILES = 2000


# Two logins: one for the survey site, one that also opens the admin panel.
# Both are created by `manage.py make_users`, which reads the passwords from
# the environment so none is committed.
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/explore/"
LOGOUT_REDIRECT_URL = "/login/"
