"""URLs for the Data group: Export, SQL."""

from django.urls import path

from analysis import views

app_name = "analysis"

urlpatterns = [
    path("export/", views.export_page, name="export_page"),
    path("sql/", views.sql_page, name="sql_page"),
]
