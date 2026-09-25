"""Tests for the registration page."""

from django.conf import settings
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from accounts.forms import RegistrationForm
from accounts.models import User

PASSWORD = "Tr1cky-Passphrase!"


class RegisterViewTests(TestCase):
    """The registration page at ``/accounts/register/``."""

    def setUp(self):
        """Set up the page URL and a valid submission."""
        self.url = reverse("register")
        self.data = {
            "username": "newuser",
            "email": "NewUser@Example.com",
            "display_name": "New User",
            "password1": PASSWORD,
            "password2": PASSWORD,
        }

    def messages_for(self, response):
        """Return the text of the messages queued for the response's request."""
        return [str(message) for message in get_messages(response.wsgi_request)]

    def test_page_is_at_accounts_register(self):
        """The registration page is served from /accounts/register/."""
        self.assertEqual(self.url, "/accounts/register/")

    def test_get_shows_form_and_login_link(self):
        """The page shows every registration field and a link to log in."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/register.html")
        self.assertIsInstance(response.context["form"], RegistrationForm)
        for name in ("username", "email", "display_name", "password1", "password2"):
            self.assertContains(response, f'name="{name}"')
        self.assertContains(response, "Already have an account?")
        self.assertContains(response, f'href="{settings.LOGIN_URL}"')

    def test_valid_submission_creates_account_and_redirects_to_login(self):
        """A valid submission saves the user and redirects with a success message."""
        response = self.client.post(self.url, self.data)
        self.assertRedirects(
            response, settings.LOGIN_URL, fetch_redirect_response=False
        )
        user = User.objects.get(username="newuser")
        self.assertEqual(user.email, "newuser@example.com")
        self.assertEqual(user.display_name, "New User")
        self.assertNotIn(PASSWORD, user.password)
        self.assertTrue(user.check_password(PASSWORD))
        self.assertEqual(
            self.messages_for(response),
            ["Welcome, New User! Your account has been created. Please log in."],
        )

    def test_success_message_uses_username_without_display_name(self):
        """Without a display name, the success message greets the username."""
        response = self.client.post(self.url, {**self.data, "display_name": ""})
        self.assertEqual(
            self.messages_for(response),
            ["Welcome, newuser! Your account has been created. Please log in."],
        )

    def test_success_message_is_shown_on_the_next_page(self):
        """The success message is displayed on the next page the user opens."""
        self.client.post(self.url, self.data)
        response = self.client.get(self.url)
        self.assertContains(response, "Welcome, New User! Your account has been")

    def test_registered_user_can_log_in(self):
        """Someone who registers can then log in with their new credentials."""
        self.client.post(self.url, self.data)
        self.assertTrue(self.client.login(username="newuser", password=PASSWORD))

    def test_invalid_submission_shows_errors_and_creates_nothing(self):
        """Invalid input re-renders the form with errors and saves nothing."""
        User.objects.create_user("taken", "taken@example.com", PASSWORD)
        response = self.client.post(
            self.url,
            {
                **self.data,
                "username": "taken",
                "email": "Taken@Example.com",
                "password2": "Other-Passphrase!",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "A user with that username already exists.")
        self.assertContains(
            response, "An account with this email address already exists."
        )
        self.assertContains(response, "The two password fields didn’t match.")
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(self.messages_for(response), [])
