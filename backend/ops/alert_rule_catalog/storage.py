from .common import rule


RULES = [
    rule('storage', 'k8s-pv-available-low', 'K8S PVC 可用空间过低',
         'kubelet_volume_stats_available_bytes{job="kubelet",metrics_path="/metrics"} / clamp_min(kubelet_volume_stats_capacity_bytes{job="kubelet",metrics_path="/metrics"}, 1) * 100',
         {'levels': [
             {'level': 'warning', 'operator': '<', 'threshold': 20, 'duration_seconds': 300},
             {'level': 'critical', 'operator': '<', 'threshold': 10, 'duration_seconds': 60},
         ]}, duration=300, unit='percent', profile='full',
         message='{{ $labels.cluster }} 集群命名空间 {{ $labels.namespace }} 的 PVC {{ $labels.persistentvolumeclaim }} 只剩 {{ printf "%.2f" $value }}% 可用空间。',
         description='PVC可用容量低于Agent-1存储阈值。', source_names=('K8S的PV使用量警报',), sort_order=1100),
    rule('storage', 'k8s-pv-full-in-four-days', 'K8S PVC 预计四天内用尽',
         '(kubelet_volume_stats_available_bytes{job="kubelet",metrics_path="/metrics"} / clamp_min(kubelet_volume_stats_capacity_bytes{job="kubelet",metrics_path="/metrics"}, 1) * 100 < 15) and predict_linear(kubelet_volume_stats_available_bytes{job="kubelet",metrics_path="/metrics"}[6h], 4 * 24 * 3600) < 0',
         {'operator': '>', 'threshold': 0}, level='critical', duration=3600, unit='percent', profile='full',
         message='{{ $labels.cluster }} 集群命名空间 {{ $labels.namespace }} 的 PVC {{ $labels.persistentvolumeclaim }} 预计四天内用尽。',
         description='基于近6小时容量趋势预测PVC四天内耗尽。', source_names=('KubePersistentVolumeFullInFourDays',), sort_order=1110),
    rule('storage', 'k8s-pv-phase-error', 'K8S PV 状态异常',
         'kube_persistentvolume_status_phase{phase=~"Failed|Pending",job="kube-state-metrics"}',
         {'operator': '>', 'threshold': 0}, level='critical', duration=300, profile='full',
         message='{{ $labels.cluster }} 集群 PV {{ $labels.persistentvolume }} 的状态为 {{ $labels.phase }}。',
         description='PV持续处于Failed或Pending状态。', source_names=('K8S的PV错误',), sort_order=1120),
]

