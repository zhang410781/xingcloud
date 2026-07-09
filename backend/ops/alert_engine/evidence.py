def result_evidence(source_type, *, query='', value=None, labels=None, raw=None, sql=''):
    evidence = {
        'source_type': source_type,
        'query': query,
        'sql': sql,
        'value': value,
        'labels': labels or {},
    }
    if raw is not None:
        evidence['raw'] = raw
    return {key: value for key, value in evidence.items() if value not in (None, '', {}, [])}


def evidence_summary(results):
    return [
        {
            'source_type': item.get('source_type'),
            'value': item.get('value'),
            'labels': item.get('labels') or {},
            'query': (item.get('evidence') or {}).get('query') or '',
            'sql': (item.get('evidence') or {}).get('sql') or '',
        }
        for item in results or []
    ]
