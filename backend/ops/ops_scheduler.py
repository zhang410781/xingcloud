import logging
import time

from django.conf import settings

from .alert_engine.scheduler import run_due_alert_rules
from .alert_analysis import run_due_alert_analyses
from .datasource_health import run_datasource_health_checks
from .host_task_schedules import run_due_schedules


logger = logging.getLogger(__name__)


def run_ops_scheduler_once(limit=20, actor='system-scheduler', alert_rule_limit=100, include_health=True):
    host_result = run_due_schedules(limit=limit, actor=actor)
    health_result = run_datasource_health_checks() if include_health else {'metrics': 0, 'logs': 0, 'errors': 0}
    alert_result = run_due_alert_rules(limit=alert_rule_limit)
    analysis_result = run_due_alert_analyses(limit=limit)
    return {
        'host_tasks': host_result,
        'datasource_health': health_result,
        'alert_rules': alert_result,
        'alert_analyses': analysis_result,
    }


def run_ops_scheduler_loop(interval_seconds=None, limit=20, actor='system-scheduler', alert_rule_limit=100):
    interval = int(interval_seconds or getattr(settings, 'OPS_SCHEDULER_POLL_SECONDS', getattr(settings, 'HOST_TASK_SCHEDULER_POLL_SECONDS', 30)))
    logger.info('ops scheduler loop started, interval=%s', interval)
    while True:
        try:
            result = run_ops_scheduler_once(limit=limit, actor=actor, alert_rule_limit=alert_rule_limit)
            logger.debug('ops scheduler checked: %s', result)
        except Exception:
            logger.exception('ops scheduler loop failed')
        time.sleep(max(interval, 5))
