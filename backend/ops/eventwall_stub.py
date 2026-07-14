"""eventwall stub"""
from rest_framework import viewsets


class EventWallModelViewSetMixin:
    def eventwall_should_record(self, action, instance=None):
        return False

    def eventwall_related_resources(self, instance):
        return []

    def eventwall_metadata(self, instance, action, before=None, after=None):
        return {}


class EventRecord:
    SEVERITY_INFO = 'info'
    SEVERITY_WARNING = 'warning'
    SEVERITY_ERROR = 'error'


class EventSource:
    pass


class EventEnvironment:
    class Meta:
        app_label = 'ops'


def build_json_preview(*args, **kwargs):
    return {}


def build_resource(*args, **kwargs):
    return {}


def record_event(*args, **kwargs):
    return None
