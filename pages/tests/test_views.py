"""Tests for the landing page."""

from django.conf import settings
from django.test import TestCase
from django.urls import reverse


class LandingViewTests(TestCase):
    """The landing page at the site root."""

    def setUp(self):
        """Set up the page URL."""
        self.url = reverse("home")

    def test_home_is_the_site_root(self):
        """The landing page is served from /."""
        self.assertEqual(self.url, "/")

    def test_get_renders_the_landing_template(self):
        """A GET returns the landing page with its hero content."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/landing.html")
        self.assertContains(response, "NYC Event Explorer")

    def test_get_shows_register_login_and_admin_links(self):
        """The landing page links to registration, login, and the admin site."""
        response = self.client.get(self.url)
        self.assertContains(response, f'href="{reverse("register")}"')
        self.assertContains(response, f'href="{settings.LOGIN_URL}"')
        self.assertContains(response, f'href="{reverse("admin:index")}"')
