from django.apps import AppConfig


class CmdbConfig(AppConfig):
    name = 'cmdb'

    def ready(self):
        from django.conf import settings

        if settings.ENABLE_LEGACY_CMDB_SYNC:
            from . import signals  # noqa: F401
