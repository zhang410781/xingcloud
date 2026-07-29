from django.apps import AppConfig


class ResourceCenterConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'resource_center'

    def ready(self):
        from . import signals  # noqa: F401
