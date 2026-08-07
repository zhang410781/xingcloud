"""检测算法注册表：静态阈值之外的同比/环比/3-Sigma 检测。

规则通过 AlertRule.detector 选择算法（默认 threshold，旧规则零迁移）。
非 Prometheus 数据源（ClickHouse 等）不支持基准比较，统一回退 threshold。
"""

import math
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

from ..anomaly_detection import _sigma

DETECTORS = {
    'threshold': {'label': '静态阈值', 'params': {}, 'implemented': True},
    'yoy': {
        'label': '同比',
        'params': {'period': 'day', 'delta_pct': 30, 'operator': '>'},
        'implemented': True,
    },
    'wow': {
        'label': '环比',
        'params': {'period': 'day', 'delta_pct': 30, 'operator': '>', 'window_minutes': 60},
        'implemented': True,
    },
    'sigma': {
        'label': '3-Sigma',
        'params': {'window_minutes': 120, 'threshold': 3.0},
        'implemented': True,
    },
    'ewma': {'label': 'EWMA', 'params': {}, 'implemented': False},
    'iqr': {'label': 'IQR', 'params': {}, 'implemented': False},
    'isolation_forest': {'label': 'Isolation Forest', 'params': {}, 'implemented': False},
}

_BASELINE_CACHE_TTL = 300  # 5 分钟


def detector_registry():
    return [
        {'name': name, **{key: value for key, value in meta.items()}}
        for name, meta in DETECTORS.items()
    ]


def normalize_detector(rule):
    """解析规则 detector 配置，返回 (name, params, fallback_reason)。

    非法/未接入算法回退 threshold，并在 evidence 标注原因。
    """
    config = rule.detector if isinstance(rule.detector, dict) else {}
    name = str(config.get('name') or 'threshold').strip().lower()
    meta = DETECTORS.get(name)
    if not meta:
        return 'threshold', {}, f'detector {name!r} 未注册，回退静态阈值'
    if not meta['implemented']:
        return 'threshold', {}, f'detector {name!r} 未接入实现，回退静态阈值'
    params = dict(meta['params'])
    params.update({key: value for key, value in config.get('params', {}).items() if value is not None})
    return name, params, ''


def run_detector(rule, current_value, *, context=None):
    """运行规则配置的检测算法。

    context: {'datasource_id', 'environment', 'source_type', 'query'} 提供基准查询所需信息。
    返回统一结果结构，detector 段供 evidence 附加。
    """
    context = context or {}
    name, params, fallback = normalize_detector(rule)
    outcome = {
        'algorithm': name,
        'matched': False,
        'baseline': None,
        'delta': None,
        'score': None,
        'detail': '',
        'params': params,
    }
    if fallback:
        outcome['detail'] = fallback
        outcome['matched'] = _threshold_match(current_value, rule.condition)
        return outcome
    try:
        if name == 'threshold':
            outcome['matched'] = _threshold_match(current_value, rule.condition)
            return outcome
        if context.get('source_type') != 'prometheus':
            outcome['algorithm'] = 'threshold'
            outcome['detail'] = '非 Prometheus 规则不支持基准比较，回退静态阈值'
            outcome['matched'] = _threshold_match(current_value, rule.condition)
            return outcome
        if name == 'yoy':
            return _run_yoy(current_value, params, context, outcome)
        if name == 'wow':
            return _run_wow(current_value, params, context, outcome)
        if name == 'sigma':
            return _run_sigma(current_value, params, context, outcome)
    except Exception as exc:  # noqa: BLE001 基准查询失败不阻断告警，回退阈值
        outcome['algorithm'] = 'threshold'
        outcome['detail'] = f'detector {name} 执行失败（{exc}），回退静态阈值'
        outcome['matched'] = _threshold_match(current_value, rule.condition)
        return outcome
    outcome['detail'] = f'detector {name!r} 未接入实现，回退静态阈值'
    outcome['matched'] = _threshold_match(current_value, rule.condition)
    return outcome


def _threshold_match(value, condition):
    condition = condition if isinstance(condition, dict) else {}
    operator = str(condition.get('operator') or condition.get('op') or '>').strip()
    threshold = condition.get('threshold') if condition.get('threshold') is not None else condition.get('value')
    try:
        threshold = float(threshold) if threshold is not None else 0
    except (TypeError, ValueError):
        threshold = 0
    try:
        value = float(value)
    except (TypeError, ValueError):
        return False
    if operator in {'>=', 'gte'}:
        return value >= threshold
    if operator in {'<', 'lt'}:
        return value < threshold
    if operator in {'<=', 'lte'}:
        return value <= threshold
    if operator in {'==', '=', 'eq'}:
        return value == threshold
    if operator in {'!=', '<>', 'ne'}:
        return value != threshold
    return value > threshold


def _range_samples(payload):
    """从 range query 响应提取各序列样本，返回 {labels_key: [values]}。"""
    samples = []
    for item in payload.get('result') or []:
        metric = item.get('metric') if isinstance(item, dict) else {}
        series = [point for point in (item.get('values') or []) if isinstance(point, (list, tuple)) and len(point) >= 2]
        for point in series:
            try:
                value = float(point[1])
            except (TypeError, ValueError):
                continue
            if math.isfinite(value):
                samples.append(value)
    return samples


def _baseline_cache_key(rule, algorithm, period_key):
    return f'detector:{rule.id}:{algorithm}:{period_key}'


def _baseline_series(rule, algorithm, period_key, query, start, end, step, datasource_id, environment):
    """range query 现查基准窗口样本，结果按 (rule, algorithm, period) 缓存 5 分钟。"""
    from ..observability_views import execute_promql_query  # 延迟导入避免 serializers 环

    cache_key = _baseline_cache_key(rule, algorithm, period_key)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    payload = execute_promql_query(
        query,
        range_query=True,
        start_time=start.isoformat(),
        end_time=end.isoformat(),
        step=step,
        metric_datasource_id=datasource_id,
        environment=environment,
        prefer_metric_datasource=True,
    )
    samples = _range_samples(payload)
    cache.set(cache_key, samples, _BASELINE_CACHE_TTL)
    return samples


def _baseline_mean(samples):
    if not samples:
        return None
    return sum(samples) / len(samples)


def _period_delta(period, window_minutes):
    period = str(period or 'day').strip().lower()
    if period == 'week':
        return 7 * 24 * 60
    return 24 * 60


def _run_yoy(current, params, context, outcome):
    period = params.get('period') or 'day'
    delta_pct = float(params.get('delta_pct') or 30)
    operator = str(params.get('operator') or '>')
    now = timezone.localtime()
    period_minutes = _period_delta(period, 0)
    window_minutes = 60
    baseline_start = now - timedelta(minutes=period_minutes + window_minutes)
    baseline_end = now - timedelta(minutes=period_minutes)
    samples = _baseline_series(
        context['rule'], 'yoy', period,
        context['query'], baseline_start, baseline_end, 60,
        context['datasource_id'], context['environment'],
    )
    baseline = _baseline_mean(samples)
    outcome['baseline'] = baseline
    if baseline is None or baseline == 0:
        outcome['detail'] = '同期窗口无有效样本，不判定'
        return outcome
    delta = (current - baseline) / abs(baseline)
    outcome['delta'] = round(delta, 4)
    hit = abs(delta) * 100 >= delta_pct and (delta > 0 if operator == '>' else delta < 0)
    outcome['matched'] = bool(hit)
    outcome['detail'] = f'baseline={baseline:.4f}, delta={delta * 100:.2f}%, period={period}'
    return outcome


def _run_wow(current, params, context, outcome):
    period = params.get('period') or 'day'
    delta_pct = float(params.get('delta_pct') or 30)
    operator = str(params.get('operator') or '>')
    window_minutes = int(params.get('window_minutes') or 60)
    now = timezone.localtime()
    period_minutes = _period_delta(period, 0)
    baseline_start = now - timedelta(minutes=period_minutes + window_minutes)
    baseline_end = now - timedelta(minutes=period_minutes)
    samples = _baseline_series(
        context['rule'], 'wow', f'{period}:{window_minutes}',
        context['query'], baseline_start, baseline_end, 60,
        context['datasource_id'], context['environment'],
    )
    baseline = _baseline_mean(samples)
    outcome['baseline'] = baseline
    if baseline is None or baseline == 0:
        outcome['detail'] = '对比窗口无有效样本，不判定'
        return outcome
    delta = (current - baseline) / abs(baseline)
    outcome['delta'] = round(delta, 4)
    hit = abs(delta) * 100 >= delta_pct and (delta > 0 if operator == '>' else delta < 0)
    outcome['matched'] = bool(hit)
    outcome['detail'] = f'baseline={baseline:.4f}, delta={delta * 100:.2f}%, window={window_minutes}min'
    return outcome


def _run_sigma(current, params, context, outcome):
    window_minutes = int(params.get('window_minutes') or 120)
    threshold = float(params.get('threshold') or 3.0)
    now = timezone.localtime()
    window_start = now - timedelta(minutes=window_minutes)
    samples = _baseline_series(
        context['rule'], 'sigma', str(window_minutes),
        context['query'], window_start, now, 60,
        context['datasource_id'], context['environment'],
    )
    result = _sigma(samples, current, threshold=threshold)
    outcome['score'] = result.get('score')
    outcome['detail'] = result.get('detail') or ''
    if not result.get('eligible'):
        outcome['detail'] = f'样本不足（{len(samples)} < 10），不判定'
        return outcome
    outcome['matched'] = bool(result.get('is_anomaly'))
    return outcome
