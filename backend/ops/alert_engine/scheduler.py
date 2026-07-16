from datetime import timedelta

from django.db.models import Max
from django.utils import timezone

from ops.models import AlertRule, AlertRuleState

from .evaluator import evaluate_rule


def due_rules(limit=100):
    now = timezone.now()
    candidates = AlertRule.objects.filter(is_enabled=True, is_template=False).order_by('last_evaluated_at', 'id')
    rules = []
    for rule in candidates[: max(limit * 3, limit)]:
        if not rule.last_evaluated_at:
            rules.append(rule)
        else:
            interval = max(int(rule.interval_seconds or 60), 30)
            if rule.last_evaluated_at <= now - timedelta(seconds=interval):
                rules.append(rule)
        if len(rules) >= limit:
            break
    return rules


def run_due_alert_rules(limit=100, request=None):
    rules = due_rules(limit=limit)
    results = []
    for rule in rules:
        results.append(evaluate_rule(rule, dry_run=False, request=request))
    return {
        'scanned': len(rules),
        'fired': sum(item.get('would_fire_count', 0) for item in results if item.get('success')),
        'failed': sum(1 for item in results if not item.get('success')),
        'results': results,
    }


def engine_status():
    executable = AlertRule.objects.filter(is_template=False)
    latest = executable.aggregate(value=Max('last_evaluated_at'))['value']
    error_states = AlertRuleState.objects.filter(status=AlertRuleState.STATUS_ERROR).select_related('rule').order_by('-last_seen_at', '-updated_at')
    return {
        'enabled_rules': executable.filter(is_enabled=True).count(),
        'total_rules': executable.count(),
        'template_count': AlertRule.objects.filter(is_template=True).count(),
        'latest_scan_at': latest.isoformat() if latest else None,
        'failed_rules': error_states.values('rule_id').distinct().count(),
        'recent_errors': [
            {
                'rule_id': item.rule_id,
                'rule_name': item.rule.name if item.rule_id else '',
                'last_error': item.last_error,
                'last_seen_at': item.last_seen_at.isoformat() if item.last_seen_at else None,
            }
            for item in error_states[:10]
        ],
    }
