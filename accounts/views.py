"""Views for user account pages."""

from django.conf import settings
from django.contrib.auth import views as auth_views
from django.contrib.messages.views import SuccessMessageMixin
from django.shortcuts import resolve_url
from django.urls import reverse_lazy
from django.views.generic import CreateView

from .forms import LoginForm, RegistrationForm


class RegisterView(SuccessMessageMixin, CreateView):
    """Create an account, then send the new user to the login page."""

    form_class = RegistrationForm
    template_name = "accounts/register.html"
    success_message = "Welcome, %(name)s! Your account has been created. Please log in."

    def get_context_data(self, **kwargs):
        """Add the login page URL for the "Already have an account?" link."""
        context = super().get_context_data(**kwargs)
        context["login_url"] = resolve_url(settings.LOGIN_URL)
        return context

    def get_success_url(self):
        """Return the login page URL."""
        return resolve_url(settings.LOGIN_URL)

    def get_success_message(self, cleaned_data):
        """Greet the new user by display name, or by username if they left it blank."""
        return self.success_message % {"name": self.object.get_display_name()}


class LoginView(SuccessMessageMixin, auth_views.LoginView):
    """Log in with an email address or username and a password."""

    form_class = LoginForm
    template_name = "accounts/login.html"
    redirect_authenticated_user = True
    success_message = "Welcome back, %(name)s!"

    def get_success_message(self, cleaned_data):
        """Greet the user by display name, or by username if they have none."""
        return self.success_message % {"name": self.request.user.get_display_name()}


class PasswordResetView(auth_views.PasswordResetView):
    """Ask for an email address and send a password reset link to it.

    The same confirmation page is shown whether or not the address belongs to
    an account, so the form can't be used to find out who is registered.
    """

    template_name = "accounts/password_reset_form.html"
    email_template_name = "accounts/password_reset_email.txt"
    subject_template_name = "accounts/password_reset_subject.txt"
    success_url = reverse_lazy("password_reset_done")


class PasswordResetDoneView(auth_views.PasswordResetDoneView):
    """Tell the user to check their email for the reset link."""

    template_name = "accounts/password_reset_done.html"


class PasswordResetConfirmView(
    SuccessMessageMixin, auth_views.PasswordResetConfirmView
):
    """Let the user choose a new password, then send them to the login page."""

    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("login")
    success_message = "Your password has been reset. You can now log in."
