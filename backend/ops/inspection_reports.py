import logging
from datetime import datetime, timedelta, timezone as datetime_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import transaction
from django.utils import timezone

from .alerting import build_recipient_contacts, send_plain_notification
from .models import InspectionReportExecution, InspectionReportSchedule
from .observability_evidence import collect_observability_evidence, inspection_result


logger = logging.getLogger(__name__)


_SEVERITY_WEIGHT = {'critical': 3, 'warning': 2, 'info': 1}


def _finding_key(item):
    return '|'.join(str(item.get(key) or '') for key in ('code', 'target', 'namespace', 'resource', 'service'))


def _inspection_change_summary(previous_report, current_report):
    previous = {_finding_key(item): item for item in (previous_report or {}).get('findings') or []}
    current = {_finding_key(item): item for item in (current_report or {}).get('findings') or []}
    added = [item for key, item in current.items() if key not in previous]
    resolved = [item for key, item in previous.items() if key not in current]
    worsened = [
        item for key, item in current.items()
        if key in previous and _SEVERITY_WEIGHT.get(str(item.get('severity') or 'info').lower(), 0)
        > _SEVERITY_WEIGHT.get(str(previous[key].get('severity') or 'info').lower(), 0)
    ]
    return {
        'has_changes': bool(added or resolved or worsened),
        'added': added,
        'resolved': resolved,
        'worsened': worsened,
        'summary': {'added': len(added), 'resolved': len(resolved), 'worsened': len(worsened)},
    }


def _schedule_timezone(schedule):
    try:
        return ZoneInfo(schedule.timezone or 'Asia/Shanghai')
    except ZoneInfoNotFoundError:
        return ZoneInfo('Asia/Shanghai')


def compute_next_inspection_report_run(schedule, now=None):
    now = now or timezone.now()
    local_tz = _schedule_timezone(schedule)
    local_now = now.astimezone(local_tz)
    candidate_date = local_now.date()
    if schedule.frequency == InspectionReportSchedule.FREQUENCY_WEEKLY:
        weekday = max(1, min(int(schedule.weekday or 1), 7))
        candidate_date += timedelta(days=(weekday - candidate_date.isoweekday()) % 7)
    candidate = datetime.combine(candidate_date, schedule.send_time, tzinfo=local_tz)
    if candidate <= local_now:
        candidate += timedelta(days=7 if schedule.frequency == InspectionReportSchedule.FREQUENCY_WEEKLY else 1)
    return candidate.astimezone(datetime_timezone.utc)


def _report_blocks(schedule, result, generated_at):
    summary = result.get('cluster_summary') or {}
    server = result.get('server_summary') or {}
    findings = result.get('findings') or []
    metrics = [
        {'label': '健康分', 'value': f"{result.get('health_score', '-')} 分"},
        {'label': '发现项', 'value': str(len(findings))},
    ]
    if schedule.profile == 'cluster':
        metrics.extend([
            {'label': 'Ready 节点', 'value': f"{summary.get('ready_nodes', 0)}/{summary.get('node_count', 0)}"},
            {'label': 'Pod 数量', 'value': str(summary.get('pod_count', 0))},
        ])
    else:
        for label, key in [('CPU', 'node_cpu'), ('内存', 'node_memory'), ('负载', 'node_load'), ('磁盘', 'disk_usage')]:
            if server.get(key) is not None:
                metrics.append({'label': label, 'value': str(server.get(key))})
    return [
        {
            'id': 'inspection-overview',
            'type': 'report',
            'title': f'{schedule.get_profile_display()}报告',
            'summary': result.get('conclusion') or '巡检已完成',
            'metrics': metrics[:6],
            'items': [
                {
                    'text': f"[{str(item.get('severity') or 'info').upper()}] {item.get('target') or item.get('namespace') or '范围'}",
                    'detail': item.get('message') or item.get('code') or '异常',
                    'status': item.get('severity') or 'info',
                }
                for item in findings[:12]
            ],
        },
        {
            'id': 'inspection-evidence',
            'type': 'evidence_timeline',
            'title': '证据覆盖',
            'summary': generated_at.strftime('%Y-%m-%d %H:%M:%S'),
            'items': [
                {'text': key, 'detail': '已获取' if value else '未获取', 'status': 'completed' if value else 'failed'}
                for key, value in (result.get('evidence', {}).get('source_coverage') or {}).items()
            ],
        },
    ]


def _format_report(schedule, result):
    summary = result.get('cluster_summary') or {}
    server_summary = result.get('server_summary') or {}
    findings = result.get('findings') or []
    missing = result.get('missing_evidence') or []
    context = schedule.knowledge_environment
    generated_at = timezone.localtime(timezone.now(), _schedule_timezone(schedule))
    result['generated_at'] = generated_at.isoformat()
    result['source_coverage'] = (result.get('evidence') or {}).get('source_coverage') or {}
    result['blocks'] = _report_blocks(schedule, result, generated_at)
    title = f'【巡检报告】{context.name} · {schedule.get_profile_display()}'
    lines = [
        f'**业务上下文：** {context.name}',
        f'**巡检范围：** {schedule.get_profile_display()}',
        f'**生成时间：** {generated_at.strftime("%Y-%m-%d %H:%M:%S")}',
        f'**总体结论：** {result.get("conclusion") or "巡检已完成"}',
        f'**健康分：** {result.get("health_score", "-")} 分',
    ]
    if schedule.profile == 'server':
        lines.extend([
            '',
            '### 服务器概览',
            f'- 主机数量：{server_summary.get("node_count", "-")}',
            f'- CPU 使用率：{server_summary.get("node_cpu", "-")}',
            f'- 内存使用率：{server_summary.get("node_memory", "-")}',
            f'- 一分钟负载：{server_summary.get("node_load", "-")}',
            f'- 磁盘使用率：{server_summary.get("disk_usage", "-")}',
            '',
            '### 发现项',
        ])
    else:
        lines.extend([
            '',
            '### 集群概览',
            f'- 节点：{summary.get("ready_nodes", 0)}/{summary.get("node_count", 0)} Ready',
            f'- Pod：{summary.get("pod_count", 0)}，状态分布 {summary.get("pod_status") or {}}',
            '',
            '### 发现项',
        ])
    if findings:
        for item in findings[:12]:
            lines.append(
                f'- [{str(item.get("severity") or "info").upper()}] '
                f'{item.get("target") or item.get("namespace") or "集群"}：{item.get("message") or item.get("code") or "异常"}'
            )
        if len(findings) > 12:
            lines.append(f'- 其余 {len(findings) - 12} 项请进入平台查看完整报告')
    else:
        lines.append('- 未发现明确异常')
    lines.extend(['', '### 建议操作'])
    for suggestion in result.get('suggestions') or ['保持当前监控并按计划复查']:
        lines.append(f'- {suggestion}')
    if missing:
        lines.extend(['', '### 未获取证据'])
        lines.extend(f'- {item}' for item in missing[:8])
    lines.extend(['', '请登录 XingCloud，在可观测、日志、告警和资产页面查看完整证据。'])
    result['markdown'] = '\n'.join(lines)
    return title, result['markdown']


def _display_report_value(value):
    if value is None or value == '':
        return '未获取'
    if isinstance(value, float):
        return f'{value:.2f}'
    return str(value)


def _append_report_section(lines, title, items, empty_text='未获取到该类数据'):
    lines.extend(['', f'### {title}'])
    if items:
        lines.extend(f'- {item}' for item in items)
    else:
        lines.append(f'- {empty_text}')


def _format_detailed_report(schedule, result):
    """Build a complete evidence-backed notification without waiting for an LLM."""
    evidence = result.get('evidence') or {}
    summary = result.get('cluster_summary') or {}
    server_summary = result.get('server_summary') or {}
    findings = result.get('findings') or []
    missing = result.get('missing_evidence') or []
    k8s = evidence.get('k8s') or {}
    nodes = k8s.get('nodes') or []
    pods = k8s.get('pods') or []
    resources = k8s.get('resources') or {}
    logs = evidence.get('logs') or {}
    context = schedule.knowledge_environment
    generated_at = timezone.localtime(timezone.now(), _schedule_timezone(schedule))
    coverage = evidence.get('source_coverage') or {}

    result['generated_at'] = generated_at.isoformat()
    result['source_coverage'] = coverage
    result['blocks'] = _report_blocks(schedule, result, generated_at)
    title = f'【巡检报告】{context.name} · {schedule.get_profile_display()}'
    lines = [
        f'**业务上下文：** {context.name}',
        f'**巡检范围：** {schedule.get_profile_display()}',
        f'**巡检时间：** {generated_at.strftime("%Y-%m-%d %H:%M:%S")}',
        f'**总体结论：** {result.get("conclusion") or "巡检已完成"}',
        f'**健康分：** {result.get("health_score", "-")} 分',
    ]
    _append_report_section(lines, '数据源覆盖', [
        f'{name}：{"已获取" if enabled else "未获取"}' for name, enabled in coverage.items()
    ])
    if schedule.profile == 'server':
        _append_report_section(lines, '服务器资源指标', [
            f'主机数量：{_display_report_value(server_summary.get("node_count"))}',
            f'CPU 使用率：{_display_report_value(server_summary.get("node_cpu"))}',
            f'内存使用率：{_display_report_value(server_summary.get("node_memory"))}',
            f'一分钟负载：{_display_report_value(server_summary.get("node_load"))}',
            f'磁盘使用率：{_display_report_value(server_summary.get("disk_usage"))}',
        ])
    else:
        _append_report_section(lines, '集群概览', [
            f'集群：{(k8s.get("cluster") or {}).get("name") or "未获取"}',
            f'节点 Ready：{summary.get("ready_nodes", 0)}/{summary.get("node_count", 0)}',
            f'Pod 总数：{summary.get("pod_count", 0)}',
            f'Pod 状态分布：{summary.get("pod_status") or "未获取"}',
        ])
        _append_report_section(lines, '节点状态', [
            f'{node.get("name") or "未命名节点"}：{node.get("status") or "Unknown"}'
            for node in nodes[:20]
        ])
        restart_pods = sorted(pods, key=lambda item: int(item.get('restarts') or 0), reverse=True)
        _append_report_section(lines, 'Pod 与重启排行', [
            f'{pod.get("namespace") or "default"}/{pod.get("name") or "未命名 Pod"}：'
            f'{pod.get("status") or "Unknown"}，重启 {pod.get("restarts") or 0} 次'
            for pod in restart_pods[:10]
        ])
        workload_items = []
        for kind, label, desired_key, ready_key in [
            ('deployments', 'Deployment', 'replicas', 'ready_replicas'),
            ('statefulsets', 'StatefulSet', 'replicas', 'ready_replicas'),
            ('daemonsets', 'DaemonSet', 'desired', 'ready'),
        ]:
            items = resources.get(kind) or []
            unhealthy = [item for item in items if item.get(desired_key) != item.get(ready_key)]
            workload_items.append(f'{label}：{len(items)} 个，副本未就绪 {len(unhealthy)} 个')
        _append_report_section(lines, '工作负载副本', workload_items)
        pvcs = resources.get('pvcs') or []
        unbound_pvcs = [item for item in pvcs if item.get('status') != 'Bound']
        _append_report_section(lines, '存储与 PVC', [
            f'PVC：{len(pvcs)} 个，未绑定 {len(unbound_pvcs)} 个',
            *[f'{item.get("namespace") or "default"}/{item.get("name")}：{item.get("status") or "Unknown"}' for item in unbound_pvcs[:10]],
        ])
    metric_lines = []
    for metric in sorted(evidence.get('metrics') or [], key=lambda item: str(item.get('title') or item.get('code') or '')):
        if metric.get('status') == 'ok' and metric.get('latest') is not None:
            suffix = '（偏离历史基线）' if (metric.get('anomaly') or {}).get('is_anomaly') else ''
            metric_lines.append(f'{metric.get("title") or metric.get("code")}：{_display_report_value(metric.get("latest"))}{suffix}')
        else:
            metric_lines.append(f'{metric.get("title") or metric.get("code")}：未获取')
    _append_report_section(lines, '指标采样', metric_lines[:16])
    samples = logs.get('samples') or []
    _append_report_section(lines, '日志与事件', [
        f'日志样本：{len(samples)} 条；异常日志：{len(evidence.get("log_findings") or [])} 项',
        *[str(item.get('message') or item.get('text') or item)[:240] for item in samples[:5]],
        *[str(item.get('message') or item.get('reason') or item)[:240] for item in (evidence.get('event_findings') or [])[:5]],
    ])
    _append_report_section(lines, '风险项', [
        f'[{str(item.get("severity") or "info").upper()}] '
        f'{item.get("target") or item.get("namespace") or "集群"}：'
        f'{item.get("message") or item.get("code") or "异常"}'
        for item in findings[:20]
    ], empty_text='未发现明确异常')
    change_summary = result.get('change_summary') or {}
    if change_summary:
        change = change_summary.get('summary') or {}
        _append_report_section(lines, '与上次巡检对比', [
            f'新增：{change.get("added", 0)} 项；恶化：{change.get("worsened", 0)} 项；恢复：{change.get("resolved", 0)} 项'
        ])
    _append_report_section(lines, '建议操作', result.get('suggestions') or ['保持当前监控并按计划复查'])
    if missing:
        _append_report_section(lines, '未获取证据及原因', missing[:12])
    lines.extend(['', '请登录 XingCloud 查看对应监控、日志、告警和资产详情。'])
    result['markdown'] = '\n'.join(lines)
    return title, result['markdown']


def _report_status_badge(status):
    value = str(status or '').lower()
    if value in {'critical', 'failed', 'error'}:
        return '❌ 异常'
    if value in {'warning', 'warn'}:
        return '⚠️ 警告'
    if value in {'unknown', 'unavailable', 'partial'}:
        return '⚪ 数据缺失'
    return '✅ 正常'


def _report_table(headers, rows):
    """Render small, Feishu-compatible Markdown tables from collected evidence."""
    def clean(value):
        return str(value if value not in (None, '') else '-').replace('|', '／').replace('\n', ' ')

    if not rows:
        return ''
    header = '| ' + ' | '.join(headers) + ' |'
    align = '| ' + ' | '.join(':---' for _ in headers) + ' |'
    body = ['| ' + ' | '.join(clean(value) for value in row) + ' |' for row in rows]
    return '\n'.join([header, align, *body])


def _format_skill_style_report(schedule, result):
    """Format scheduled inspections as a deterministic Agent-1-style report."""
    evidence = result.get('evidence') or {}
    summary = result.get('cluster_summary') or {}
    server_summary = result.get('server_summary') or {}
    k8s = evidence.get('k8s') or {}
    nodes = k8s.get('nodes') or []
    pods = k8s.get('pods') or []
    resources = k8s.get('resources') or {}
    logs = evidence.get('logs') or {}
    findings = result.get('findings') or []
    missing = result.get('missing_evidence') or []
    coverage = evidence.get('source_coverage') or {}
    context = schedule.knowledge_environment
    generated_at = timezone.localtime(timezone.now(), _schedule_timezone(schedule))
    metrics = evidence.get('metrics') or []
    metric_ok = sum(1 for item in metrics if item.get('status') == 'ok' and item.get('latest') is not None)
    metric_warning = sum(1 for item in metrics if (item.get('anomaly') or {}).get('is_anomaly'))
    metric_missing = len(metrics) - metric_ok

    result['generated_at'] = generated_at.isoformat()
    result['source_coverage'] = coverage
    result['blocks'] = _report_blocks(schedule, result, generated_at)
    title = f'【巡检报告】{context.name} · {schedule.get_profile_display()}'
    scope = schedule.get_profile_display()
    lines = [
        '━━━━━━━━━━━━━━━━━━━━',
        f'📋 {scope} · {context.name}',
        f'时间：{generated_at.strftime("%Y-%m-%d %H:%M:%S")} · 证据窗口：{schedule.window_minutes} 分钟',
        '━━━━━━━━━━━━━━━━━━━━',
        '',
        '## 📊 巡检摘要',
    ]
    if schedule.profile == 'server':
        summary_rows = [[
            f'{result.get("health_score", "-")} 分',
            _report_status_badge('partial' if result.get('status') == 'partial' else 'normal'),
            _display_report_value(server_summary.get('node_count')),
            metric_ok,
            metric_warning,
            metric_missing,
        ]]
        lines.append(_report_table(['健康分', '结论状态', '主机数', '有效指标', '指标告警', '指标缺失'], summary_rows))
    else:
        summary_rows = [[
            f'{result.get("health_score", "-")} 分',
            _report_status_badge('partial' if result.get('status') == 'partial' else 'normal'),
            f'{summary.get("ready_nodes", 0)}/{summary.get("node_count", 0)}',
            summary.get('pod_count', 0),
            metric_ok,
            metric_missing,
        ]]
        lines.append(_report_table(['健康分', '结论状态', 'Ready 节点', 'Pod 数', '有效指标', '指标缺失'], summary_rows))
    lines.extend(['', f'> {result.get("conclusion") or "巡检已完成"}'])

    lines.extend(['', '## 📡 数据源覆盖'])
    coverage_table = _report_table(['来源', '状态', '说明'], [
        [name, '✅ 已获取' if enabled else '⚪ 未获取', '可用于本次巡检' if enabled else '该来源未参与健康结论']
        for name, enabled in coverage.items()
    ])
    lines.append(coverage_table or '⚪ 未登记数据源覆盖信息')

    if schedule.profile == 'server':
        lines.extend(['', '## 🖥️ 服务器资源（来源：Prometheus）'])
        lines.append(_report_table(['指标', '当前值', '状态'], [
            ['CPU 使用率', _display_report_value(server_summary.get('node_cpu')), _report_status_badge('unknown' if server_summary.get('node_cpu') is None else 'normal')],
            ['内存使用率', _display_report_value(server_summary.get('node_memory')), _report_status_badge('unknown' if server_summary.get('node_memory') is None else 'normal')],
            ['一分钟负载', _display_report_value(server_summary.get('node_load')), _report_status_badge('unknown' if server_summary.get('node_load') is None else 'normal')],
            ['磁盘使用率', _display_report_value(server_summary.get('disk_usage')), _report_status_badge('unknown' if server_summary.get('disk_usage') is None else 'normal')],
        ]))
    else:
        lines.extend(['', '## 🖥️ 节点状态（来源：K8s API）'])
        lines.append(_report_table(['节点', '状态'], [
            [item.get('name') or '未命名节点', _report_status_badge('normal' if item.get('status') == 'Ready' else 'critical')]
            for item in nodes[:20]
        ]))
        lines.extend(['', '## 📦 Pod 状态与重启排行（来源：K8s API）'])
        restart_pods = sorted(pods, key=lambda item: int(item.get('restarts') or 0), reverse=True)
        lines.append(_report_table(['命名空间', 'Pod', '状态', '重启次数', '巡检状态'], [
            [
                item.get('namespace') or 'default', item.get('name') or '未命名 Pod',
                item.get('status') or 'Unknown', item.get('restarts') or 0,
                _report_status_badge('warning' if int(item.get('restarts') or 0) > 5 else ('normal' if item.get('status') in {'Running', 'Succeeded'} else 'warning')),
            ] for item in restart_pods[:10]
        ]))
        lines.extend(['', '## 🧩 工作负载与存储（来源：K8s API）'])
        workload_rows = []
        for kind, label, desired_key, ready_key in [
            ('deployments', 'Deployment', 'replicas', 'ready_replicas'),
            ('statefulsets', 'StatefulSet', 'replicas', 'ready_replicas'),
            ('daemonsets', 'DaemonSet', 'desired', 'ready'),
        ]:
            items = resources.get(kind) or []
            unhealthy = [item for item in items if item.get(desired_key) != item.get(ready_key)]
            workload_rows.append([label, len(items), len(unhealthy), _report_status_badge('warning' if unhealthy else 'normal')])
        pvcs = resources.get('pvcs') or []
        unbound_pvcs = [item for item in pvcs if item.get('status') != 'Bound']
        workload_rows.append(['PVC', len(pvcs), len(unbound_pvcs), _report_status_badge('warning' if unbound_pvcs else 'normal')])
        lines.append(_report_table(['资源类型', '总数', '异常/未就绪', '状态'], workload_rows))

    lines.extend(['', '## 📈 指标巡检（来源：Prometheus）'])
    metric_rows = []
    for item in sorted(metrics, key=lambda row: str(row.get('title') or row.get('code') or ''))[:20]:
        anomaly = (item.get('anomaly') or {}).get('is_anomaly')
        status = 'warning' if anomaly else ('normal' if item.get('status') == 'ok' and item.get('latest') is not None else 'unknown')
        metric_rows.append([
            item.get('title') or item.get('code'),
            _display_report_value(item.get('latest')),
            _report_status_badge(status),
            '偏离历史基线' if anomaly else ('采样正常' if status == 'normal' else '指标不存在、无数据或查询失败'),
        ])
    lines.append(_report_table(['指标', '当前值', '状态', '说明'], metric_rows) or '⚪ 未获取指标采样结果')

    lines.extend(['', '## 🔍 日志与事件'])
    samples = logs.get('samples') or []
    lines.append(_report_table(['项目', '数量/内容', '状态'], [
        ['日志样本', f'{len(samples)} 条', _report_status_badge('normal' if coverage.get('logs') else 'unknown')],
        ['异常日志', f'{len(evidence.get("log_findings") or [])} 项', _report_status_badge('warning' if evidence.get('log_findings') else 'normal')],
        ['Warning Event', f'{len(evidence.get("event_findings") or [])} 项', _report_status_badge('warning' if evidence.get('event_findings') else 'normal')],
    ]))
    if samples:
        lines.append('最近异常日志样本：')
        lines.extend(f'- {str(item.get("message") or item.get("text") or item)[:240]}' for item in samples[:5])

    lines.extend(['', '## ⚠️ 巡检发现'])
    lines.append(_report_table(['级别', '对象', '发现'], [
        [_report_status_badge(item.get('severity')), item.get('target') or item.get('namespace') or '集群', item.get('message') or item.get('code') or '异常']
        for item in findings[:20]
    ]) or '✅ 未发现明确异常')

    lines.extend(['', '## 🧪 数据质量'])
    quality_rows = [[
        '采集完整性',
        f'{sum(1 for value in coverage.values() if value)}/{len(coverage)} 个来源可用',
        _report_status_badge('normal' if all(coverage.values()) else 'partial'),
    ]]
    quality_rows.extend([['缺失证据', item, '⚪ 数据缺失'] for item in missing[:12]])
    lines.append(_report_table(['项目', '说明', '状态'], quality_rows))

    lines.extend(['', '## ✅ 建议操作'])
    lines.append(_report_table(['优先级', '操作建议', '目的'], [
        ['P0', item, '恢复关键监控或处理当前异常'] for item in (result.get('suggestions') or ['保持当前监控并按计划复查'])
    ]))
    lines.extend(['', '━━━━━━━━━━━━━━━━━━━━', '报告仅基于 Prometheus、K8s API、日志源与资产证据生成；数据缺失不作推断。', '━━━━━━━━━━━━━━━━━━━━'])
    result['markdown'] = '\n'.join(lines)
    return title, result['markdown']


def run_inspection_report_schedule(schedule, *, trigger=InspectionReportExecution.TRIGGER_SCHEDULER):
    schedule = InspectionReportSchedule.objects.select_related('knowledge_environment').prefetch_related(
        'channels', 'recipients', 'recipient_groups__recipients', 'recipient_groups__users',
    ).get(pk=schedule.pk)
    previous_execution = schedule.executions.filter(
        status__in=[InspectionReportExecution.STATUS_SUCCESS, InspectionReportExecution.STATUS_PARTIAL],
    ).order_by('-started_at', '-id').first()
    execution = InspectionReportExecution.objects.create(schedule=schedule, trigger=trigger)
    try:
        evidence = collect_observability_evidence(
            schedule.knowledge_environment_id,
            profile=schedule.profile,
            depth=schedule.depth,
            window_minutes=schedule.window_minutes,
        )
        report = inspection_result(evidence)
        change_summary = _inspection_change_summary(
            previous_execution.report if previous_execution else {}, report,
        )
        report['change_summary'] = change_summary
        title, body = _format_skill_style_report(schedule, report)
        should_notify = (
            trigger == InspectionReportExecution.TRIGGER_MANUAL
            or not schedule.notify_changes_only
            or change_summary['has_changes']
        )
        if should_notify:
            contacts = build_recipient_contacts(
                groups=schedule.recipient_groups.filter(is_enabled=True),
                recipients=schedule.recipients.filter(is_enabled=True),
            )
            delivery_results = [
                send_plain_notification(channel, contacts, title=title, body=body)
                for channel in schedule.channels.filter(is_enabled=True)
            ]
        else:
            delivery_results = [{'status': 'skipped', 'reason': '巡检无新增或恶化项，按计划设置不发送'}]
        success_count = sum(1 for item in delivery_results if item.get('status') == 'success')
        failed_count = sum(1 for item in delivery_results if item.get('status') != 'success')
        if not should_notify:
            execution_status = InspectionReportExecution.STATUS_SUCCESS
            schedule_status = InspectionReportSchedule.STATUS_SUCCESS
        elif success_count and not failed_count:
            execution_status = InspectionReportExecution.STATUS_SUCCESS
            schedule_status = InspectionReportSchedule.STATUS_SUCCESS
        elif success_count:
            execution_status = InspectionReportExecution.STATUS_PARTIAL
            schedule_status = InspectionReportSchedule.STATUS_PARTIAL
        else:
            execution_status = InspectionReportExecution.STATUS_FAILED
            schedule_status = InspectionReportSchedule.STATUS_FAILED
        execution.status = execution_status
        execution.report = {**report, 'notification_title': title, 'notification_body': body}
        execution.delivery_results = delivery_results
        execution.change_summary = change_summary
        execution.completed_at = timezone.now()
        execution.save(update_fields=['status', 'report', 'delivery_results', 'change_summary', 'completed_at'])
        schedule.last_run_at = execution.completed_at
        schedule.last_status = schedule_status
        schedule.last_error = '; '.join(
            item.get('error_message') or item.get('response_body') or ''
            for item in delivery_results if item.get('status') != 'success'
        )[:2000]
        schedule.last_report = execution.report
        schedule.save(update_fields=['last_run_at', 'last_status', 'last_error', 'last_report', 'updated_at'])
    except Exception as exc:
        logger.exception('inspection report schedule %s failed', schedule.id)
        execution.status = InspectionReportExecution.STATUS_FAILED
        execution.error_message = str(exc)[:4000]
        execution.completed_at = timezone.now()
        execution.save(update_fields=['status', 'error_message', 'completed_at'])
        schedule.last_run_at = execution.completed_at
        schedule.last_status = InspectionReportSchedule.STATUS_FAILED
        schedule.last_error = str(exc)[:2000]
        schedule.save(update_fields=['last_run_at', 'last_status', 'last_error', 'updated_at'])
    return execution


def run_due_inspection_reports(limit=20):
    now = timezone.now()
    due_ids = list(
        InspectionReportSchedule.objects.filter(
            is_enabled=True, next_run_at__isnull=False, next_run_at__lte=now,
        ).order_by('next_run_at', 'id').values_list('id', flat=True)[:limit]
    )
    completed = failed = 0
    for schedule_id in due_ids:
        try:
            with transaction.atomic():
                schedule = InspectionReportSchedule.objects.select_for_update().get(pk=schedule_id)
                if not schedule.is_enabled or not schedule.next_run_at or schedule.next_run_at > timezone.now():
                    continue
                schedule.next_run_at = compute_next_inspection_report_run(schedule, now=timezone.now())
                schedule.save(update_fields=['next_run_at', 'updated_at'])
            execution = run_inspection_report_schedule(schedule)
            if execution.status in {InspectionReportExecution.STATUS_SUCCESS, InspectionReportExecution.STATUS_PARTIAL}:
                completed += 1
            else:
                failed += 1
        except Exception:
            failed += 1
            logger.exception('scheduled inspection report %s failed before execution', schedule_id)
    return {'checked': len(due_ids), 'completed': completed, 'failed': failed}
