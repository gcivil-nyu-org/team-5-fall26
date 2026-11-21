"""The login lockout can't be dodged by retyping the account differently (#180)."""

from django.conf import settings
from django.contrib.auth import SESSION_KEY
from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from accounts.views import LOCKOUT_THRESHOLD, CustomLoginView

PASSWORD = "Tr1cky-Passphrase!"


class LockoutBypassTests(TestCase):
    """Failed attempts count against the account, however it is typed."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("alice", "alice@example.com", PASSWORD)

    def setUp(self):
        cache.clear()
        self.url = reverse("login")

    def fail(self, identifier, times=1):
        """Submit a wrong password ``times`` times using ``identifier``."""
        for _ in range(times):
            self.client.post(self.url, {"username": identifier, "password": "wrong"})

    def log_in(self, identifier):
        """Try the correct password and return whether a session was created."""
        self.client.post(self.url, {"username": identifier, "password": PASSWORD})
        return SESSION_KEY in self.client.session

    def test_other_capitalization_stays_locked(self):
        """Five failures lock the account for every capitalization of the email."""
        self.fail("alice@example.com", LOCKOUT_THRESHOLD)

        for spelling in ("ALICE@EXAMPLE.COM", "Alice@Example.com", "alice@example.com"):
            with self.subTest(spelling=spelling):
                self.assertFalse(self.log_in(spelling))

    def test_username_and_email_share_one_counter(self):
        """Failures spread across the username and email still add up."""
        self.fail("alice", 2)
        self.fail("ALICE", 1)
        self.fail("Alice@Example.com", 2)

        self.assertFalse(self.log_in("alice"))
        response = self.client.post(self.url, {"username": "alice", "password": "x"})
        self.assertIsNotNone(response.context["lock_expiry"])

    def test_remaining_attempts_count_every_spelling(self):
        """The warning reflects failures made with other spellings."""
        self.fail("alice")
        response = self.client.post(
            self.url, {"username": "ALICE@example.com", "password": "wrong"}
        )

        self.assertEqual(response.context["remaining_attempts"], LOCKOUT_THRESHOLD - 2)

    def test_success_with_any_spelling_clears_the_counter(self):
        """A correct login resets failures recorded under another spelling."""
        self.fail("ALICE", LOCKOUT_THRESHOLD - 1)
        self.assertTrue(self.log_in("alice@example.com"))
        self.client.logout()

        self.fail("alice")
        response = self.client.post(self.url, {"username": "alice", "password": "x"})
        self.assertEqual(response.context["remaining_attempts"], LOCKOUT_THRESHOLD - 2)

    def test_unknown_identifiers_are_counted_case_insensitively(self):
        """Text matching no account still shares one counter across case."""
        self.fail("nobody@example.com", LOCKOUT_THRESHOLD - 1)
        response = self.client.post(
            self.url, {"username": "NOBODY@example.com", "password": "wrong"}
        )

        self.assertIsNotNone(response.context["lock_expiry"])

    def test_cache_keys_have_a_fixed_safe_length(self):
        """Any typed text, however long or unusual, maps to a short key."""
        key = CustomLoginView()._get_attempt_key("login:" + "é <>" * 500)

        self.assertLess(len(key), 100)
        self.assertNotIn(" ", key)


class SharedCacheTests(TestCase):
    """Lockouts live in a database cache shared by every server process."""

    def test_cache_uses_the_database_table(self):
        """The default cache is the database cache created by migration 0009."""
        default = settings.CACHES["default"]

        self.assertEqual(
            default["BACKEND"], "django.core.cache.backends.db.DatabaseCache"
        )
        self.assertIn(default["LOCATION"], connection.introspection.table_names())

    def test_values_round_trip_through_the_cache(self):
        """Values written to the cache can be read back."""
        cache.set("shared-cache-check", 3, 60)

        self.assertEqual(cache.get("shared-cache-check"), 3)
