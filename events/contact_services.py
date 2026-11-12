"""Shared contact-request workflows."""

from django.db import transaction
from django.db.models import Q

from accounts.ban_services import get_active_ban, require_unbanned_user
from accounts.models import ContactPermission, User

from .models import ContactRequest, Conversation, EventInterest
from .notifications import notify_contact_request
from .similar_interests import available_event, public_match_for_event


def create_contact_request(
    event,
    sender,
    recipient,
    message,
    notification_sender=notify_contact_request,
):
    """Create one eligible event contact request, or return an existing one."""
    with transaction.atomic():
        # Lock both accounts in a stable order so concurrent requests cannot
        # bypass the one-pending-request-per-pair rule.
        locked_users = {
            user.pk: user
            for user in User.objects.select_for_update(no_key=True)
            .filter(pk__in=(sender.pk, recipient.pk))
            .order_by("pk")
        }
        sender = locked_users[sender.pk]
        recipient = locked_users[recipient.pk]
        require_unbanned_user(sender)
        if (
            not available_event(event)
            or sender.pk == recipient.pk
            or not recipient.is_active
            or get_active_ban(recipient) is not None
            or not recipient.share_profile_with_attendees
            or not EventInterest.objects.filter(
                event=event,
                user=sender,
                status=EventInterest.Status.INTERESTED,
            ).exists()
        ):
            return None, False

        # Same-event connections remain available as before. Different-event
        # requests require a verified category match and explicit discovery
        # consent; the posted event id alone is never authorization.
        shares_event = EventInterest.objects.filter(
            event=event,
            user=recipient,
            status=EventInterest.Status.INTERESTED,
        ).exists()
        if not shares_event and not public_match_for_event(event, recipient):
            return None, False

        # A pending or accepted request belongs to the pair, not to a
        # particular event. Checking both directions also prevents spam.
        existing = (
            ContactRequest.objects.filter(
                Q(sender=sender, recipient=recipient)
                | Q(sender=recipient, recipient=sender),
                status__in=(
                    ContactRequest.Status.PENDING,
                    ContactRequest.Status.ACCEPTED,
                ),
            )
            .order_by("-created_at", "-pk")
            .first()
        )
        if existing:
            return existing, False

        contact_request = ContactRequest.objects.create(
            event=event,
            sender=sender,
            recipient=recipient,
            message=message,
            status=(
                ContactRequest.Status.ACCEPTED
                if recipient.contact_permission == ContactPermission.OPEN
                else ContactRequest.Status.PENDING
            ),
        )
        notification_sender(contact_request)
        if contact_request.status == ContactRequest.Status.ACCEPTED:
            Conversation.get_or_create_for_users(sender, recipient)

    return contact_request, True
