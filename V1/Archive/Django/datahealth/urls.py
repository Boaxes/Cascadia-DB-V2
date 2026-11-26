from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="admin_home"),
    path("tracks/", views.tracks, name="admin_tracks"),
    path("tracks/effort/<int:legacy_id>/", views.track_effort, name="admin_track_effort"),
    path("tracks/file/<int:legacy_id>/", views.track_file, name="admin_track_file"),
    path("audit/", views.audit_log, name="admin_audit"),
    path("users/", views.users, name="data_health_users"),
    path("audit/<int:entry_id>/", views.audit_entry, name="admin_audit_entry"),
]
