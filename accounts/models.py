"""Data models for user accounts."""

from django.contrib.auth.models import AbstractUser, UserManager
from django.contrib.auth.validators import ASCIIUsernameValidator
from django.db import models


class AccountManager(UserManager):
    """User manager that stores email addresses in lowercase."""

    @classmethod
    def normalize_email(cls, email):
        """Lowercase the whole address so emails are unique regardless of case."""
        return super().normalize_email(email).lower()


class User(AbstractUser):
    """A person who signs up with a unique username and email address.

    Builds on Django's built-in user, so login, password hashing and
    permissions work as usual. On top of that, usernames are limited to 20
    ASCII characters, each email address can only be registered once, and
    people can choose an optional display name.
    """

    username_validator = ASCIIUsernameValidator()

    username = models.CharField(
        "username",
        max_length=20,
        unique=True,
        help_text=(
            "Required. 20 characters or fewer. "
            "Unaccented letters, digits and @/./+/-/_ only."
        ),
        validators=[username_validator],
        error_messages={"unique": "A user with that username already exists."},
    )
    email = models.EmailField(
        "email address",
        unique=True,
        error_messages={
            "unique": "An account with this email address already exists.",
        },
    )
    display_name = models.CharField(
        "display name",
        max_length=50,
        blank=True,
        help_text="Optional. 50 characters or fewer.",
    )

    objects = AccountManager()

    def get_display_name(self):
        """Return the display name, or the username if no display name is set."""
        return self.display_name or self.username
