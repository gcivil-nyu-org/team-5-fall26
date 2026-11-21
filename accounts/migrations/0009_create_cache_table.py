"""Create the shared database cache table used for login lockouts (#180)."""

from django.core.management import call_command
from django.db import migrations


def create_cache_table(apps, schema_editor):
    """Create the cache table if it does not exist yet."""
    call_command("createcachetable", database=schema_editor.connection.alias)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0008_user_profile_photo_crop")]

    operations = [
        migrations.RunPython(create_cache_table, migrations.RunPython.noop),
    ]
