"""Tests for permanently deleting a signed-in user's own account."""

from datetime import datetime
from zoneinfo import ZoneInfo

from django.contrib.auth import SESSION_KEY, get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from accounts.ban_services import apply_ban
from accounts.forms import DeleteAccountForm
from events.models import Event, EventInterest, Notification, Registration

NYC = ZoneInfo("America/New_York")
User = get_user_model()
PASSWORD = "Tr1cky-Passphrase!"


class DeleteAccountTests(TestCase):
    """Account Settings links to a confirm page that deletes after email match."""

    @classmethod
    def setUpTestData(cls):
        """Create an owner, a peer, and a staff member who can apply bans."""
        cls.user = User.objects.create_user(
            "alice",
            "alice@example.com",
            PASSWORD,
            display_name="Alice",
        )
        cls.peer = User.objects.create_user(
            "bob",
            "bob@example.com",
            PASSWORD,
        )
        cls.admin = User.objects.create_superuser(
            "admin",
            "admin@example.com",
            PASSWORD,
        )

    def setUp(self):
        """Sign in as the account owner for each test."""
        self.client.force_login(self.user)
        self.url = reverse("delete_account")
        self.settings_url = reverse("account_settings")

    def test_settings_links_to_delete_account_for_active_and_banned_members(self):
        """Account Settings always offers Delete my account, including while banned."""
        response = self.client.get(self.settings_url)
        self.assertContains(response, "Delete account")
        self.assertContains(response, f'href="{self.url}"')
        self.assertContains(response, "Delete my account")

        apply_ban(self.admin, self.user)
        response = self.client.get(self.settings_url)
        self.assertContains(response, "Delete my account")
        self.assertContains(response, f'href="{self.url}"')

    def test_confirm_page_requires_login_and_explains_consequences(self):
        """Visitors are sent to log in; members see the email confirm form."""
        self.client.logout()
        response = self.client.get(self.url)
        self.assertRedirects(
            response,
            f'{reverse("login")}?next={self.url}',
            fetch_redirect_response=False,
        )

        self.client.force_login(self.user)
        hosted = Event.objects.create(
            guid=Event.HOSTED_GUID_PREFIX + "delete-me",
            title="Hosted Walk",
            host=self.user,
            content_hash="a" * 64,
            start_time=datetime(2099, 1, 1, 10, tzinfo=NYC),
        )
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/delete_account.html")
        self.assertContains(response, 'name="email"')
        self.assertContains(response, "Permanently delete account")
        self.assertContains(response, "1 event you host")
        self.assertContains(response, hosted.title, count=0)
        self.assertIsInstance(response.context["form"], DeleteAccountForm)

    def test_wrong_email_keeps_the_account(self):
        """A mismatched email shows an error and does not delete the user."""
        response = self.client.post(self.url, {"email": "wrong@example.com"})
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"],
            "email",
            "Enter the email address for this account to confirm deletion.",
        )
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_matching_email_deletes_account_hosted_events_and_logs_out(self):
        """The correct email removes the user, hosted events, and the session."""
        hosted = Event.objects.create(
            guid=Event.HOSTED_GUID_PREFIX + "gone",
            title="Sunset Yoga",
            host=self.user,
            content_hash="b" * 64,
            start_time=datetime(2099, 2, 1, 18, tzinfo=NYC),
        )
        other_event = Event.objects.create(
            guid=Event.HOSTED_GUID_PREFIX + "peer",
            title="Peer Picnic",
            host=self.peer,
            content_hash="c" * 64,
            start_time=datetime(2099, 3, 1, 12, tzinfo=NYC),
        )
        Registration.objects.create(user=self.user, event=other_event, party_size=2)

        response = self.client.post(
            self.url, {"email": "Alice@Example.com"}, follow=True
        )
        self.assertRedirects(
            response, reverse("landing"), fetch_redirect_response=False
        )
        self.assertContains(response, "Your account has been permanently deleted.")
        self.assertContains(response, 'class="toast toast-success"')
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())
        self.assertFalse(Event.objects.filter(pk=hosted.pk).exists())
        self.assertTrue(Event.objects.filter(pk=other_event.pk).exists())
        self.assertFalse(Registration.objects.filter(user_id=self.user.pk).exists())
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_deleted_account_cannot_log_in_and_profile_is_gone(self):
        """After deletion, login fails and the public profile is not found."""
        username = self.user.username
        self.client.post(self.url, {"email": self.user.email})

        response = self.client.post(
            reverse("login"),
            {"username": username, "password": PASSWORD},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(SESSION_KEY, self.client.session)

        self.client.force_login(self.peer)
        response = self.client.get(reverse("public_profile", args=[username]))
        self.assertEqual(response.status_code, 404)

    def test_banned_member_can_delete_their_account(self):
        """An active ban does not block the delete confirmation POST."""
        apply_ban(self.admin, self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

        response = self.client.post(self.url, {"email": self.user.email})
        self.assertRedirects(response, reverse("landing"))
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())

    def test_get_does_not_delete_and_post_is_required(self):
        """Opening the confirm page never deletes; only a valid POST does."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_open_event_guests_are_notified_that_hosted_events_are_cancelled(self):
        """Registered and Interested guests get a cancel notice for open events."""
        guest = User.objects.create_user(
            "cara", "cara@example.com", PASSWORD, display_name="Cara"
        )
        fan = User.objects.create_user(
            "erin", "erin@example.com", PASSWORD, display_name="Erin"
        )
        bystander = User.objects.create_user("dan", "dan@example.com", PASSWORD)
        hosted = Event.objects.create(
            guid=Event.HOSTED_GUID_PREFIX + "notify-cancel",
            title="Morning Stretch",
            host=self.user,
            content_hash="d" * 64,
            start_time=datetime(2099, 4, 1, 9, tzinfo=NYC),
            location="Central Park",
        )
        Registration.objects.create(user=guest, event=hosted, party_size=2)
        Registration.objects.create(user=self.user, event=hosted, party_size=1)
        EventInterest.objects.create(event=hosted, user=fan)

        response = self.client.post(self.url, {"email": self.user.email})
        self.assertRedirects(response, reverse("landing"))
        self.assertFalse(Event.objects.filter(pk=hosted.pk).exists())

        notice = Notification.objects.get(recipient=guest)
        self.assertEqual(notice.subject, "Cancelled: Morning Stretch")
        self.assertIn("Alice cancelled Morning Stretch.", notice.body)
        self.assertIn("host deleted their account", notice.body)
        self.assertIsNone(notice.event_id)
        self.assertTrue(Notification.objects.filter(recipient=fan).exists())
        self.assertFalse(Notification.objects.filter(recipient=bystander).exists())
        self.assertFalse(Notification.objects.filter(recipient=self.user).exists())

        self.assertEqual(
            sorted(email.to[0] for email in mail.outbox),
            ["cara@example.com", "erin@example.com"],
        )
        self.assertEqual(mail.outbox[0].subject, "Cancelled: Morning Stretch")
        self.assertIn("Alice cancelled Morning Stretch.", mail.outbox[0].body)

        self.client.force_login(guest)
        page = self.client.get(reverse("notifications"))
        self.assertContains(page, "Cancelled: Morning Stretch")
        self.assertContains(page, "host deleted their account")

    def test_past_and_done_hosted_events_do_not_send_cancel_notices(self):
        """Ended or archived hosted events are removed quietly."""
        guest = User.objects.create_user("finn", "finn@example.com", PASSWORD)
        past = Event.objects.create(
            guid=Event.HOSTED_GUID_PREFIX + "past-walk",
            title="Last Week Walk",
            host=self.user,
            content_hash="e" * 64,
            start_time=datetime(2020, 1, 1, 10, tzinfo=NYC),
            end_time=datetime(2020, 1, 1, 11, tzinfo=NYC),
            status=Event.Status.UPCOMING,
        )
        done = Event.objects.create(
            guid=Event.HOSTED_GUID_PREFIX + "done-walk",
            title="Finished Meetup",
            host=self.user,
            content_hash="f" * 64,
            start_time=datetime(2099, 5, 1, 10, tzinfo=NYC),
            status=Event.Status.DONE,
        )
        Registration.objects.create(user=guest, event=past)
        Registration.objects.create(user=guest, event=done)

        response = self.client.post(self.url, {"email": self.user.email})
        self.assertRedirects(response, reverse("landing"))
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())
        self.assertFalse(Notification.objects.filter(recipient=guest).exists())
        self.assertEqual(mail.outbox, [])
