import math
import random
import statistics


def _result(name, eligible, anomaly=False, score=0.0, threshold=0.0, detail=''):
    return {
        'algorithm': name,
        'eligible': bool(eligible),
        'is_anomaly': bool(anomaly) if eligible else False,
        'score': round(float(score or 0), 4),
        'threshold': threshold,
        'detail': detail,
    }


def _percentile(values, percentile):
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = (len(ordered) - 1) * percentile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def _sigma(history, current, threshold=3.0, name='3-Sigma'):
    if len(history) < 10:
        return _result(name, False, detail='至少需要10个历史样本')
    mean = statistics.fmean(history)
    deviation = statistics.pstdev(history)
    if deviation == 0:
        return _result(name, True, False, 0, threshold, '历史序列无波动')
    score = abs(current - mean) / deviation
    return _result(name, True, score > threshold, score, threshold, f'mean={mean:.4f}, std={deviation:.4f}')


def _ewma(history, current, alpha=0.3, threshold=3.0):
    if len(history) < 5:
        return _result('EWMA', False, detail='至少需要5个历史样本')
    mean = history[0]
    variance = 0.0
    for value in history[1:]:
        previous = mean
        mean = alpha * value + (1 - alpha) * mean
        variance = alpha * ((value - previous) ** 2) + (1 - alpha) * variance
    deviation = math.sqrt(max(variance, 0.0))
    if deviation == 0:
        return _result('EWMA', True, False, 0, threshold, 'EWMA历史序列无波动')
    score = abs(current - mean) / deviation
    return _result('EWMA', True, score > threshold, score, threshold, f'ewma={mean:.4f}, std={deviation:.4f}')


def _iqr(history, current, multiplier=1.5):
    if len(history) < 20:
        return _result('IQR', False, detail='至少需要20个历史样本')
    q1, q3 = _percentile(history, 0.25), _percentile(history, 0.75)
    spread = q3 - q1
    if spread == 0:
        return _result('IQR', True, False, 0, multiplier, 'IQR为0')
    lower, upper = q1 - multiplier * spread, q3 + multiplier * spread
    score = max((lower - current) / spread, (current - upper) / spread, 0)
    return _result('IQR', True, current < lower or current > upper, score, multiplier, f'range=[{lower:.4f}, {upper:.4f}]')


def _isolation_path(values, current, rng, depth=0, max_depth=8):
    if depth >= max_depth or len(values) <= 1 or min(values) == max(values):
        return depth + math.log2(max(len(values), 1))
    split = rng.uniform(min(values), max(values))
    left = [value for value in values if value < split]
    right = [value for value in values if value >= split]
    branch = left if current < split else right
    return _isolation_path(branch or values, current, rng, depth + 1, max_depth)


def _isolation_forest(history, current, trees=48, threshold=0.65):
    if len(history) < 20:
        return _result('Isolation Forest', False, detail='至少需要20个历史样本')
    rng = random.Random(20260716)
    sample_size = min(64, len(history))
    paths = []
    for _ in range(trees):
        sample = rng.sample(history, sample_size) if len(history) > sample_size else list(history)
        paths.append(_isolation_path(sample, current, rng, max_depth=max(5, math.ceil(math.log2(sample_size)))))
    average_path = statistics.fmean(paths)
    normalizer = 2 * (math.log(max(sample_size - 1, 1)) + 0.5772156649) - (2 * (sample_size - 1) / sample_size)
    score = 2 ** (-average_path / max(normalizer, 1e-9))
    return _result('Isolation Forest', True, score >= threshold, score, threshold, f'average_path={average_path:.4f}')


def detect_anomaly(values, min_votes=2):
    cleaned = []
    for value in values or []:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            cleaned.append(number)
    if len(cleaned) < 2:
        return {'is_anomaly': False, 'confidence': 0.0, 'vote_count': 0, 'eligible_count': 0, 'algorithms': []}
    history, current = cleaned[:-1], cleaned[-1]
    algorithms = [
        _sigma(history, current, 3.0, '3-Sigma'),
        _ewma(history, current),
        _iqr(history, current),
        _sigma(history, current, 2.5, 'Z-Score'),
        _isolation_forest(history, current),
    ]
    eligible = [item for item in algorithms if item['eligible']]
    votes = [item for item in eligible if item['is_anomaly']]
    required = min_votes if len(eligible) >= min_votes else len(eligible) + 1
    return {
        'is_anomaly': len(votes) >= required,
        'confidence': round(len(votes) / len(eligible), 4) if eligible else 0.0,
        'vote_count': len(votes),
        'eligible_count': len(eligible),
        'current': current,
        'algorithms': algorithms,
    }
