import json
from datetime import timedelta

from django.utils import timezone

from .models import Alert


SLA_TARGET_PERCENT = 99.96
SLA_DOWNTIME_LEVEL_MARKERS = ['disaster', 'fatal', 'emergency', 'catastrophic', 'p0', 'sev0', 's0', '灾难']
SLA_PRODUCT_DEFINITIONS = [
    {
        'key': 'database',
        'name': '数据库',
        'keywords': ['database', 'db', 'mysql', 'postgres', 'postgresql', 'oracle', 'sqlserver', 'mongodb', 'tidb', '数据库'],
    },
    {
        'key': 'middleware',
        'name': '中间件',
        'keywords': ['middleware', 'redis', 'kafka', 'rocketmq', 'rabbitmq', 'mq', 'elasticsearch', 'es', '中间件', '缓存', '消息队列'],
    },
    {
        'key': 'container_platform',
        'name': '容器平台',
        'keywords': ['container', 'k8s', 'kubernetes', 'pod', 'deployment', 'namespace', 'docker', '容器'],
    },
    {
        'key': 'network',
        'name': '网络',
        'keywords': ['network', 'ingress', 'service', 'dns', 'vip', 'slb', 'elb', 'switch', 'firewall', '网络', '交换机'],
    },
    {
        'key': 'server',
        'name': '服务器',
        'keywords': ['server', 'host', 'node', 'cpu', 'memory', 'disk', 'filesystem', '主机', '服务器', '磁盘', '内存'],
    },
]


def period_start(now, kind):
    if kind == 'year':
        return now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def period_end(now, kind):
    if kind == 'year':
        return now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    if now.month == 12:
        return now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)


def seconds_between(start, end):
    return max((end - start).total_seconds(), 1)


def sla_percentage(period_seconds, downtime_seconds):
    uptime = max(period_seconds - downtime_seconds, 0)
    return round((uptime / period_seconds) * 100, 4)


def contains_sla_downtime_marker(value):
    if value is None:
        return False
    if isinstance(value, (dict, list, tuple)):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = str(value)
    normalized = text.lower().replace('_', '-').replace(' ', '')
    return any(marker in normalized for marker in SLA_DOWNTIME_LEVEL_MARKERS)


def is_sla_downtime_alert(alert):
    return any(
        contains_sla_downtime_marker(value)
        for value in [alert.labels, alert.annotations, alert.raw_payload, alert.title, alert.message]
    )


def alert_product(alert):
    labels = alert.labels if isinstance(alert.labels, dict) else {}
    text = ' '.join(
        str(value or '')
        for value in [
            alert.resource_type,
            alert.resource,
            alert.metric_name,
            alert.service,
            alert.title,
            alert.message,
            labels.get('product'),
            labels.get('category'),
            labels.get('component'),
        ]
    ).lower()
    for product in SLA_PRODUCT_DEFINITIONS:
        if any(keyword in text for keyword in product['keywords']):
            return product
    return SLA_PRODUCT_DEFINITIONS[-1]


def alert_interval(alert, now):
    start = alert.starts_at or alert.created_at or alert.last_received_at or now
    if alert.ends_at:
        end = alert.ends_at
    elif alert.status in [Alert.STATUS_RESOLVED, Alert.STATUS_CLOSED]:
        end = alert.updated_at or alert.last_received_at or now
    else:
        end = now
    if end < start:
        end = start
    return start, end


def overlap_seconds(start, end, window_start, window_end):
    overlap_start = max(start, window_start)
    overlap_end = min(end, window_end)
    if overlap_end <= overlap_start:
        return 0
    return (overlap_end - overlap_start).total_seconds()


def product_status(month_sla, target, downtime_seconds, month_budget_seconds):
    if month_sla < target:
        return '未达标'
    if downtime_seconds >= month_budget_seconds * 0.8:
        return '风险'
    return '达标'


def build_sla_summary(alerts=None, now=None):
    now = now or timezone.now()
    if alerts is None:
        alerts = Alert.objects.select_related('host').prefetch_related('claim_records').order_by('-created_at', '-id')
    alerts = list(alerts)

    month_start = period_start(now, 'month')
    year_start = period_start(now, 'year')
    year_end = period_end(now, 'year')
    month_elapsed_seconds = seconds_between(month_start, now)
    year_elapsed_seconds = seconds_between(year_start, now)
    year_total_seconds = seconds_between(year_start, year_end)
    month_budget_seconds = month_elapsed_seconds * (100 - SLA_TARGET_PERCENT) / 100
    annual_budget_seconds = year_total_seconds * (100 - SLA_TARGET_PERCENT) / 100

    products = {
        item['key']: {
            'key': item['key'],
            'name': item['name'],
            'downtime_seconds': 0,
            'year_downtime_seconds': 0,
            'alerts': 0,
            'critical_alerts': 0,
            'warning_alerts': 0,
        }
        for item in SLA_PRODUCT_DEFINITIONS
    }
    total_month_downtime = 0
    total_year_downtime = 0
    monthly_alerts = []
    disaster_events = []

    for alert in alerts:
        product = alert_product(alert)
        product_row = products[product['key']]
        start, end = alert_interval(alert, now)
        if alert.created_at and alert.created_at >= month_start:
            product_row['alerts'] += 1
            if alert.level == 'critical':
                product_row['critical_alerts'] += 1
            elif alert.level == 'warning':
                product_row['warning_alerts'] += 1
            monthly_alerts.append((alert, product))
        if is_sla_downtime_alert(alert):
            month_overlap = overlap_seconds(start, end, month_start, now)
            year_overlap = overlap_seconds(start, end, year_start, now)
            product_row['downtime_seconds'] += month_overlap
            product_row['year_downtime_seconds'] += year_overlap
            total_month_downtime += month_overlap
            total_year_downtime += year_overlap
            if month_overlap > 0:
                disaster_events.append({
                    'id': alert.id,
                    'title': alert.title,
                    'level': alert.level,
                    'status': alert.status,
                    'product': product['name'],
                    'service': alert.service,
                    'resource': alert.resource,
                    'starts_at': start.isoformat() if start else '',
                    'ends_at': end.isoformat() if end else '',
                    'downtime_minutes': round(month_overlap / 60, 1),
                })

    product_slas = []
    for product in products.values():
        month_sla = sla_percentage(month_elapsed_seconds, product['downtime_seconds'])
        product_slas.append({
            'key': product['key'],
            'name': product['name'],
            'month_sla': month_sla,
            'target': SLA_TARGET_PERCENT,
            'status': product_status(month_sla, SLA_TARGET_PERCENT, product['downtime_seconds'], month_budget_seconds),
            'downtime_minutes': round(product['downtime_seconds'] / 60, 1),
            'alerts': product['alerts'],
            'critical_alerts': product['critical_alerts'],
            'warning_alerts': product['warning_alerts'],
            'risk_count': int(month_sla < SLA_TARGET_PERCENT) + product['critical_alerts'],
        })
    product_slas.sort(key=lambda item: (item['status'] == '达标', item['month_sla'], -item['alerts'], item['name']))

    month_sla = sla_percentage(month_elapsed_seconds, total_month_downtime)
    annual_sla_to_date = sla_percentage(year_elapsed_seconds, total_year_downtime)
    downtime_rate = total_year_downtime / year_elapsed_seconds
    annual_projected_downtime = downtime_rate * year_total_seconds
    annual_forecast_sla = sla_percentage(year_total_seconds, annual_projected_downtime)
    annual_budget_remaining = annual_budget_seconds - total_year_downtime
    if annual_forecast_sla < SLA_TARGET_PERCENT:
        annual_goal_status = '无法达成'
    elif annual_budget_remaining < annual_budget_seconds * 0.2:
        annual_goal_status = '存在风险'
    else:
        annual_goal_status = '预计达成'
    month_status = '未达标' if month_sla < SLA_TARGET_PERCENT else ('风险' if annual_goal_status != '预计达成' else '达标')

    return {
        'target': SLA_TARGET_PERCENT,
        'month_status': month_status,
        'month_sla': month_sla,
        'annual_sla_to_date': annual_sla_to_date,
        'annual_forecast_sla': annual_forecast_sla,
        'annual_goal_status': annual_goal_status,
        'downtime_basis': '灾难级告警持续时长',
        'month_downtime_minutes': round(total_month_downtime / 60, 1),
        'annual_downtime_minutes': round(total_year_downtime / 60, 1),
        'month_budget_minutes': round(month_budget_seconds / 60, 1),
        'annual_budget_minutes': round(annual_budget_seconds / 60, 1),
        'annual_budget_remaining_minutes': round(annual_budget_remaining / 60, 1),
        'product_slas': product_slas,
        'disaster_events': disaster_events,
        '_monthly_alerts': monthly_alerts,
    }


def build_dashboard_sla(alerts=None, now=None):
    summary = build_sla_summary(alerts=alerts, now=now)
    return {
        'sla': {
            'target': summary['target'],
            'month_status': summary['month_status'],
            'month_sla': summary['month_sla'],
            'annual_sla_to_date': summary['annual_sla_to_date'],
            'annual_forecast_sla': summary['annual_forecast_sla'],
            'annual_goal_status': summary['annual_goal_status'],
            'downtime_basis': summary['downtime_basis'],
            'month_downtime_minutes': summary['month_downtime_minutes'],
            'annual_downtime_minutes': summary['annual_downtime_minutes'],
            'annual_budget_minutes': summary['annual_budget_minutes'],
            'annual_budget_remaining_minutes': summary['annual_budget_remaining_minutes'],
        },
        'product_slas': summary['product_slas'],
        'monthly_alerts': summary['_monthly_alerts'],
    }


def build_sla_risk_item():
    summary = build_sla_summary()
    return {
        'would_fire': summary['month_sla'] < SLA_TARGET_PERCENT or summary['annual_goal_status'] != '预计达成',
        'summary': summary,
    }
