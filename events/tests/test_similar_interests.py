"""Privacy, matching, and page tests for event-interest discovery (#54)."""

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from accounts.forms import AccountSettingsForm
from accounts.models import User
from events.models import Event, EventInterest, Registration
from events.similar_interests import (
    category_query,
    category_tags,
    category_terms,
    find_similar_interest_users,
    shared_interest_label,
)


def make_event(guid, categories, status=Event.Status.UPCOMING):
    """Create an event with public category labels."""
    return Event.objects.create(
        guid=guid,
        title=guid,
        categories=categories,
        status=status,
        content_hash="e" * 64,
    )


def make_user(username, *, sharing=True, similar=True):
    """Create a member with independently controlled visibility settings."""
    return User.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password="not-a-real-password",
        display_name=username.capitalize(),
        share_profile_with_attendees=sharing,
        discoverable_for_similar_events=similar,
    )


class CategoryMatchingTests(SimpleTestCase):
    """Only genuine, human-readable event categories match."""

    def test_category_tags_ignore_empty_segments(self):
        self.assertEqual(category_tags(" Sports | | Basketball/Netball "), [
            "Sports",
            "Basketball/Netball",
        ])
        self.assertEqual(category_tags(""), [])

    def test_terms_expand_using_existing_groups(self):
        terms = category_terms(["Basketball/Netball"])
        self.assertIn("Sports", terms)
        self.assertIn("Running/Jogging", terms)
        self.assertIn("Basketball/Netball", terms)
        self.assertNotIn("Gardening", terms)

    def test_exact_and_related_interest_labels(self):
        source = ["Sports", "Basketball/Netball"]
        self.assertEqual(
            shared_interest_label(source, "Basketball/Netball"),
            "Basketball/Netball",
        )
        self.assertEqual(shared_interest_label(source, "Running/Jogging"), "Sports")
        self.assertIsNone(shared_interest_label(source, "Gardening"))

    def test_unlisted_categories_can_still_match_exactly(self):
        self.assertEqual(
            shared_interest_label(["Community Chess"], "community chess"),
            "Community Chess",
        )

    def test_category_query_uses_complete_pipe_separated_labels(self):
        self.assertIsNotNone(category_query("event__categories", "Art"))


class SimilarInterestDiscoveryTests(TestCase):
    """Only consenting users with related upcoming events are suggested."""

    @classmethod
    def setUpTestData(cls):
        cls.event = make_event("basketball", "Sports | Basketball/Netball")
        cls.other_sports = make_event("running", "Running/Jogging")
        cls.same_sport = make_event("basketball-other", "Basketball/Netball")
        cls.other_topic = make_event("gardening", "Gardening")
        cls.viewer = make_user("viewer")
        cls.runner = make_user("runner")
        EventInterest.objects.create(user=cls.runner, event=cls.other_sports)

    def suggestions(self, event=None, viewer=None, limit=6):
        """Fetch suggested profiles and their shared labels."""
        return find_similar_interest_users(
            event or self.event,
            viewer=viewer or self.viewer,
            limit=limit,
        )

    def test_related_event_category_discovers_different_event_attendee(self):
        suggestions = self.suggestions()
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]["user"], self.runner)
        self.assertEqual(suggestions[0]["shared_interest"], "Sports")

    def test_exact_category_match_uses_specific_interest_label(self):
        person = make_user("ballplayer")
        EventInterest.objects.create(user=person, event=self.same_sport)
        by_user = {item["user"].pk: item for item in self.suggestions()}
        self.assertEqual(
            by_user[person.pk]["shared_interest"],
            "Basketball/Netball",
        )

    def test_unrelated_categories_do_not_match(self):
        person = make_user("gardener")
        EventInterest.objects.create(user=person, event=self.other_topic)
        self.assertNotIn(person, [item["user"] for item in self.suggestions()])

    def test_no_partial_word_category_match(self):
        art = make_event("art", "Art")
        martial = make_event("martial", "Martial Arts")
        person = make_user("martialmember")
        EventInterest.objects.create(user=person, event=martial)
        self.assertEqual(self.suggestions(event=art), [])

    def test_hidden_or_not_separately_opted_in_profiles_are_excluded(self):
        no_profile = make_user("noprofile", sharing=False, similar=True)
        no_similar = make_user("nosimilar", sharing=True, similar=False)
        for user in (no_profile, no_similar):
            EventInterest.objects.create(event=self.other_sports, user=user)
        users = [item["user"] for item in self.suggestions()]
        self.assertEqual(users, [self.runner])

    def test_unchecked_discovery_defaults_to_off(self):
        member = User.objects.create_user(
            username="private", email="private@example.com"
        )
        self.assertFalse(member.discoverable_for_similar_events)
        member.share_profile_with_attendees = True
        member.save()
        EventInterest.objects.create(event=self.other_sports, user=member)
        self.assertNotIn(member, [item["user"] for item in self.suggestions()])

    def test_same_event_attendees_and_registrants_are_not_repeated(self):
        same_interest = make_user("sameinterest")
        same_registration = make_user("sameregistration")
        EventInterest.objects.create(event=self.event, user=same_interest)
        Registration.objects.create(event=self.event, user=same_registration)
        for user in (same_interest, same_registration):
            EventInterest.objects.create(event=self.other_sports, user=user)
        self.assertEqual([i["user"] for i in self.suggestions()], [self.runner])

    def test_current_viewer_is_not_suggested(self):
        EventInterest.objects.create(event=self.other_sports, user=self.viewer)
        self.assertEqual([i["user"] for i in self.suggestions()], [self.runner])

    def test_user_is_only_suggested_once_even_with_multiple_events(self):
        EventInterest.objects.create(event=self.same_sport, user=self.runner)
        self.assertEqual([i["user"] for i in self.suggestions()], [self.runner])

    def test_ended_cancelled_and_inactive_users_are_excluded(self):
        ended = make_event("ended-sports", "Sports", Event.Status.DONE)
        cancelled = make_event("cancelled-sports", "Sports", Event.Status.CANCELLED)
        for event, name in (
            (ended, "endedmember"),
            (cancelled, "cancelledmember"),
        ):
            EventInterest.objects.create(event=event, user=make_user(name))
        inactive = make_user("inactive")
        inactive.is_active = False
        inactive.save()
        EventInterest.objects.create(event=self.other_sports, user=inactive)
        self.assertEqual([i["user"] for i in self.suggestions()], [self.runner])

    def test_empty_categories_closed_events_and_zero_limit_return_nothing(self):
        self.assertEqual(self.suggestions(event=make_event("blank", "")), [])
        self.assertEqual(
            self.suggestions(event=make_event("closed", "Sports", Event.Status.DONE)),
            [],
        )
        self.assertEqual(self.suggestions(limit=0), [])

    def test_result_limit_is_applied(self):
        EventInterest.objects.create(
            event=self.other_sports,
            user=make_user("another"),
        )
        self.assertEqual(len(self.suggestions(limit=1)), 1)

    def test_profile_settings_can_enable_and_disable_suggestions(self):
        member = make_user("settingsmember", sharing=False, similar=False)
        form = AccountSettingsForm(
            {
                "share_profile_with_attendees": "on",
                "discoverable_for_similar_events": "on",
            },
            instance=member,
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        member.refresh_from_db()
        self.assertTrue(member.share_profile_with_attendees)
        self.assertTrue(member.discoverable_for_similar_events)

        form = AccountSettingsForm({}, instance=member)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        member.refresh_from_db()
        self.assertFalse(member.discoverable_for_similar_events)

    def test_event_page_displays_shared_category_and_public_profile_link(self):
        self.client.force_login(self.viewer)
        response = self.client.get(reverse("event_detail", args=[self.event.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "People with Similar Interests")
        self.assertContains(response, "Shared interest: Sports")
        self.assertContains(
            response,
            reverse("public_profile", args=[self.runner.username]),
        )
        self.assertNotContains(response, self.runner.email)
        self.assertEqual(
            [item["user"] for item in response.context["similar_interest_users"]],
            [self.runner],
        )

    def test_private_profile_is_not_visible_in_event_page(self):
        private = make_user("privateperson", similar=False)
        EventInterest.objects.create(event=self.other_sports, user=private)
        self.client.force_login(self.viewer)
        response = self.client.get(reverse("event_detail", args=[self.event.pk]))
        self.assertNotContains(response, private.username)
        self.assertNotContains(response, private.email)

    def test_anonymous_visitors_do_not_see_similar_profile_discovery(self):
        response = self.client.get(reverse("event_detail", args=[self.event.pk]))
        self.assertNotContains(response, "People with Similar Interests")
        self.assertNotContains(response, self.runner.username)

    def test_event_page_does_not_suggest_on_cancelled_event(self):
        self.event.status = Event.Status.CANCELLED
        self.event.save()
        self.client.force_login(self.viewer)
        response = self.client.get(reverse("event_detail", args=[self.event.pk]))
        self.assertNotContains(response, "People with Similar Interests")

    def test_public_profile_setting_is_visible_in_account_settings(self):
        self.client.force_login(self.viewer)
        response = self.client.get(reverse("account_settings"))
        self.assertContains(response, 'name="discoverable_for_similar_events"')
        self.assertContains(response, "Show my public profile for similar events")
