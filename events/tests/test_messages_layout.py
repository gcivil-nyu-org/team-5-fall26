"""The site footer stays below the chat and at the bottom of message pages (#156)."""

from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.test import TestCase
from django.urls import reverse

from events.models import ContactRequest, Conversation, DirectMessage, EventInterest
from events.tests.test_messaging import make_event

User = get_user_model()


def read_css():
    """Return the messages stylesheet that lays these pages out."""
    with open(finders.find("events/messages.css"), encoding="utf-8") as css:
        return css.read()


class MessagesLayoutTests(TestCase):
    """Two attendees of one event who have agreed to message each other."""

    def setUp(self):
        self.sender = User.objects.create_user(
            "layout_sender",
            "layout_sender@example.com",
            share_profile_with_attendees=True,
        )
        self.recipient = User.objects.create_user(
            "layout_recipient",
            "layout_recipient@example.com",
            share_profile_with_attendees=True,
        )
        self.event = make_event()
        EventInterest.objects.create(event=self.event, user=self.sender)
        EventInterest.objects.create(event=self.event, user=self.recipient)
        self.client.force_login(self.sender)

    def open_conversation(self):
        """Accept contact, start a conversation and return its page HTML."""
        ContactRequest.objects.create(
            event=self.event,
            sender=self.sender,
            recipient=self.recipient,
            status=ContactRequest.Status.ACCEPTED,
        )
        one, two = sorted([self.sender, self.recipient], key=lambda user: user.pk)
        thread = Conversation.objects.create(user_one=one, user_two=two)
        DirectMessage.objects.create(
            conversation=thread, sender=self.recipient, body="See you there"
        )
        response = self.client.get(reverse("conversation", args=[thread.pk]))
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_chat_fills_the_screen_and_footer_comes_after(self):
        """The header and chat share one full-screen box; the footer is outside it."""
        html = self.open_conversation()

        viewport = html.index('<div class="chat-viewport">')
        header = html.index('class="topbar site-header"')
        chat_end = html.index("</main>")
        footer = html.index('class="site-footer"')
        self.assertLess(viewport, header)
        self.assertLess(header, chat_end)
        self.assertLess(chat_end, html.index("</div>", chat_end))
        self.assertLess(html.index("</div>", chat_end), footer)

    def test_inbox_and_message_page_keep_the_footer_at_the_bottom(self):
        """Short message pages use the full-height layout."""
        for url in (
            reverse("inbox"),
            reverse("message_user", args=[self.recipient.pk]),
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertContains(response, '<body class="messages-body">')

    def test_stylesheet_sizes_the_chat_to_the_screen(self):
        """The chat box is one screen tall, minus the phone tab bar."""
        css = read_css()

        self.assertIn(".chat-viewport {", css)
        self.assertIn("height: 100dvh;", css)
        self.assertIn("body:has(.tabbar) .chat-viewport", css)
        self.assertIn(".messages-body > .messages-page", css)


class ChatPageNoLongerPinsBodyHeightTests(TestCase):
    """The old rule squeezed the footer into the screen next to the chat."""

    def test_chat_page_body_is_not_fixed_to_the_screen_height(self):
        css = read_css()
        block = css[css.index(".chat-page {") :]
        block = block[: block.index("}")]

        self.assertNotIn("height: 100dvh", block)
        self.assertNotIn("display: flex", block)
