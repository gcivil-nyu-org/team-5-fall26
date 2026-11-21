"""Bell items open the full message on the Notifications page (#182)."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from events.models import Event, Notification


class BellOpensMessageTests(TestCase):
    """A host's message is read in full on the Notifications page."""

    @classmethod
    def setUpTestData(cls):
        cls.guest = get_user_model().objects.create_user(
            "bellguest", "bellguest@example.com", "pass12345"
        )
        cls.event = Event.objects.create(
            guid="bell-message",
            title="Garden Volunteer Day",
            content_hash="",
            start_time=timezone.now() + timedelta(days=4),
            registration_url="https://example.com/register",
        )
        cls.body = "Bring gloves and water. " * 20 + "We meet at the north gate."
        cls.notice = Notification.objects.create(
            recipient=cls.guest,
            event=cls.event,
            subject="Update from your host",
            body=cls.body,
        )

    def setUp(self):
        self.client.force_login(self.guest)

    def test_bell_item_links_to_the_message_on_the_notifications_page(self):
        """The bell links to the notification, not to the event page."""
        html = self.client.post(reverse("notification_bell")).json()["html"]
        target = f'{reverse("notifications")}#notification-{self.notice.pk}'

        self.assertIn(f'href="{target}"', html)
        self.assertNotIn(reverse("event_detail", args=[self.event.pk]), html)

    def test_notifications_page_shows_the_whole_message_at_that_anchor(self):
        """The target exists and holds the full body, with the event linked."""
        response = self.client.get(reverse("notifications"))

        self.assertContains(response, f'id="notification-{self.notice.pk}"')
        self.assertContains(response, "We meet at the north gate.")
        self.assertContains(
            response, f'href="{reverse("event_detail", args=[self.event.pk])}"'
        )
