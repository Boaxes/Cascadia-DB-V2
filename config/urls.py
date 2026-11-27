"""Project URLs: each app's own urls.py, plus Django's admin for Users (USER requirements)."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
    path("", include("survey.urls")),
    path("", include("photoid.urls")),
    path("", include("analysis.urls")),
    path("", include("manage.urls")),
]
