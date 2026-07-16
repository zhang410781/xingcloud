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
    """Compatibility constants for callers left after the event-wall removal.

    Event recording is intentionally a no-op in this module.  Keeping the
    value constants prevents otherwise unrelated actions (for example a K8S
    deployment) from failing while they prepare an event payload.
    """
    SEVERITY_INFO = 'info'
    SEVERITY_WARNING = 'warning'
    SEVERITY_ERROR = 'error'
    SEVERITY_DANGER = 'danger'

    RESULT_PENDING = 'pending'
    RESULT_SUCCESS = 'success'
    RESULT_FAILED = 'failed'
    RESULT_PARTIAL = 'partial'
    RESULT_REJECTED = 'rejected'

    SOURCE_ASYNC = 'async'
    SOURCE_SCHEDULER = 'scheduler'
    SOURCE_EXTERNAL = 'external'
    SOURCE_SEED = 'seed'

    ACTOR_SYSTEM = 'system'
    ACTOR_USER = 'user'


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
