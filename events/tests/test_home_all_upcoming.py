"""The home page links to every upcoming event, not just the first 20 (#190)."""

from datetime import timedelta
from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from events.filters import nyc_today
from events.models import Event
from events.views import UPCOMING_EVENT_LIMIT


class HomeAllUpcomingTests(TestCase):
    """More upcoming events than the home page shows, for a signed-in user."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            "homeviewer", "homeviewer@example.com", "pass12345"
        )
        start = timezone.now() + timedelta(days=1)
        cls.total = UPCOMING_EVENT_LIMIT + 5
        Event.objects.bulk_create(
            Event(
                guid=f"home-all-{i}",
                title=f"Upcoming Walk {i:02d}",
                content_hash="",
                start_time=start + timedelta(hours=i),
                registration_url="https://example.com/register",
            )
            for i in range(cls.total)
        )

    def setUp(self):
        self.client.force_login(self.user)

    def expected_url(self):
        query = urlencode({"date_from": nyc_today().isoformat()})
        return reverse("search") + "?" + query

    def test_home_links_to_all_upcoming_events(self):
        """The Upcoming section has a View all link to today's onward search."""
        response = self.client.get(reverse("landing"))

        self.assertEqual(len(response.context["events"]), UPCOMING_EVENT_LIMIT)
        self.assertEqual(response.context["all_upcoming_url"], self.expected_url())
        self.assertContains(
            response,
            f'<a class="section-link" href="{self.expected_url()}">'
            "View all upcoming events →</a>",
            html=True,
        )

    def test_event_count_pill_is_gone(self):
        """The "20 events" label next to the heading is no longer shown."""
        response = self.client.get(reverse("landing"))
        section = response.content.decode().split('id="events-heading"')[1]
        section = section.split("</section>")[0]

        self.assertNotIn("count-pill", section)
        self.assertNotIn(f"{UPCOMING_EVENT_LIMIT} events", section)

    def test_link_lists_every_upcoming_event(self):
        """Following the link shows all upcoming events across its pages."""
        response = self.client.get(self.expected_url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["paginator"].count, self.total)
