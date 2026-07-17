from django.core.management.base import BaseCommand
from django.db import transaction

from ops.alert_rule_presets import ensure_builtin_alert_rule_templates
from ops.dashboard_presets import ensure_builtin_dashboards
from ops.models import AlertRule, ObservabilityDashboard


class Command(BaseCommand):
    help = 'Create or update built-in observability dashboards and alert rule templates.'

    def handle(self, *args, **options):
        with transaction.atomic():
            ensure_builtin_dashboards()
            ensure_builtin_alert_rule_templates()

        dashboard_count = ObservabilityDashboard.objects.filter(is_builtin=True).count()
        template_count = AlertRule.objects.filter(is_template=True).count()
        self.stdout.write(
            self.style.SUCCESS(
                f'Observability presets ready: dashboards={dashboard_count}, alert_templates={template_count}'
            )
        )
