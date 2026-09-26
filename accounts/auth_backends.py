"""Custom authentication backends for accounts app."""
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q

User = get_user_model()


class EmailOrUsernameModelBackend(ModelBackend):
    """
    Custom authentication backend allowing users to log in
    using either their username OR registered email address.

    Inherits Django's ModelBackend, maintains standard password validation.
    """
    def authenticate(self, request, username=None, password=None, **kwargs):
        """
        Authenticate user by matching input against username or email field.

        Args:
            request: Django HttpRequest object
            username: user-supplied login identifier (username or email string)
            password: user-supplied plaintext password
        Returns:
            User object if credentials valid and user is active; None otherwise
        """
        try:
            user = User.objects.get(Q(username=username) | Q(email=username))
        except User.DoesNotExist:
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
