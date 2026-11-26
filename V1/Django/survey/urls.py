from django.contrib.auth import views as auth_views
from django.urls import path
from django.views.generic import RedirectView

from . import edit_views, export_views, views

urlpatterns = [
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),

    # Explore is the landing page. There is no separate home page.
    path("", RedirectView.as_view(pattern_name="explore", permanent=False),
         name="home"),

    path("explore/", views.explore, name="explore"),

    path("efforts/", views.effort_list, name="effort_list"),
    path("efforts/<int:legacy_id>/", views.effort_detail, name="effort_detail"),
    path("efforts/<int:pk>/edit/", edit_views.edit, {"kind": "daily_effort"},
         name="effort_edit"),
    path("efforts/<int:pk>/delete/", edit_views.delete, {"kind": "daily_effort"},
         name="effort_delete"),

    path("sightings/", views.sighting_list, name="sighting_list"),
    path("sightings/<int:legacy_id>/", views.sighting_detail, name="sighting_detail"),
    path("sightings/<int:pk>/edit/", edit_views.edit, {"kind": "sighting"},
         name="sighting_edit"),
    path("sightings/<int:pk>/delete/", edit_views.delete, {"kind": "sighting"},
         name="sighting_delete"),

    path("export/", export_views.export_page, name="export"),
    path("export/download/", export_views.export_download, name="export_download"),
    path("export/preview/", export_views.export_preview, name="export_preview"),
    path("export/add/", export_views.export_add, name="export_add"),
    path("export/remove/", export_views.export_remove, name="export_remove"),
    path("export/related/", export_views.export_related, name="export_related"),

    path("settings/", views.settings_page, name="settings"),

    path("api/sightings/", views.sightings_json, name="api_sightings"),
    path("api/efforts/", views.efforts_json, name="api_efforts"),
    path("api/tracks/", views.tracks_json, name="api_tracks"),
    path("api/track/<int:legacy_id>/", views.track_full_json, name="api_track_full"),
]
