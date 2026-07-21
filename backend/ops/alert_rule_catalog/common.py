def rule(group, code, name, query, condition, *, level='warning', duration=300,
         message='', description='', notify=True, analyze=True, source_names=(),
         unit='', profile='targeted', sort_order=600):
    group_labels = {
        'apiserver': 'API Server',
        'workload': '工作负载',
        'network': '节点网络',
        'storage': '集群存储',
        'system': '节点系统',
    }
    return {
        'category': 'k8s',
        'code': code,
        'name': name,
        'source_type': 'prometheus',
        'level': level,
        'query_config': {
            'query': query,
            'value_path': 'value',
            'unit': unit,
            'evidence_profile': profile,
        },
        'condition': condition,
        'default_labels': {
            'integration': 'kubernetes',
            'service': 'kubernetes',
            'rule_group': group,
            'rule_group_label': group_labels[group],
            'template_source': 'xing-cloud-ops-agent-agent1-4',
        },
        'annotations': {
            'summary': name,
            'message': message,
            'description': description,
        },
        'interval_seconds': 30 if duration < 60 else 60,
        'duration_seconds': duration,
        'notify_enabled': notify,
        'auto_analyze': analyze,
        'description': description,
        'sort_order': sort_order,
        'source_rule_names': tuple(source_names),
    }

