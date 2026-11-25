"""Attendee cards link to profiles; messaging starts on the profile (#191)."""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import ContactPermission, User
from events.models import (
    ContactRequest,
    Conversation,
    Event,
    EventInterest,
    Notification,
    Registration,
)


class AttendeeCardProfileOnlyTests(TestCase):
    """The hover card offers See Details only, for both attendee groups."""

    @classmethod
    def setUpTestData(cls):
        start = timezone.now() + timedelta(days=3)
        cls.event = Event.objects.create(
            guid="card-profile-only",
            title="Riverside Picnic",
            content_hash="c" * 64,
            start_time=start,
            end_time=start + timedelta(hours=2),
            status=Event.Status.UPCOMING,
        )
        cls.viewer = User.objects.create_user(
            "cardviewer", "cardviewer@example.com", share_profile_with_attendees=True
        )
        cls.interested = User.objects.create_user(
            "cardfan", "cardfan@example.com", share_profile_with_attendees=True
        )
        cls.registered = User.objects.create_user(
            "cardguest", "cardguest@example.com", share_profile_with_attendees=True
        )
        EventInterest.objects.create(event=cls.event, user=cls.viewer)
        EventInterest.objects.create(event=cls.event, user=cls.interested)
        Registration.objects.create(event=cls.event, user=cls.registered)

    def setUp(self):
        self.client.force_login(self.viewer)
        self.detail_url = reverse("event_detail", args=[self.event.pk])

    def card_actions(self, html, username):
        """Return the action area of the hover card for ``username``."""
        card = html[html.index(f"@{username}") :]
        card = card[card.index('class="attendee-card-actions"') :]
        return card[: card.index("</div>")]

    def test_interested_and_registered_cards_only_link_to_the_profile(self):
        """No messaging form in either group, just See Details."""
        html = self.client.get(self.detail_url).content.decode()

        for member in (self.interested, self.registered):
            with self.subTest(member=member.username):
                actions = self.card_actions(html, member.username)
                profile_url = reverse("public_profile", args=[member.username])
                self.assertIn(f'href="{profile_url}"', actions)
                self.assertIn("See Details", actions)
                self.assertNotIn("<form", actions)
                self.assertNotIn("<textarea", actions)
                self.assertNotIn("Contact", actions)

    def test_profile_shows_a_message_button_for_both_groups(self):
        """See Details leads to a profile with a message button."""
        for member in (self.interested, self.registered):
            with self.subTest(member=member.username):
                page = self.client.get(
                    reverse("public_profile", args=[member.username])
                )
                self.assertContains(page, "Request Message")
                self.assertContains(page, reverse("message_user", args=[member.pk]))

    def test_open_contact_lets_people_message_directly(self):
        """Allow direct contact: sending opens the conversation straight away."""
        self.registered.contact_permission = ContactPermission.OPEN
        self.registered.save(update_fields=["contact_permission"])

        response = self.client.post(
            reverse("message_user", args=[self.registered.pk]),
            {"event": self.event.pk, "message": "Hi there"},
        )

        conversation = Conversation.objects.get()
        self.assertRedirects(
            response,
            reverse("conversation", args=[conversation.pk]),
            fetch_redirect_response=False,
        )
        self.assertEqual(
            ContactRequest.objects.get().status, ContactRequest.Status.ACCEPTED
        )

    def test_approval_required_sends_a_request_to_accept_or_decline(self):
        """Require approval: sending creates a pending request, no chat yet."""
        self.interested.contact_permission = ContactPermission.APPROVAL_REQUIRED
        self.interested.save(update_fields=["contact_permission"])

        self.client.post(
            reverse("message_user", args=[self.interested.pk]),
            {"event": self.event.pk, "message": "Hi there"},
        )

        request = ContactRequest.objects.get()
        self.assertEqual(request.status, ContactRequest.Status.PENDING)
        self.assertFalse(Conversation.objects.exists())

        self.client.force_login(self.interested)
        self.client.post(
            reverse("respond_to_contact_request", args=[request.pk, "accept"])
        )
        request.refresh_from_db()
        self.assertEqual(request.status, ContactRequest.Status.ACCEPTED)
        response = self.client.get(reverse("message_user", args=[self.viewer.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Conversation.objects.exists())


class ProfileMessageButtonTests(TestCase):
    """Send Message for direct contact, Request Message otherwise (#191)."""

    @classmethod
    def setUpTestData(cls):
        start = timezone.now() + timedelta(days=3)
        cls.event = Event.objects.create(
            guid="profile-button-event",
            title="Harbor Cleanup",
            content_hash="h" * 64,
            start_time=start,
            end_time=start + timedelta(hours=2),
            status=Event.Status.UPCOMING,
        )
        cls.sender = User.objects.create_user(
            "btnsender", "btnsender@example.com", share_profile_with_attendees=True
        )
        cls.member = User.objects.create_user(
            "btnmember", "btnmember@example.com", share_profile_with_attendees=True
        )
        EventInterest.objects.create(event=cls.event, user=cls.sender)
        Registration.objects.create(event=cls.event, user=cls.member)

    def setUp(self):
        self.client.force_login(self.sender)
        self.profile_url = reverse("public_profile", args=[self.member.username])
        self.message_url = reverse("message_user", args=[self.member.pk])

    def set_permission(self, permission):
        self.member.contact_permission = permission
        self.member.save(update_fields=["contact_permission"])

    def test_direct_contact_profile_shows_send_message_form(self):
        self.set_permission(ContactPermission.OPEN)
        page = self.client.get(self.profile_url)
        self.assertContains(page, 'name="direct"')
        self.assertContains(page, "Send Message")
        self.assertNotContains(page, "Request Message")

    def test_send_message_opens_the_chat_without_an_introduction(self):
        self.set_permission(ContactPermission.OPEN)
        response = self.client.post(self.message_url, {"direct": "1"})
        conversation = Conversation.objects.get()
        self.assertRedirects(
            response,
            reverse("conversation", args=[conversation.pk]),
            fetch_redirect_response=False,
        )
        contact = ContactRequest.objects.get()
        self.assertEqual(contact.status, ContactRequest.Status.ACCEPTED)
        self.assertEqual(contact.message, "")

    def test_approval_profile_shows_request_message_link(self):
        self.set_permission(ContactPermission.APPROVAL_REQUIRED)
        page = self.client.get(self.profile_url)
        self.assertContains(page, "Request Message")
        self.assertContains(page, f'href="{self.message_url}"')
        self.assertNotContains(page, 'name="direct"')
        self.assertContains(self.client.get(self.message_url), "Send Contact Request")

    def test_direct_post_cannot_skip_approval(self):
        """A crafted direct POST to an approval-only member creates nothing."""
        self.set_permission(ContactPermission.APPROVAL_REQUIRED)
        response = self.client.post(self.message_url, {"direct": "1"})
        self.assertRedirects(response, self.message_url, fetch_redirect_response=False)
        self.assertFalse(ContactRequest.objects.exists())
        self.assertFalse(Conversation.objects.exists())

    def test_direct_post_needs_a_shared_upcoming_event(self):
        self.set_permission(ContactPermission.OPEN)
        EventInterest.objects.filter(user=self.sender).delete()
        self.client.post(self.message_url, {"direct": "1"})
        self.assertFalse(Conversation.objects.exists())

    def test_accepted_contact_shows_send_message_link(self):
        ContactRequest.objects.create(
            event=self.event,
            sender=self.sender,
            recipient=self.member,
            status=ContactRequest.Status.ACCEPTED,
        )
        page = self.client.get(self.profile_url)
        self.assertContains(page, f'href="{self.message_url}">Send Message')
        self.assertNotContains(page, "Request Message")

    def test_sender_is_notified_when_request_is_accepted(self):
        self.set_permission(ContactPermission.APPROVAL_REQUIRED)
        self.client.post(self.message_url, {"event": self.event.pk, "message": "Hi"})
        request = ContactRequest.objects.get()
        self.client.force_login(self.member)
        self.client.post(
            reverse("respond_to_contact_request", args=[request.pk, "accept"])
        )
        notice = Notification.objects.get(recipient=self.sender)
        self.assertIn("accepted your contact request", notice.subject)
        self.assertIn("You can now message", notice.body)

    def test_declining_does_not_notify_the_sender(self):
        self.set_permission(ContactPermission.APPROVAL_REQUIRED)
        self.client.post(self.message_url, {"event": self.event.pk, "message": "Hi"})
        request = ContactRequest.objects.get()
        self.client.force_login(self.member)
        self.client.post(
            reverse("respond_to_contact_request", args=[request.pk, "decline"])
        )
        self.assertFalse(Notification.objects.filter(recipient=self.sender).exists())
