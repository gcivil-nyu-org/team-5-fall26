"""Forms for creating user accounts and logging in."""

from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

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


class LoginForm(AuthenticationForm):
    """Login form that takes an email address or a username, and a password."""

    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": (
            "Please enter a correct email or username and password. "
            "Note that the password is case-sensitive."
        ),
    }

    def __init__(self, request=None, *args, **kwargs):
        """Relabel the username field and let it fit a full email address."""
        super().__init__(request, *args, **kwargs)
        field = self.fields["username"]
        field.label = "Email or username"
        field.max_length = User._meta.get_field("email").max_length
        field.widget.attrs["maxlength"] = field.max_length
