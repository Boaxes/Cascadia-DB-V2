"""URLs for the Manage group: Track File Manager, Audit Log, Server."""

from django.urls import path

from manage import views

app_name = "manage"

urlpatterns = [
    path("tracks/", views.track_list, name="track_list"),
    path("audit/", views.audit_list, name="audit_list"),
    path("server/", views.server_page, name="server_page"),
]
