"""Views for public site pages."""

from django.conf import settings
from django.shortcuts import resolve_url
from django.views.generic import TemplateView


class LandingView(TemplateView):
    """The landing page served from the site root."""

    template_name = "pages/landing.html"

    def get_context_data(self, **kwargs):
        """Add the login page URL for the "Log in" link."""
        context = super().get_context_data(**kwargs)
        context["login_url"] = resolve_url(settings.LOGIN_URL)
        return context
