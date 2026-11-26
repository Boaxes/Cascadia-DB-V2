from django.urls import path

from . import views

urlpatterns = [
    path("", views.feedback, name="feedback"),
    path("picture/<slug:token>.<slug:ext>", views.picture, name="feedback_picture"),
]
