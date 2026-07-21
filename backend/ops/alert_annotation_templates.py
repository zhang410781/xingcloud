import re


EXPRESSION_RE = re.compile(r'{{\s*(.*?)\s*}}')
LABEL_RE = re.compile(r'^\$labels\.([A-Za-z_][A-Za-z0-9_]*)$')
PRINTF_RE = re.compile(r'^printf\s+"%(?:\.([0-6]))?f"\s+\$value$')


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _render_expression(expression, labels, value):
    expression = expression.strip()
    label_match = LABEL_RE.match(expression)
    if label_match:
        result = labels.get(label_match.group(1))
        return str(result) if result not in (None, '') else '-', None
    if expression == '$value':
        return str(value) if value not in (None, '') else '-', None
    printf_match = PRINTF_RE.match(expression)
    if printf_match:
        number = _number(value)
        if number is None:
            return '-', '数值格式化失败：$value不是数字'
        precision = int(printf_match.group(1) or 6)
        return f'{number:.{precision}f}', None
    if re.fullmatch(r'\$value\s*\|\s*humanizePercentage', expression):
        number = _number(value)
        if number is None:
            return '-', '百分比格式化失败：$value不是数字'
        return f'{number * 100:.2f}%', None
    return '-', f'不支持的模板表达式：{expression}'


def render_annotation_template(template, *, labels=None, value=None):
    text = str(template or '')
    labels = labels if isinstance(labels, dict) else {}
    diagnostics = []

    def replace(match):
        rendered, error = _render_expression(match.group(1), labels, value)
        if error:
            diagnostics.append(error)
        return rendered

    return EXPRESSION_RE.sub(replace, text), diagnostics


def render_rule_annotations(rule, *, labels=None, value=None):
    annotations = rule.annotations if isinstance(rule.annotations, dict) else {}
    rendered = {}
    diagnostics = []
    for key in ('summary', 'message', 'description'):
        text, errors = render_annotation_template(annotations.get(key), labels=labels, value=value)
        rendered[key] = text
        diagnostics.extend(errors)
    rendered['summary'] = rendered['summary'] or rule.name
    rendered['message'] = rendered['message'] or rendered['description'] or rule.description or rule.name
    return rendered, diagnostics


def notification_preview(*, name, annotations, labels, value, level='warning', resource=''):
    class PreviewRule:
        pass

    preview_rule = PreviewRule()
    preview_rule.name = name or '未命名告警'
    preview_rule.description = ''
    preview_rule.annotations = annotations if isinstance(annotations, dict) else {}
    rendered, diagnostics = render_rule_annotations(preview_rule, labels=labels, value=value)
    namespace = labels.get('namespace') or '-'
    target = resource or labels.get('pod') or labels.get('node') or labels.get('instance') or labels.get('deployment') or '-'
    return {
        'title': rendered['summary'],
        'summary': rendered['message'],
        'description': rendered['description'] or '无描述',
        'impact_scope': f'{namespace}/{target}',
        'level': level,
        'labels': labels,
        'value': value,
        'diagnostics': diagnostics,
    }

