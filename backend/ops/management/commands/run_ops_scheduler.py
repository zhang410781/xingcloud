from django.core.management.base import BaseCommand

from ops.ops_scheduler import run_ops_scheduler_loop, run_ops_scheduler_once


class Command(BaseCommand):
    help = 'Run Xing-Cloud unified ops scheduler: host tasks, datasource health checks, and alert rule evaluation.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Run one scheduler scan and exit')
        parser.add_argument('--interval', type=int, default=None, help='Polling interval in seconds')
        parser.add_argument('--limit', type=int, default=20, help='Maximum host schedules to trigger per scan')
        parser.add_argument('--alert-rule-limit', type=int, default=100, help='Maximum alert rules to evaluate per scan')
        parser.add_argument('--actor', type=str, default='system-scheduler', help='Actor name for scheduler generated records')
        parser.add_argument('--skip-health', action='store_true', help='Skip datasource health checks in once mode')

    def handle(self, *args, **options):
        limit = int(options.get('limit') or 20)
        alert_rule_limit = int(options.get('alert_rule_limit') or 100)
        actor = options.get('actor') or 'system-scheduler'

        if options.get('once'):
            result = run_ops_scheduler_once(
                limit=limit,
                actor=actor,
                alert_rule_limit=alert_rule_limit,
                include_health=not options.get('skip_health'),
            )
            self.stdout.write(self.style.SUCCESS(
                'scan complete: '
                f"host_due={result['host_tasks'].get('due_count', 0)}, "
                f"alerts_scanned={result['alert_rules'].get('scanned', 0)}, "
                f"health_metrics={result['datasource_health'].get('metrics', 0)}, "
                f"health_logs={result['datasource_health'].get('logs', 0)}"
            ))
            return

        self.stdout.write(self.style.SUCCESS(
            f'ops scheduler started, interval={options.get("interval") or "settings default"}s, '
            f'host_limit={limit}, alert_rule_limit={alert_rule_limit}'
        ))
        run_ops_scheduler_loop(
            interval_seconds=options.get('interval'),
            limit=limit,
            actor=actor,
            alert_rule_limit=alert_rule_limit,
        )
