from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("cascadia-admin/", include("datahealth.urls")),
    # Data Health's old address, for bookmarks.
    path("data-health/", RedirectView.as_view(pattern_name="admin_home")),
    path("feedback/", include("feedback.urls")),
    path("", include("survey.urls")),
]
