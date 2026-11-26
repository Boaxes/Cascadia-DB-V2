"""Makes the Django admin use our site. Kept apart from sites.py, which needs
the app registry and so cannot be imported while the apps are loading."""

from django.contrib.admin.apps import AdminConfig


class AccessAdminConfig(AdminConfig):
    default_site = "datahealth.sites.AccessAdminSite"
