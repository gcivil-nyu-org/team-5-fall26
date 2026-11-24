"""The extra "Search events" links on event pages and the footer are gone (#185)."""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from events.models import Event


class NoSearchEventsLinkTests(TestCase):
    """Event pages and the footer no longer carry a separate search link."""

    @classmethod
    def setUpTestData(cls):
        start = timezone.now() + timedelta(days=2)
        cls.event = Event.objects.create(
            guid="no-search-link",
            title="Harbor Cleanup",
            content_hash="",
            start_time=start,
            registration_url="https://example.com/register",
        )

    def test_event_page_has_no_search_events_link(self):
        """The link above the event card is removed."""
        response = self.client.get(reverse("event_detail", args=[self.event.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'class="detail-back"')
        self.assertNotContains(
            response, f'<a href="{reverse("search")}">Search events</a>', html=True
        )

    def test_footer_has_no_search_events_link(self):
        """The footer's Explore list no longer offers Search events."""
        for url in (reverse("landing"), reverse("event_detail", args=[self.event.pk])):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertNotContains(response, ">Search events</a>")
