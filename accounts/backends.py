"""Authentication backend that accepts an email address or a username."""

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q


class EmailOrUsernameBackend(ModelBackend):
    """Log users in with either their username or their email address.

    Both are matched regardless of case. Usernames may contain "@", so one
    login can match a username and a different user's email address; each
    match is checked against the password in turn.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        """Return the active user whose username or email and password match."""
        User = get_user_model()
        if username is None or password is None:
            return None
        users = User._default_manager.filter(
            Q(username__iexact=username) | Q(email__iexact=username)
        )
        for user in users:
            if user.check_password(password) and self.user_can_authenticate(user):
                return user
        if not users:
            # Hash anyway so the response time doesn't reveal unknown accounts.
            User().set_password(password)
        return None
