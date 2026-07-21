import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections

from ops.alert_analysis import enqueue_missing_active_analyses, run_due_alert_analyses


class Command(BaseCommand):
    help = 'Run the dedicated Agent-4 alert analysis queue worker.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Process one queue batch and exit')
        parser.add_argument('--interval', type=int, default=None, help='Polling interval in seconds')
        parser.add_argument('--limit', type=int, default=5, help='Maximum analyses to process per batch')

    def handle(self, *args, **options):
        interval = int(options.get('interval') or getattr(settings, 'ALERT_ANALYSIS_POLL_SECONDS', 5))
        limit = max(1, int(options.get('limit') or 5))
        if options.get('once'):
            repair = enqueue_missing_active_analyses(limit=max(limit, 100))
            result = run_due_alert_analyses(limit=limit)
            self.stdout.write(self.style.SUCCESS(
                f"analysis scan complete: repaired={repair['queued']}, processed={result['processed']}, "
                f"completed={result['completed']}, partial={result['partial']}, "
                f"retried={result['retried']}, failed={result['failed']}"
            ))
            return

        self.stdout.write(self.style.SUCCESS(
            f'alert analysis worker started, interval={interval}s, batch_limit={limit}'
        ))
        while True:
            close_old_connections()
            try:
                enqueue_missing_active_analyses(limit=100)
                run_due_alert_analyses(limit=limit)
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f'alert analysis worker scan failed: {exc}'))
            finally:
                close_old_connections()
            time.sleep(max(interval, 2))
