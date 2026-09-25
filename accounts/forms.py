"""Forms for creating user accounts."""

from django.contrib.auth.forms import UserCreationForm

from .models import User


class RegistrationForm(UserCreationForm):
    """Sign-up form for a username, email address, display name and password.

    Django's ``UserCreationForm`` already rejects usernames that differ from an
    existing one only in case, checks the password against
    ``AUTH_PASSWORD_VALIDATORS`` and saves only the password's hash.
    """

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email", "display_name")

    def clean_email(self):
        """Normalize the email address and reject one that is already registered."""
        email = User.objects.normalize_email(self.cleaned_data["email"])
        if User.objects.filter(email__iexact=email).exists():
            raise self.instance.unique_error_message(User, ["email"])
        return email
