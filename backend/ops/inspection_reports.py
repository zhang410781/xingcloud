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
        title, body = _format_report(schedule, report)
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
