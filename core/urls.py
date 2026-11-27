"""URLs for sign-in, Settings, Feedback and the home redirect."""

from django.contrib.auth import views as auth_views
from django.urls import path

from core import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("login/", auth_views.LoginView.as_view(template_name="core/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("settings/", views.settings_page, name="settings"),
    path("feedback/", views.feedback_page, name="feedback"),
]
