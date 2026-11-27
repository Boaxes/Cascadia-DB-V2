"""URLs for the Photo-ID group: Individuals."""

from django.urls import path

from photoid import views

app_name = "photoid"

urlpatterns = [
    path("individuals/", views.individual_list, name="individual_list"),
]
