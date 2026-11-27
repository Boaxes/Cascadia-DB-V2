"""URLs for the Survey group: Explore, Efforts, Sightings."""

from django.urls import path

from survey import views

app_name = "survey"

urlpatterns = [
    path("explore/", views.explore, name="explore"),
    path("efforts/", views.effort_list, name="effort_list"),
    path("sightings/", views.sighting_list, name="sighting_list"),
]
