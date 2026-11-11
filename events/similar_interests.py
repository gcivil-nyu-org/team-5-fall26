"""Find opted-in people interested in events with related categories.

Only public event-category labels are used as explanations. User email,
private messages, and attendance details are never included in suggestions.
"""

from django.db.models import Q

from .filters import CATEGORY_GROUPS, CATEGORY_NAMES, CATEGORY_SEPARATOR
from .models import Event, EventInterest, Registration

DEFAULT_SUGGESTION_LIMIT = 6


def category_tags(categories):
    """Split the NYC Parks category string into nonempty public labels."""
    return [tag.strip() for tag in (categories or "").split("|") if tag.strip()]


def category_terms(tags):
    """Include related labels in the same existing event-filter category group."""
    terms = set(tags)
    normalized = {tag.casefold() for tag in tags}

    for slug, _, _ in CATEGORY_GROUPS:
        members = CATEGORY_NAMES[slug]
        if normalized.intersection(name.casefold() for name in members):
            terms.update(members)

    return sorted(terms)


def category_query(field, label):
    """Match a complete category in a delimiter-separated database field."""
    separator = CATEGORY_SEPARATOR
    return (
        Q(**{f"{field}__iexact": label})
        | Q(**{f"{field}__istartswith": label + separator})
        | Q(**{f"{field}__iendswith": separator + label})
        | Q(**{f"{field}__icontains": separator + label + separator})
    )


def shared_interest_label(source_tags, other_categories):
    """Describe the actual category overlap without revealing private data."""
    other_tags = category_tags(other_categories)
    other_names = {name.casefold() for name in other_tags}

    for tag in source_tags:
        if tag.casefold() in other_names:
            return tag

    source_names = {name.casefold() for name in source_tags}
    for slug, label, _ in CATEGORY_GROUPS:
        members = {name.casefold() for name in CATEGORY_NAMES[slug]}
        if source_names & members and other_names & members:
            return label

    return None


def find_similar_interest_users(event, viewer=None, limit=DEFAULT_SUGGESTION_LIMIT):
    """Return unique opted-in users interested in other upcoming related events.

    Users on this event's interested or registered lists are left out to avoid
    duplicate suggestions. Both public-profile sharing and the separate
    similar-event discovery consent must be enabled.
    """
    tags = category_tags(event.categories)
    if event.status != Event.Status.UPCOMING or not tags or limit < 1:
        return []

    matching_categories = Q()
    for label in category_terms(tags):
        matching_categories |= category_query("event__categories", label)

    same_event_interests = EventInterest.objects.filter(event=event).values("user_id")
    same_event_registrations = Registration.objects.filter(event=event).values(
        "user_id"
    )
    candidates = (
        EventInterest.objects.filter(
            matching_categories,
            status=EventInterest.Status.INTERESTED,
            event__status=Event.Status.UPCOMING,
            user__is_active=True,
            user__share_profile_with_attendees=True,
            user__discoverable_for_similar_events=True,
        )
        .exclude(event=event)
        .exclude(user_id__in=same_event_interests)
        .exclude(user_id__in=same_event_registrations)
        .select_related("user", "event")
        .order_by("user__display_name", "user__username", "event__start_time", "pk")
    )
    if viewer is not None and viewer.is_authenticated:
        candidates = candidates.exclude(user=viewer)

    suggestions = []
    seen_users = set()
    for interest in candidates.iterator(chunk_size=200):
        if interest.user_id in seen_users:
            continue
        label = shared_interest_label(tags, interest.event.categories)
        if label is None:
            continue
        seen_users.add(interest.user_id)
        suggestions.append({"user": interest.user, "shared_interest": label})
        if len(suggestions) >= limit:
            break

    return suggestions
