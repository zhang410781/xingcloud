from .common import rule


DEVICE_FILTER = 'device!~"lo|veth.*|cali.*|flannel.*|vxlan.*|docker.*|br-.*"'

RULES = [
    rule('network', 'k8s-node-network-flapping', '节点网卡状态频繁变化',
         f'changes(node_network_up{{job="node-exporter",{DEVICE_FILTER}}}[2m])',
         {'operator': '>', 'threshold': 2}, duration=120,
         message='{{ $labels.cluster }} 集群 {{ $labels.instance }} 节点上的网卡 {{ $labels.device }} 状态频繁变化。',
         description='物理网卡在2分钟内多次改变状态。', source_names=('Node网络网卡抖动',), sort_order=1000),
    rule('network', 'k8s-node-network-receive-errors', '节点下行网络错误',
         f'rate(node_network_receive_errs_total{{{DEVICE_FILTER}}}[5m])',
         {'levels': [
             {'level': 'warning', 'operator': '>', 'threshold': 0, 'duration_seconds': 300},
             {'level': 'critical', 'operator': '>', 'threshold': 10, 'duration_seconds': 300},
         ]}, duration=300, unit='ops',
         message='{{ $labels.cluster }} 集群 {{ $labels.instance }} 节点的网络设备 {{ $labels.device }} 检测到接收错误（{{ printf "%.2f" $value }}/s）。',
         description='节点物理网卡接收错误率。', source_names=('节点下行网络错误',), sort_order=1010),
    rule('network', 'k8s-node-network-transmit-errors', '节点上行网络错误',
         f'rate(node_network_transmit_errs_total{{{DEVICE_FILTER}}}[5m])',
         {'levels': [
             {'level': 'warning', 'operator': '>', 'threshold': 0, 'duration_seconds': 300},
             {'level': 'critical', 'operator': '>', 'threshold': 10, 'duration_seconds': 300},
         ]}, duration=300, unit='ops',
         message='{{ $labels.cluster }} 集群 {{ $labels.instance }} 节点的网络设备 {{ $labels.device }} 检测到发送错误（{{ printf "%.2f" $value }}/s）。',
         description='节点物理网卡发送错误率。', source_names=('节点上行网络错误',), sort_order=1020),
    rule('network', 'k8s-node-network-receive-drops', '节点下行丢包',
         f'rate(node_network_receive_drop_total{{{DEVICE_FILTER}}}[5m])',
         {'operator': '>', 'threshold': 10}, duration=300, unit='ops',
         message='{{ $labels.cluster }} 集群 {{ $labels.instance }} 节点的网络设备 {{ $labels.device }} 接收丢包达到 {{ printf "%.2f" $value }}/s。',
         description='节点物理网卡接收丢包率过高。', source_names=('节点下行丢包',), sort_order=1030),
    rule('network', 'k8s-node-network-transmit-drops', '节点上行丢包',
         f'rate(node_network_transmit_drop_total{{{DEVICE_FILTER}}}[5m])',
         {'operator': '>', 'threshold': 10}, duration=300, unit='ops',
         message='{{ $labels.cluster }} 集群 {{ $labels.instance }} 节点的网络设备 {{ $labels.device }} 发送丢包达到 {{ printf "%.2f" $value }}/s。',
         description='节点物理网卡发送丢包率过高。', source_names=('节点上行丢包',), sort_order=1040),
    rule('network', 'k8s-node-network-receive-bandwidth', '节点下行带宽过高',
         f'irate(node_network_receive_bytes_total{{{DEVICE_FILTER}}}[30s]) / 1024 / 1024',
         {'operator': '>', 'threshold': 100}, duration=30, unit='MB/s',
         message='{{ $labels.cluster }} 集群 {{ $labels.instance }} 节点的网络设备 {{ $labels.device }} 下载带宽达到 {{ printf "%.1f" $value }} MB/s。',
         description='节点物理网卡下载带宽持续超过100MB/s。', source_names=('节点下行带宽过高',), sort_order=1050),
    rule('network', 'k8s-node-network-transmit-bandwidth', '节点上行带宽过高',
         f'irate(node_network_transmit_bytes_total{{{DEVICE_FILTER}}}[30s]) / 1024 / 1024',
         {'operator': '>', 'threshold': 100}, duration=30, unit='MB/s',
         message='{{ $labels.cluster }} 集群 {{ $labels.instance }} 节点的网络设备 {{ $labels.device }} 上传带宽达到 {{ printf "%.1f" $value }} MB/s。',
         description='节点物理网卡上传带宽持续超过100MB/s。', source_names=('节点上行带宽过高',), sort_order=1060),
]

