from ops.alert_rules import build_rule_fingerprint
from ops.models import AlertRuleState


def state_fingerprint(rule, labels=None):
    return build_rule_fingerprint(rule, labels or {})


def active_states(rule):
    return AlertRuleState.objects.filter(rule=rule, status=AlertRuleState.STATUS_ACTIVE)
