"""URL routes for the pages app."""

from django.urls import path

from .views import LandingView

urlpatterns = [
    path("", LandingView.as_view(), name="home"),
]
