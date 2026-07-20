import json
import logging
import re
from collections import Counter
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import Alert, AlertAnalysis, AlertRule, MetricDataSource


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


def _resolve_environment(alert, rule=None):
    from aiops.business_context import resolve_business_context

    metric_id = _metric_datasource_id(alert, rule=rule)
    environment = alert.knowledge_environment if alert.knowledge_environment_id else resolve_business_context(alert.environment)
    if not environment:
        return None, [], [], '告警未匹配到知识环境，未查询任何默认数据源'
    if alert.environment != environment.code:
        return environment, [], [], f'告警环境“{alert.environment}”与业务上下文编码“{environment.code}”不一致'
    metric_ids = [environment.metric_datasource_id] if environment.metric_datasource_id else []
    log_ids = [environment.log_datasource_id] if environment.log_datasource_id else []
    if metric_id and (not metric_ids or metric_ids[0] != metric_id):
        return environment, metric_ids, log_ids, '告警规则绑定的 Prometheus 与知识环境不一致'
    return environment, metric_ids, log_ids, ''


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


def collect_alert_evidence(alert):
    rule = _alert_rule(alert)
    raw_payload = _dict(alert.raw_payload)
    raw_event = _dict(raw_payload.get('event'))
    raw_rule = _dict(raw_payload.get('rule'))
    environment, metric_ids, _log_ids, config_error = _resolve_environment(alert, rule=rule)
    depth = {'critical': 'full', 'warning': 'targeted', 'info': 'light'}.get(alert.level, 'targeted')
    evidence = {
        'profile': 'alert_analysis',
        'depth': depth,
        'stage_status': {},
        'source_coverage': {},
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
    metric = MetricDataSource.objects.filter(pk=metric_ids[0], is_enabled=True).first() if metric_ids else None
    if not metric:
        message = '知识环境绑定的 Prometheus 不存在或已停用'
        evidence['diagnostics'].append({'code': 'metric_datasource_unavailable', 'message': message})
    else:
        evidence['metric_datasource'] = {'id': metric.id, 'name': metric.name, 'provider': metric.provider}
    if environment:
        try:
            from .observability_evidence import collect_observability_evidence
            observed = collect_observability_evidence(
                environment,
                profile='alert_analysis',
                depth=depth,
                alert=alert,
                target=alert.resource or alert.service,
                window_minutes=max(30, _window_minutes(alert, rule=rule)),
            )
            for key in [
                'stage_status', 'source_coverage', 'metrics', 'metric_anomalies', 'k8s',
                'k8s_findings', 'k8s_samples', 'event_findings', 'change_findings',
                'topology_findings', 'assets', 'logs', 'log_findings',
            ]:
                if key in observed:
                    evidence[key] = observed[key]
            evidence['diagnostics'].extend(observed.get('diagnostics') or [])
        except Exception as exc:
            evidence['stage_status']['observability'] = 'failed'
            evidence['diagnostics'].append({'code': 'observability_collection_failed', 'message': str(exc)[:300]})
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
    grouped = {item['code']: item for item in candidates}
    for finding in evidence.get('k8s_findings') or []:
        code = finding.get('code') or 'k8s_abnormal'
        item = grouped.setdefault(code, {
            'code': code,
            'title': finding.get('message') or 'K8s 资源状态异常',
            'score': 0.72 if finding.get('severity') == 'critical' else 0.58,
            'evidence': [],
        })
        item['evidence'].append(finding.get('message'))
        item['score'] = min(0.9, item['score'] + 0.04)
    for metric in evidence.get('metric_anomalies') or []:
        code = f"metric_{metric.get('code')}"
        grouped.setdefault(code, {
            'code': code,
            'title': f"{metric.get('title')}偏离历史基线",
            'score': min(0.85, 0.45 + float((metric.get('anomaly') or {}).get('confidence') or 0) * 0.35),
            'evidence': [f"{(metric.get('anomaly') or {}).get('vote_count', 0)} 个算法判定异常"],
        })
    candidates = sorted(grouped.values(), key=lambda item: item.get('score', 0), reverse=True)[:5]
    return candidates


def _confidence_policy(evidence):
    coverage = evidence.get('source_coverage') if isinstance(evidence.get('source_coverage'), dict) else {}
    independent_sources = {'metrics', 'k8s', 'logs', 'changes'}
    sources = [name for name, available in coverage.items() if available and name in independent_sources]
    direct = bool(
        evidence.get('metric_anomalies')
        or evidence.get('k8s_findings')
        or evidence.get('event_findings')
        or evidence.get('log_findings')
    )
    if len(sources) >= 3 and direct:
        cap = 0.95
    elif len(sources) >= 2:
        cap = 0.79
    elif len(sources) == 1:
        cap = 0.49
    else:
        cap = 0.3
    return {
        'source_count': len(sources),
        'sources': sources,
        'direct_evidence': direct,
        'confidence_cap': cap,
        'reasons': [f'有效独立证据源 {len(sources)} 类', '存在直接异常证据' if direct else '缺少直接异常证据'],
    }


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
        'metric_anomalies': evidence.get('metric_anomalies'),
        'k8s_findings': evidence.get('k8s_findings'),
        'k8s_samples': evidence.get('k8s_samples'),
        'event_findings': evidence.get('event_findings'),
        'log_evidence': evidence.get('logs'),
        'source_coverage': evidence.get('source_coverage'),
        'confidence_cap': evidence.get('confidence_cap'),
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
                    'confidence 不得高于输入中的 confidence_cap。'
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
    confidence_policy = _confidence_policy(evidence)
    evidence['evidence_quality'] = confidence_policy
    evidence['confidence_cap'] = confidence_policy['confidence_cap']
    evidence['confidence_reasons'] = confidence_policy['reasons']
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
        confidence = max(0.0, min(float(confidence), confidence_policy['confidence_cap'])) if confidence is not None else None
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
    if analysis.alert.status in {Alert.STATUS_ACTIVE, Alert.STATUS_RESOLVED}:
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
