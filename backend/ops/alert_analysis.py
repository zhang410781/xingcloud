import json
import logging
import re
from collections import Counter
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .log_views import ProviderError, _merge_config, _run_query
from .models import Alert, AlertAnalysis, AlertRule, LogDataSource, MetricDataSource


logger = logging.getLogger(__name__)

SECRET_PATTERN = re.compile(
    r'(?i)\b(password|passwd|pwd|token|api[_-]?key|authorization|cookie|secret)\b(\s*[:=]\s*)([^\s,;]+)'
)
BEARER_PATTERN = re.compile(r'(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*')
PHONE_PATTERN = re.compile(r'(?<!\d)1[3-9]\d{9}(?!\d)')
LEVEL_RANK = {'info': 1, 'warning': 2, 'critical': 3}

PATTERNS = [
    ('oom_killed', re.compile(r'(?i)\b(oomkilled|out of memory|cannot allocate memory)\b'), '进程或容器可能因内存不足退出'),
    ('crash_loop', re.compile(r'(?i)\b(crashloopbackoff|back-off restarting|restart loop)\b'), '容器持续启动失败并进入重启退避'),
    ('connection_refused', re.compile(r'(?i)\b(connection refused|connect refused|actively refused)\b'), '下游依赖拒绝连接'),
    ('timeout', re.compile(r'(?i)\b(timeout|timed out|deadline exceeded)\b'), '调用或资源操作发生超时'),
    ('permission_denied', re.compile(r'(?i)\b(permission denied|forbidden|unauthorized|access denied)\b'), '权限或鉴权配置可能异常'),
    ('disk_full', re.compile(r'(?i)\b(no space left|disk full|filesystem full)\b'), '磁盘空间不足导致写入失败'),
    ('dependency_error', re.compile(r'(?i)\b(unavailable|connection reset|broken pipe|upstream error)\b'), '依赖服务或网络链路异常'),
]


def _dict(value):
    return value if isinstance(value, dict) else {}


def _int_list(value):
    values = value if isinstance(value, (list, tuple, set)) else []
    result = []
    for item in values:
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        if number > 0 and number not in result:
            result.append(number)
    return result


def _redact(value):
    text = str(value or '')
    text = SECRET_PATTERN.sub(lambda match: f'{match.group(1)}{match.group(2)}***', text)
    text = BEARER_PATTERN.sub('Bearer ***', text)
    return PHONE_PATTERN.sub('1**********', text)


def _redact_json(value):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if str(key).strip().casefold() in {'password', 'passwd', 'pwd', 'token', 'api_key', 'apikey', 'authorization', 'cookie', 'secret'}:
                result[key] = '***'
            else:
                result[key] = _redact_json(item)
        return result
    if isinstance(value, list):
        return [_redact_json(item) for item in value]
    if isinstance(value, str):
        return _redact(value)
    return value


def _alert_rule(alert):
    rule_data = _dict(_dict(alert.raw_payload).get('rule'))
    rule_id = rule_data.get('id') or _dict(alert.labels).get('alert_rule_id')
    try:
        return AlertRule.objects.select_related('metric_datasource').filter(pk=int(rule_id)).first()
    except (TypeError, ValueError):
        return None


def _metric_datasource_id(alert, rule=None):
    labels = _dict(alert.labels)
    raw_rule = _dict(_dict(alert.raw_payload).get('rule'))
    value = (rule.metric_datasource_id if rule else None) or raw_rule.get('metric_datasource_id') or labels.get('metric_datasource_id')
    try:
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


def _singular_or_legacy_ids(environment, singular_name, legacy_name):
    singular_id = getattr(environment, f'{singular_name}_id', None)
    if singular_id:
        return [int(singular_id)], ''
    ids = _int_list(getattr(environment, legacy_name, []) or [])
    if len(ids) > 1:
        return [], f'知识环境“{environment.name}”配置了多个{singular_name}，每个环境只允许绑定一个'
    return ids, ''


def _environment_terms(environment):
    return {
        str(value).strip().casefold()
        for value in [environment.name, *(environment.aliases or []), *(environment.alert_environments or [])]
        if str(value or '').strip()
    }


def _resolve_environment(alert, rule=None):
    from aiops.models import AIOpsKnowledgeEnvironment

    environments = list(AIOpsKnowledgeEnvironment.objects.filter(is_enabled=True).order_by('-is_default', 'id'))
    metric_id = _metric_datasource_id(alert, rule=rule)
    alert_environment = str(alert.environment or _dict(alert.labels).get('environment') or '').strip().casefold()
    candidates = []
    for environment in environments:
        metric_ids, metric_error = _singular_or_legacy_ids(environment, 'metric_datasource', 'metric_datasource_ids')
        log_ids, log_error = _singular_or_legacy_ids(environment, 'log_datasource', 'log_datasource_ids')
        if metric_error or log_error:
            if (metric_id and metric_id in metric_ids) or (alert_environment and alert_environment in _environment_terms(environment)):
                return environment, metric_ids, log_ids, metric_error or log_error
            continue
        score = 0
        if metric_id and metric_id in metric_ids:
            score += 100
        if alert_environment and alert_environment in _environment_terms(environment):
            score += 50
        if score:
            candidates.append((score, environment, metric_ids, log_ids))
    if not candidates:
        return None, [], [], '告警未匹配到知识环境，未查询任何默认数据源'
    candidates.sort(key=lambda item: (-item[0], item[1].id))
    best_score = candidates[0][0]
    best = [item for item in candidates if item[0] == best_score]
    if len(best) > 1:
        return None, [], [], '告警同时匹配多个知识环境，请完善环境或指标数据源关联'
    _, environment, metric_ids, log_ids = best[0]
    if len(metric_ids) != 1:
        return environment, metric_ids, log_ids, f'知识环境“{environment.name}”未绑定唯一 Prometheus 数据源'
    if metric_id and metric_ids[0] != metric_id:
        return environment, metric_ids, log_ids, '告警规则绑定的 Prometheus 与知识环境不一致'
    if len(log_ids) != 1:
        return environment, metric_ids, log_ids, f'知识环境“{environment.name}”未绑定唯一日志源'
    return environment, metric_ids, log_ids, ''


def _dimension_values(alert):
    labels = _dict(alert.labels)
    resource_type = str(alert.resource_type or '').lower()
    resource = str(alert.resource or '').strip()
    values = {
        'cluster': str(alert.cluster or labels.get('cluster') or '').strip(),
        'namespace': str(alert.namespace or labels.get('namespace') or labels.get('namespace_name') or '').strip(),
        'pod': str(labels.get('pod') or labels.get('pod_name') or (resource if resource_type in {'pod', 'k8s', 'prometheus'} else '')).strip(),
        'service': str(alert.service or labels.get('service') or labels.get('app') or labels.get('job') or '').strip(),
        'node': str(labels.get('node') or labels.get('node_name') or (resource if resource_type == 'node' else '')).strip(),
        'host': str(labels.get('host') or labels.get('instance') or (alert.host.hostname if alert.host_id and alert.host else '')).strip(),
    }
    return {key: value for key, value in values.items() if value}


def _query_terms(dimensions):
    ordered = ['pod', 'namespace', 'service', 'node', 'host', 'cluster']
    terms = []
    for key in ordered:
        value = dimensions.get(key)
        if value and value not in terms:
            terms.append(value)
        if len(terms) >= 3:
            break
    return ' '.join(f'"{item}"' for item in terms) or '*'


def _window_end(alert):
    return alert.ends_at or alert.last_received_at or alert.starts_at or timezone.now()


def _window_minutes(alert, rule=None):
    values = []
    if rule:
        values.extend([rule.duration_seconds / 60, rule.interval_seconds / 60])
        query = _dict(rule.query_config)
        raw = query.get('window_minutes') or query.get('window')
        if raw:
            text = str(raw).strip().lower()
            try:
                values.append(float(text[:-1]) * 60 if text.endswith('h') else float(text[:-1]) if text.endswith('m') else float(text))
            except (TypeError, ValueError):
                pass
    return max(15, min(int(max(values or [15])), 60))


def _sanitize_log(log):
    message = _redact(log.get('message'))[:1200]
    return {
        'timestamp': str(log.get('timestamp') or ''),
        'level': str(log.get('level') or 'unknown').lower(),
        'source': str(log.get('source') or ''),
        'service': str(log.get('service') or ''),
        'namespace': str(log.get('namespace') or ''),
        'pod': str(log.get('pod') or ''),
        'container': str(log.get('container') or ''),
        'host': str(log.get('host') or ''),
        'message': message,
    }


def _dedupe_logs(logs, limit=20):
    result = []
    seen = set()
    for raw in logs or []:
        item = _sanitize_log(raw)
        fingerprint = re.sub(r'\b\d+\b', '#', item['message'].casefold())[:500]
        key = (item['level'], item['source'], fingerprint)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= limit:
            break
    return result


def _collect_log_evidence(alert, datasource, rule=None):
    dimensions = _dimension_values(alert)
    initial_minutes = _window_minutes(alert, rule=rule)
    end_at = _window_end(alert)
    attempts = []
    result = None
    for minutes in list(dict.fromkeys([initial_minutes, 60])):
        payload = {
            'query': _query_terms(dimensions),
            'start_ms': int((end_at - timedelta(minutes=minutes)).timestamp() * 1000),
            'end_ms': int(end_at.timestamp() * 1000),
            'limit': 50,
        }
        if datasource.provider == 'clickhouse':
            payload['collection'] = _dict(datasource.config).get('default_collection') or 'container-logs'
        attempts.append({'window_minutes': minutes, 'query': payload['query']})
        result = _run_query(datasource.provider, _merge_config(datasource.provider, datasource.config), payload)
        if result.get('logs') or minutes == 60:
            break
    logs = _dedupe_logs((result or {}).get('logs') or [])
    levels = Counter(item.get('level') or 'unknown' for item in logs)
    return {
        'status': 'ok',
        'datasource': {'id': datasource.id, 'name': datasource.name, 'provider': datasource.provider},
        'dimensions': dimensions,
        'field_map': _redact_json(_dict(datasource.config).get('field_map') or {}),
        'attempts': attempts,
        'total': (result or {}).get('total', len(logs)),
        'sample_count': len(logs),
        'level_distribution': dict(levels),
        'samples': logs,
    }


def collect_alert_evidence(alert):
    rule = _alert_rule(alert)
    raw_payload = _dict(alert.raw_payload)
    raw_event = _dict(raw_payload.get('event'))
    raw_rule = _dict(raw_payload.get('rule'))
    environment, metric_ids, log_ids, config_error = _resolve_environment(alert, rule=rule)
    evidence = {
        'alert': {
            'id': alert.id,
            'title': alert.title,
            'level': alert.level,
            'status': alert.status,
            'message': alert.message,
            'environment': alert.environment,
            'cluster': alert.cluster,
            'namespace': alert.namespace,
            'service': alert.service,
            'resource_type': alert.resource_type,
            'resource': alert.resource,
            'metric_name': alert.metric_name,
            'current_value': raw_event.get('value'),
            'condition': _redact_json(raw_rule.get('condition') or {}),
            'query_config': _redact_json(raw_rule.get('query_config') or {}),
            'event': _redact_json(raw_event),
            'labels': _redact_json(_dict(alert.labels)),
            'starts_at': alert.starts_at.isoformat() if alert.starts_at else None,
        },
        'knowledge_environment': None,
        'metric_datasource': None,
        'logs': {'status': 'not_collected', 'samples': []},
        'diagnostics': [],
    }
    if environment:
        evidence['knowledge_environment'] = {'id': environment.id, 'name': environment.name}
    if config_error:
        evidence['diagnostics'].append({'code': 'environment_configuration_error', 'message': config_error})
        evidence['logs'] = {'status': 'configuration_error', 'error': config_error, 'samples': []}
        return evidence
    metric = MetricDataSource.objects.filter(pk=metric_ids[0], is_enabled=True).first()
    if not metric:
        message = '知识环境绑定的 Prometheus 不存在或已停用'
        evidence['diagnostics'].append({'code': 'metric_datasource_unavailable', 'message': message})
    else:
        evidence['metric_datasource'] = {'id': metric.id, 'name': metric.name, 'provider': metric.provider}
    datasource = LogDataSource.objects.filter(pk=log_ids[0], is_enabled=True).first()
    if not datasource:
        message = '知识环境绑定的日志源不存在或已停用'
        evidence['diagnostics'].append({'code': 'log_datasource_unavailable', 'message': message})
        evidence['logs'] = {'status': 'configuration_error', 'error': message, 'samples': []}
        return evidence
    try:
        evidence['logs'] = _collect_log_evidence(alert, datasource, rule=rule)
    except (ProviderError, Exception) as exc:
        message = str(exc)
        evidence['diagnostics'].append({'code': 'log_query_failed', 'message': message})
        evidence['logs'] = {
            'status': 'query_error',
            'error': message,
            'datasource': {'id': datasource.id, 'name': datasource.name, 'provider': datasource.provider},
            'samples': [],
        }
    return evidence


def _deterministic_candidates(evidence):
    samples = _dict(evidence.get('logs')).get('samples') or []
    matches = Counter()
    examples = {}
    for sample in samples:
        message = str(sample.get('message') or '')
        for code, pattern, title in PATTERNS:
            if pattern.search(message):
                matches[code] += 1
                examples.setdefault(code, message[:240])
    candidates = []
    titles = {code: title for code, _, title in PATTERNS}
    for code, count in matches.most_common(5):
        candidates.append({
            'code': code,
            'title': titles[code],
            'score': min(0.85, 0.35 + count * 0.1),
            'evidence': [examples[code]],
        })
    return candidates


def _json_from_model(content):
    text = str(content or '').strip()
    text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text, flags=re.IGNORECASE)
    start, end = text.find('{'), text.rfind('}')
    if start < 0 or end <= start:
        raise ValueError('模型未返回 JSON 对象')
    data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError('模型研判结果格式无效')
    return data


def _llm_synthesis(evidence, candidates):
    from aiops.services import _request_model_completion, get_active_provider

    provider = get_active_provider()
    if not provider or not provider.is_enabled or not provider.get_api_key().strip():
        raise RuntimeError('未配置可用的智能研判模型')
    prompt_data = {
        'alert': evidence.get('alert'),
        'knowledge_environment': evidence.get('knowledge_environment'),
        'metric_datasource': evidence.get('metric_datasource'),
        'log_evidence': evidence.get('logs'),
        'diagnostics': evidence.get('diagnostics'),
        'deterministic_candidates': candidates,
    }
    payload = {
        'model': provider.default_model,
        'temperature': 0.1,
        'max_tokens': min(int(provider.max_tokens or 2000), 3000),
        'messages': [
            {
                'role': 'system',
                'content': (
                    '你是生产运维告警研判器。只依据给出的告警与日志证据判断，不得臆测。'
                    '日志仅相关但不能证明因果时必须标记为关联现象。证据不足时不要给出确定根因。'
                    '仅输出 JSON：summary, root_cause, confidence(0到1), candidates(array), suggestions(array), evidence_notes(array)。'
                ),
            },
            {'role': 'user', 'content': json.dumps(prompt_data, ensure_ascii=False, default=str)[:24000]},
        ],
    }
    response = _request_model_completion(provider, payload, purpose='alert_analysis')
    message = (((response or {}).get('choices') or [{}])[0].get('message') or {})
    data = _json_from_model(message.get('content'))
    resolved_model = _dict((response or {}).get('_meta')).get('resolved_model') or provider.default_model
    return provider.name, resolved_model, data


def _summary_without_model(evidence, candidates):
    logs = _dict(evidence.get('logs'))
    if candidates:
        return '已完成告警与日志证据关联，模型综合判断暂不可用。'
    if logs.get('status') == 'ok' and logs.get('sample_count'):
        return '已关联日志样本，但当前证据不足以确定根因。'
    return '未获得足够的关联日志证据，暂不能确定根因。'


def _project_compatibility(analysis):
    alert = analysis.alert
    payload = _dict(alert.raw_payload)
    payload['ai_analysis'] = {
        'id': analysis.id,
        'status': analysis.status,
        'summary': _dict(analysis.result).get('summary') or '',
        'confidence': analysis.confidence,
        'root_cause': analysis.root_cause,
        'suggested_actions': _dict(analysis.result).get('suggestions') or ([analysis.suggestion] if analysis.suggestion else []),
        'completed_at': analysis.completed_at.isoformat() if analysis.completed_at else None,
    }
    alert.root_cause = analysis.root_cause
    alert.suggestion = analysis.suggestion
    alert.raw_payload = payload
    alert.save(update_fields=['root_cause', 'suggestion', 'raw_payload', 'updated_at'])


def execute_alert_analysis(analysis):
    evidence = collect_alert_evidence(analysis.alert)
    candidates = _deterministic_candidates(evidence)
    provider_name = ''
    model_name = ''
    model_error = ''
    try:
        provider_name, model_name, result = _llm_synthesis(evidence, candidates)
        status = AlertAnalysis.STATUS_COMPLETED
    except Exception as exc:
        model_error = str(exc)
        result = {
            'summary': _summary_without_model(evidence, candidates),
            'root_cause': '',
            'confidence': candidates[0]['score'] if candidates else None,
            'candidates': candidates,
            'suggestions': ['检查知识环境和日志源配置后重新研判'] if _dict(evidence.get('logs')).get('status') != 'ok' else ['结合更多指标、事件和变更证据继续排查'],
            'evidence_notes': [item.get('message') for item in evidence.get('diagnostics') or []],
        }
        status = AlertAnalysis.STATUS_PARTIAL
    confidence = result.get('confidence')
    try:
        confidence = max(0.0, min(float(confidence), 1.0)) if confidence is not None else None
    except (TypeError, ValueError):
        confidence = None
    suggestions = result.get('suggestions') if isinstance(result.get('suggestions'), list) else []
    analysis.status = status
    analysis.evidence = evidence
    analysis.candidates = result.get('candidates') if isinstance(result.get('candidates'), list) else candidates
    analysis.confidence = confidence
    analysis.result = result
    analysis.root_cause = str(result.get('root_cause') or '')
    analysis.suggestion = '\n'.join(str(item) for item in suggestions if str(item).strip())
    analysis.provider = provider_name
    analysis.model = model_name
    analysis.last_error = model_error
    analysis.completed_at = timezone.now()
    analysis.next_retry_at = None
    analysis.save(update_fields=[
        'status', 'evidence', 'candidates', 'confidence', 'result', 'root_cause', 'suggestion',
        'provider', 'model', 'last_error', 'completed_at', 'next_retry_at', 'updated_at',
    ])
    _project_compatibility(analysis)
    analysis.alert.refresh_from_db(fields=['status'])
    if analysis.alert.status == Alert.STATUS_ACTIVE:
        try:
            from .alerting import dispatch_alert_notifications
            dispatch_alert_notifications(analysis.alert, action='analysis')
        except Exception:
            logger.exception('failed to dispatch analysis notification for alert %s', analysis.alert_id)
    return analysis


def enqueue_alert_analysis(alert, trigger=AlertAnalysis.TRIGGER_FIRST_ACTIVE, requested_by='', force=False):
    if not force and alert.status != Alert.STATUS_ACTIVE:
        return None, False
    active = alert.analyses.filter(status__in=[AlertAnalysis.STATUS_PENDING, AlertAnalysis.STATUS_RUNNING]).order_by('-id').first()
    if active:
        return active, False
    analysis = AlertAnalysis.objects.create(alert=alert, trigger=trigger, requested_by=requested_by)
    payload = _dict(alert.raw_payload)
    payload['ai_analysis'] = {
        **_dict(payload.get('ai_analysis')),
        'id': analysis.id,
        'status': AlertAnalysis.STATUS_PENDING,
    }
    alert.raw_payload = payload
    alert.save(update_fields=['raw_payload', 'updated_at'])
    return analysis, True


def enqueue_for_rule_alert(alert, rule, created=False, previous_level=''):
    if not rule.auto_analyze or alert.status != Alert.STATUS_ACTIVE:
        return None, False
    if created:
        return enqueue_alert_analysis(alert, AlertAnalysis.TRIGGER_FIRST_ACTIVE, requested_by='alert-engine')
    if LEVEL_RANK.get(alert.level, 0) > LEVEL_RANK.get(previous_level, 0):
        return enqueue_alert_analysis(alert, AlertAnalysis.TRIGGER_SEVERITY_ESCALATION, requested_by='alert-engine')
    return None, False


def claim_due_analysis():
    now = timezone.now()
    with transaction.atomic():
        queryset = AlertAnalysis.objects.select_for_update().filter(
            status=AlertAnalysis.STATUS_PENDING,
        ).filter(Q(next_retry_at__isnull=True) | Q(next_retry_at__lte=now)).order_by('created_at', 'id')
        analysis = queryset.first()
        if not analysis:
            return None
        analysis.status = AlertAnalysis.STATUS_RUNNING
        analysis.started_at = now
        analysis.save(update_fields=['status', 'started_at', 'updated_at'])
        return analysis


def run_due_alert_analyses(limit=20):
    completed = partial = failed = retried = 0
    processed = []
    for _ in range(max(1, int(limit or 20))):
        analysis = claim_due_analysis()
        if not analysis:
            break
        try:
            execute_alert_analysis(analysis)
            analysis.refresh_from_db(fields=['status'])
            completed += analysis.status == AlertAnalysis.STATUS_COMPLETED
            partial += analysis.status == AlertAnalysis.STATUS_PARTIAL
        except Exception as exc:
            logger.exception('alert analysis %s failed', analysis.id)
            analysis.refresh_from_db()
            analysis.last_error = str(exc)
            if analysis.retry_count < analysis.max_retries:
                analysis.retry_count += 1
                analysis.status = AlertAnalysis.STATUS_PENDING
                analysis.next_retry_at = timezone.now() + timedelta(seconds=min(60 * analysis.retry_count, 120))
                retried += 1
            else:
                analysis.status = AlertAnalysis.STATUS_FAILED
                analysis.completed_at = timezone.now()
                analysis.next_retry_at = None
                failed += 1
            analysis.save(update_fields=['retry_count', 'status', 'next_retry_at', 'completed_at', 'last_error', 'updated_at'])
        processed.append(analysis.id)
    return {'processed': len(processed), 'completed': completed, 'partial': partial, 'retried': retried, 'failed': failed, 'ids': processed}


def serialize_analysis(analysis):
    if not analysis:
        return None
    result = _dict(analysis.result)
    return {
        'id': analysis.id,
        'alert_id': analysis.alert_id,
        'status': analysis.status,
        'trigger': analysis.trigger,
        'confidence': analysis.confidence,
        'summary': result.get('summary') or '',
        'root_cause': analysis.root_cause,
        'suggestion': analysis.suggestion,
        'suggestions': result.get('suggestions') or ([analysis.suggestion] if analysis.suggestion else []),
        'evidence': analysis.evidence,
        'candidates': analysis.candidates,
        'provider': analysis.provider,
        'model': analysis.model,
        'retry_count': analysis.retry_count,
        'last_error': analysis.last_error,
        'requested_by': analysis.requested_by,
        'started_at': analysis.started_at.isoformat() if analysis.started_at else None,
        'completed_at': analysis.completed_at.isoformat() if analysis.completed_at else None,
        'created_at': analysis.created_at.isoformat() if analysis.created_at else None,
        'updated_at': analysis.updated_at.isoformat() if analysis.updated_at else None,
    }
