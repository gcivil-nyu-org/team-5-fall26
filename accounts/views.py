"""Views for user account pages."""
from django.conf import settings
from django.contrib.messages.views import SuccessMessageMixin
from django.shortcuts import resolve_url
from django.views.generic import CreateView

from django.contrib.auth.views import LoginView
from django.contrib import messages
from django.core.cache import cache
from django.urls import reverse_lazy
import time

from .forms import RegistrationForm

LOCKOUT_DURATION_SECONDS = 10 * 60


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


LOCKOUT_THRESHOLD = 5
LOCKOUT_DURATION_SECONDS = 10 * 60  # 10 minutes lockout
CACHE_KEY_ATTEMPTS = "login_attempts:"
CACHE_KEY_LOCK = "login_locked:"
SESSION_LIFESPAN_SECONDS = 48 * 60 * 60  # 48 hours idle expiry


class CustomLoginView(LoginView):
    """
    Custom login view supporting username/email login, brute force lockout,
    and 48-hour idle session expiration.

    After successful login, redirects to landing page (landing route).
    After 5 consecutive failed login attempts, blocks login for 10 minutes.
    Session expires after 48 hours of user inactivity.
    Passes lockout expiry timestamp to template for frontend countdown.
    """
    template_name = "accounts/login.html"
    redirect_authenticated_user = True
    success_url = reverse_lazy("landing")

    def _get_attempt_key(self, login_identifier: str) -> str:
        """
        Generate cache key for counting failed login attempts.

        Args:
            login_identifier: username or email entered in login form
        Returns:
            prefixed cache key string
        """
        return f"{CACHE_KEY_ATTEMPTS}{login_identifier}"

    def _get_lock_key(self, login_identifier: str) -> str:
        """
        Generate cache key to mark an identifier as locked out.

        Args:
            login_identifier: username or email entered in login form
        Returns:
            prefixed lock cache key string
        """
        return f"{CACHE_KEY_LOCK}{login_identifier}"

    def dispatch(self, request, *args, **kwargs):
        """
        Intercept POST login request before credential validation.
        If the identifier is locked out, show error and skip password checking.
        Store lock expiry timestamp in request for template rendering.
        """
        self.lock_expiry_timestamp = None
        if request.method == "POST":
            username_input = request.POST.get("username", "").strip()
            lock_key = self._get_lock_key(username_input)
            lock_value = cache.get(lock_key)
            if lock_value:
                self.lock_expiry_timestamp = time.time() + LOCKOUT_DURATION_SECONDS
                messages.error(
                    request,
                    "Too many failed login attempts. Please try again in 10 minutes."
                )
                return super(LoginView, self).render_to_response(self.get_context_data())
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self,** kwargs):
        """
        Pass lock expiry timestamp to template context for frontend countdown.
        """
        context = super().get_context_data(**kwargs)
        context["lock_expiry"] = self.lock_expiry_timestamp
        return context

    def form_invalid(self, form):
        """
        Handle failed login submission. Increment failure counter and apply lockout.
        Set lock expiry timestamp for frontend countdown when threshold is reached.

        Args:
            form: Django AuthenticationForm with invalid credentials
        Returns:
            HttpResponse: rendered login page with error message
        """
        username_input = form.cleaned_data.get("username", "").strip()
        attempt_key = self._get_attempt_key(username_input)
        lock_key = self._get_lock_key(username_input)

        current_attempts = cache.get(attempt_key, 0) + 1
        cache.set(attempt_key, current_attempts, LOCKOUT_DURATION_SECONDS)

        if current_attempts >= LOCKOUT_THRESHOLD:
            cache.set(lock_key, True, LOCKOUT_DURATION_SECONDS)
            self.lock_expiry_timestamp = time.time() + LOCKOUT_DURATION_SECONDS
            messages.error(
                self.request,
                "Too many failed login attempts. Please try again in 10 minutes."
            )
        else:
            remaining = LOCKOUT_THRESHOLD - current_attempts
            messages.error(
                self.request,
                f"Incorrect username/email or password. Remaining attempts: {remaining}"
            )
        return super().form_invalid(form)

    def form_valid(self, form):
        """
        Handle successful login. Clear failure counter and set 48h idle session expiry.

        Args:
            form: Django AuthenticationForm with valid credentials
        Returns:
            HttpResponseRedirect: redirect to landing page
        """
        username_input = form.cleaned_data.get("username")
        attempt_key = self._get_attempt_key(username_input)
        lock_key = self._get_lock_key(username_input)

        cache.delete(attempt_key)
        cache.delete(lock_key)
        # Session expires 48 hours after last user activity
        self.request.session.set_expiry(SESSION_LIFESPAN_SECONDS)
        return super().form_valid(form)
