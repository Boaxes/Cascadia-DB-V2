from django.urls import path

from . import track_views, views

urlpatterns = [
    path("", views.dashboard, name="admin_home"),
    path("tracks/", track_views.workspace, name="admin_tracks"),
    path("tracks/import/", track_views.import_page, name="admin_track_import"),
    path("tracks/change/", track_views.change_page, name="admin_track_change"),
    path("tracks/<int:track_id>/fill/", track_views.fill_page, name="admin_track_fill"),
    path("tracks/<int:track_id>/delete/", track_views.delete_page, name="admin_track_delete"),
    path("tracks/api/files/", track_views.api_files, name="admin_tracks_files"),
    path("tracks/api/import/preview/", track_views.api_import_preview, name="admin_tracks_import_preview"),
    path("tracks/api/import/", track_views.api_import, name="admin_tracks_import"),
    path("tracks/api/positions/", track_views.api_positions, name="admin_tracks_positions"),
    path("tracks/api/positions/<int:effort_id>/", track_views.api_positions_draft, name="admin_tracks_positions_draft"),
    path("tracks/api/positions/<int:effort_id>/save/", track_views.api_positions_save, name="admin_tracks_positions_save"),
    path("tracks/api/candidates/", track_views.api_candidates, name="admin_tracks_candidates"),
    path("tracks/api/<int:track_id>/", track_views.api_open, name="admin_tracks_open"),
    path("tracks/api/<int:track_id>/save/", track_views.api_save, name="admin_tracks_save"),
    path("tracks/api/<int:track_id>/fill/preview/", track_views.api_fill_preview, name="admin_tracks_fill_preview"),
    path("tracks/api/<int:track_id>/fill/", track_views.api_fill, name="admin_tracks_fill"),
    path("tracks/api/<int:track_id>/version/", track_views.api_version, name="admin_tracks_version"),
    path("tracks/api/<int:track_id>/match/", track_views.api_match, name="admin_tracks_match"),
    path("tracks/api/<int:track_id>/unmatch/", track_views.api_unmatch, name="admin_tracks_unmatch"),
    path("tracks/api/<int:track_id>/delete/", track_views.api_delete, name="admin_tracks_delete"),
    path("tracks/api/<int:track_id>/restore/", track_views.api_restore, name="admin_tracks_restore"),
    path("audit/", views.audit_log, name="admin_audit"),
    path("audit/migration-script/", views.audit_script, name="admin_audit_script"),
    path("audit/<int:entry_id>/", views.audit_entry, name="admin_audit_entry"),
    path("pipeline/", views.data_pipeline, name="admin_pipeline"),
]
