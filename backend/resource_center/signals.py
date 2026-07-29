from django.db.models.signals import post_save
from django.dispatch import receiver

from ops.models import K8sCluster
from ops.models import Alert


@receiver(post_save, sender=K8sCluster)
def schedule_k8s_resource_discovery(sender, instance, **kwargs):
    from .discovery import ensure_k8s_discovery_source

    ensure_k8s_discovery_source(instance)


@receiver(post_save, sender=Alert)
def match_alert_resource(sender, instance, created, **kwargs):
    if instance.matched_resource_id or (not created and instance.resource_match_status != 'unmatched'):
        return
    from .alert_matching import attach_alert_resource

    attach_alert_resource(instance)
