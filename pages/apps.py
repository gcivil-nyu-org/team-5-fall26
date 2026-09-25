"""App configuration for the public site pages."""

from django.apps import AppConfig


class PagesConfig(AppConfig):
    """Configuration for the pages app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "pages"
