"""Views for user account pages."""

import hashlib
import time
from urllib.parse import urlencode
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth import views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView
from django.contrib.messages.views import SuccessMessageMixin
from django.core.cache import cache
from django.db.models import Q
from django.http import Http404
from django.shortcuts import render, resolve_url
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.generic import CreateView, DetailView, UpdateView

from events.contact_services import shared_upcoming_events
from events.models import ContactRequest, Event, EventInterest
from events.ratings import host_rating_summary, latest_host_comments
from events.similar_interests import public_match_for_event
from events.photos import gallery_context
from .ban_services import get_active_ban
from .forms import AccountSettingsForm, LoginForm, RegistrationForm
from .models import ContactPermission


class AccountSettingsView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    """Allow signed-in users to edit only their own account's profile."""

    form_class = AccountSettingsForm
    template_name = "accounts/settings.html"
    success_url = reverse_lazy("account_settings")
    success_message = "Your account settings have been saved."

    def get_object(self, queryset=None):
        """Select the account from the session, never from submitted identifiers."""
        return self.request.user

    def get_context_data(self, **kwargs):
        """Keep saved settings readable while an active ban prevents editing."""
        context = super().get_context_data(**kwargs)
        context["active_ban"] = get_active_ban(self.object)
        interest_labels = dict(AccountSettingsForm.INTEREST_CHOICES)
        context["interest_categories"] = [
            interest_labels.get(value, value) for value in (self.object.interests or [])
        ]
        return context


@method_decorator(never_cache, name="dispatch")
class PublicProfileView(LoginRequiredMixin, DetailView):
    """Display a lightweight community profile."""

    model = get_user_model()
    template_name = "accounts/public_profile.html"
    context_object_name = "profile_user"
    slug_field = "username"
    slug_url_kwarg = "username"

    def get(self, request, *args, **kwargs):
        """Check whether the profile exists and can be viewed."""
        profile_user = (
            get_user_model().objects.filter(username=kwargs["username"]).first()
        )

        if profile_user is None:
            raise Http404("User not found")

        # Members can always view their own profile.
        if (
            not profile_user.share_profile_with_attendees
            and profile_user.pk != request.user.pk
        ):
            return render(
                request,
                "accounts/profile_unavailable.html",
                status=200,
            )

        self.object = profile_user
        context = self.get_context_data(object=self.object)
        return self.render_to_response(context)

    def get_context_data(self, **kwargs):
        """Provide real profile information from existing event data."""
        context = super().get_context_data(**kwargs)
        profile_user = self.object
        context["profile_ban"] = get_active_ban(profile_user)
        context.update(gallery_context(self.request, uploader=profile_user))
        context["can_upload_photos"] = (
            profile_user.pk == self.request.user.pk and context["profile_ban"] is None
        )

        # Ratings from attendees of events this member hosted.
        context["is_host"] = profile_user.hosted_events.exists()
        if context["is_host"]:
            context["host_rating"] = host_rating_summary(profile_user)
            context["host_comments"] = latest_host_comments(profile_user)

        # Upcoming events the member marked as Interested.
        context["upcoming_events"] = (
            Event.objects.filter(
                interests__user=profile_user,
                status=Event.Status.UPCOMING,
                start_time__gte=timezone.now(),
            )
            .distinct()
            .order_by("start_time", "title")
        )

        # Derive interests from categories of events the member is
        # interested in. No separate interest tags are assumed.

        interest_labels = dict(AccountSettingsForm.INTEREST_CHOICES)
        context["interest_categories"] = [
            interest_labels.get(value, value)
            for value in (profile_user.interests or [])
        ]

        if profile_user.pk != self.request.user.pk:
            pair_requests = ContactRequest.objects.filter(
                Q(sender=self.request.user, recipient=profile_user)
                | Q(sender=profile_user, recipient=self.request.user)
            )
            has_accepted_request = pair_requests.filter(
                status=ContactRequest.Status.ACCEPTED
            ).exists()
            has_pending_request = pair_requests.filter(
                status=ContactRequest.Status.PENDING
            ).exists()
            has_shared_upcoming_event = shared_upcoming_events(
                self.request.user, profile_user
            ).exists()
            # Banned recipients cannot receive new invitations, but an
            # already-approved conversation should remain reachable.
            context["can_message"] = has_accepted_request or (
                context["profile_ban"] is None
                and (has_pending_request or has_shared_upcoming_event)
            )
            # Only show a verified related label when the viewer actually
            # marked the source event as Interested, and the profile owner
            # still allows similar-event discovery.
            related_label = None
            from_event = self.request.GET.get("from_event", "")
            if (
                get_active_ban(self.request.user) is None
                and from_event.isascii()
                and from_event.isdecimal()
                and len(from_event) < 18
            ):
                event = Event.objects.filter(pk=int(from_event)).first()
                if event is not None:
                    viewer_interested = EventInterest.objects.filter(
                        event=event,
                        user=self.request.user,
                        status=EventInterest.Status.INTERESTED,
                    ).exists()
                    if viewer_interested:
                        related_label = public_match_for_event(
                            event, profile_user, self.request.user
                        )
            context["similar_interest_label"] = related_label
            # Open chats and direct-contact members get Send Message;
            # everyone else gets Request Message (#191).
            context["has_accepted_contact"] = has_accepted_request
            context["direct_contact"] = (
                profile_user.contact_permission == ContactPermission.OPEN
                and has_shared_upcoming_event
                and not has_pending_request
            )
        else:
            context["can_message"] = False
            context["similar_interest_label"] = None

        # No past_events or attendance statistics are added
        # because actual attendance data has not been confirmed.

        return context


# Lockout configuration
LOCKOUT_THRESHOLD = 5
LOCKOUT_DURATION_SECONDS = 10 * 60  # 10 minutes lockout
CACHE_KEY_ATTEMPTS = "login_attempts:"
CACHE_KEY_LOCK_EXPIRY = "login_lock_expiry:"
SESSION_LIFESPAN_SECONDS = 48 * 60 * 60  # 48 hours idle sliding expiry


class RegisterView(SuccessMessageMixin, CreateView):
    """Create an account, then send the new user to the login page."""

    form_class = RegistrationForm
    template_name = "accounts/register.html"
    success_message = "Welcome, %(name)s! Your account has been created. Please log in."

    def get_return_url(self):
        """Keep a safe same-site return destination across account creation."""
        target = self.request.POST.get("next", self.request.GET.get("next", "")).strip()
        if url_has_allowed_host_and_scheme(
            target,
            allowed_hosts={self.request.get_host()},
            require_https=self.request.is_secure(),
        ):
            return target
        return ""

    def get_context_data(self, **kwargs):
        """Preserve the return destination in the signup form and login link."""
        context = super().get_context_data(**kwargs)
        context["next"] = self.get_return_url()
        context["login_url"] = self.get_success_url()
        context["google_oauth_enabled"] = settings.GOOGLE_OAUTH_ENABLED
        return context

    def get_success_url(self):
        """Return to login with the original safe destination, if supplied."""
        login_url = resolve_url(settings.LOGIN_URL)
        target = self.get_return_url()
        if target:
            return f"{login_url}?{urlencode({'next': target})}"
        return login_url

    def get_success_message(self, cleaned_data):
        """Greet the new user by display name, or by username if they left it blank."""
        return self.success_message % {"name": self.object.get_display_name()}


class CustomLoginView(LoginView):
    """
    Custom login view supporting username/email login, brute force lockout,
    and 48-hour sliding idle session expiration.

    After successful login, redirects to landing page (landing route).
    After 5 consecutive failed login attempts, blocks login for 10 minutes.
    Lock expiry timestamp is stored in cache so countdown persists on page refresh.
    Session expires after 48 hours of user inactivity (sliding refresh on every
    request).
    Passes lock expiry timestamp and locked login identifier to template for frontend
    countdown.
    Welcome message is shown on landing page AFTER login, not on login page.
    """

    template_name = "accounts/login.html"
    redirect_authenticated_user = True
    success_url = reverse_lazy("landing")
    form_class = LoginForm

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.lock_expiry_timestamp = None
        self.locked_identifier = None
        self.locked_subjects = set()

    @staticmethod
    def _account_subject(user_pk) -> str:
        """Return the subject failed attempts are counted against for an account."""
        return f"user:{user_pk}"

    def _matching_user_ids(self, identifier: str) -> list[int]:
        """
        Return the accounts whose username or email matches the login text.

        Text with a NUL character can't match any account, and PostgreSQL
        rejects it in a query, so it is never looked up.
        """
        if not identifier or "\x00" in identifier:
            return []
        return list(
            get_user_model()
            ._default_manager.filter(
                Q(username__iexact=identifier) | Q(email__iexact=identifier)
            )
            .order_by("pk")
            .values_list("pk", flat=True)
        )

    def _lock_subjects(self, login_identifier: str) -> list[str]:
        """
        Return what failed attempts are counted against for this login text.

        Login matches usernames and emails regardless of case, so attempts
        are counted per matching account. Typing "Alice", "alice" or the
        account's email all share one counter (#180). Text that matches no
        account is counted by its lowercased form.

        Args:
            login_identifier: username or email entered in login form
        Returns:
            list of subject strings, one per matching account
        """
        identifier = login_identifier.strip()
        subjects = [
            self._account_subject(pk) for pk in self._matching_user_ids(identifier)
        ]
        return subjects or [f"login:{identifier.casefold()}"]

    @staticmethod
    def _cache_key(prefix: str, subject: str) -> str:
        """Build a fixed-length cache key, so any typed text is safe to use."""
        digest = hashlib.sha256(subject.encode()).hexdigest()
        return f"{prefix}{digest}"

    def _get_attempt_key(self, subject: str) -> str:
        """
        Generate cache key for counting failed login attempts.

        Args:
            subject: an account or login text from ``_lock_subjects``
        Returns:
            prefixed cache key string
        """
        return self._cache_key(CACHE_KEY_ATTEMPTS, subject)

    def _get_lock_expiry_key(self, subject: str) -> str:
        """
        Generate cache key that stores the absolute lock expiry timestamp.

        Args:
            subject: an account or login text from ``_lock_subjects``
        Returns:
            prefixed cache key string
        """
        return self._cache_key(CACHE_KEY_LOCK_EXPIRY, subject)

    def _active_locks(self, subjects: list[str]) -> dict[str, float]:
        """Return the lock expiry still in force for each locked subject."""
        now = time.time()
        locks = {}
        for subject in subjects:
            expiry = cache.get(self._get_lock_expiry_key(subject))
            if expiry and expiry > now:
                locks[subject] = expiry
        return locks

    def dispatch(self, request, *args, **kwargs):
        """
        Intercept login request before credential validation.
        Read saved lock expiry timestamp from cache.
        If still locked, render login page with countdown context.
        """
        self.lock_expiry_timestamp = None
        self.locked_identifier = None
        self.locked_subjects = set()
        if request.method == "POST":
            raw_username = request.POST.get("username", "").strip()
            subjects = self._lock_subjects(raw_username)
            locks = self._active_locks(subjects)
            # One login can match a username and another user's email. If
            # only some of those accounts are locked, the others can still
            # log in: the locked ones are left out of the password check
            # (see EmailOrUsernameBackend), so they reveal nothing.
            self.locked_subjects = set(locks)
            request.login_locked_user_ids = {
                pk
                for pk in self._matching_user_ids(raw_username)
                if self._account_subject(pk) in self.locked_subjects
            }
            if locks and len(locks) == len(subjects):
                # Reopen the form as soon as any matching account unlocks.
                self.lock_expiry_timestamp = min(locks.values())
                self.locked_identifier = raw_username
                context = self.get_context_data()
                context["form"] = self.get_form()
                # Pass locked account identifier to template
                context["locked_identifier"] = self.locked_identifier
                return render(request, self.template_name, context)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        """
        Pass lock expiry timestamp and locked identifier to
        template context for frontend countdown.
        """
        context = super().get_context_data(**kwargs)
        context["google_oauth_enabled"] = settings.GOOGLE_OAUTH_ENABLED
        context["lock_expiry"] = self.lock_expiry_timestamp
        context["locked_identifier"] = self.locked_identifier
        return context

    def form_valid(self, form):
        """
        Run when login credentials are correct.
        Clear failed attempt counter and lock record from cache.
        Set sliding session timeout for 48 hours.
        """
        # Clear failed attempts and locks for the account that logged in only.
        # Another account matching the same text keeps its own count.
        subject = self._account_subject(form.get_user().pk)
        cache.delete(self._get_attempt_key(subject))
        cache.delete(self._get_lock_expiry_key(subject))

        # 48h sliding session expiry
        self.request.session.set_expiry(SESSION_LIFESPAN_SECONDS)

        messages.success(self.request, "Welcome back! You are now logged in.")
        return super().form_valid(form)

    def form_invalid(self, form):
        """
        Handle failed login submission.
        Increment failure counter and apply lockout after reaching threshold.
        Pass remaining attempts, lock expiry and locked identifier to the template.

        Args:
            form: LoginForm with invalid credentials
        Returns:
            HttpResponse: rendered login page with error context
        """
        username_input = form.cleaned_data.get("username", "").strip()
        if not username_input:
            username_input = self.request.POST.get("username", "").strip()

        subjects = self._lock_subjects(username_input)
        attempts_left = []
        for subject in subjects:
            if subject in self.locked_subjects:
                # Already locked and left out of the password check.
                continue
            attempt_key = self._get_attempt_key(subject)
            attempts = cache.get(attempt_key, 0) + 1
            cache.set(attempt_key, attempts, LOCKOUT_DURATION_SECONDS)
            if attempts >= LOCKOUT_THRESHOLD:
                cache.set(
                    self._get_lock_expiry_key(subject),
                    time.time() + LOCKOUT_DURATION_SECONDS,
                    LOCKOUT_DURATION_SECONDS,
                )
            else:
                attempts_left.append(LOCKOUT_THRESHOLD - attempts)

        # Lock the form only when no matching account can still log in, and
        # reopen it as soon as the first of them can.
        locks = self._active_locks(subjects)
        if len(locks) == len(subjects):
            self.lock_expiry_timestamp = min(locks.values())
            self.locked_identifier = username_input
            remaining_attempts = 0
        else:
            self.lock_expiry_timestamp = None
            self.locked_identifier = None
            remaining_attempts = min(attempts_left, default=LOCKOUT_THRESHOLD)
        current_attempts = LOCKOUT_THRESHOLD - remaining_attempts

        context = self.get_context_data(form=form)
        context["remaining_attempts"] = remaining_attempts
        context["current_attempts"] = current_attempts
        return render(self.request, self.template_name, context)


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
