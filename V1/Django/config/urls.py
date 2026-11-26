from django.urls import include, path

urlpatterns = [
    path("admin/", include("admintools.urls")),
    path("", include("survey.urls")),
]
