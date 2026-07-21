from .common import rule


RULES = [
    rule('apiserver', 'k8s-apiserver-latency', 'API Server 请求延迟过高',
         'histogram_quantile(0.99, sum(rate(apiserver_request_duration_seconds_bucket{job="apiserver",verb!~"WATCH|CONNECT"}[5m])) by (cluster,verb,resource,le))',
         {'levels': [
             {'level': 'warning', 'operator': '>', 'threshold': 1, 'duration_seconds': 300},
             {'level': 'critical', 'operator': '>', 'threshold': 4, 'duration_seconds': 300},
         ]}, duration=300, unit='seconds', profile='full',
         message='{{ $labels.cluster }} 集群 API Server 的 {{ $labels.verb }} {{ $labels.resource }} P99 延迟达到 {{ printf "%.2f" $value }} 秒。',
         description='API Server 非 WATCH/CONNECT 请求 P99 延迟持续超过阈值。',
         source_names=('K8S的APISERVER请求延迟过高', 'K8S的APISERVER请求延迟致命'), sort_order=600),
    rule('apiserver', 'k8s-apiserver-error-rate', 'API Server 5XX 错误率过高',
         'sum(rate(apiserver_request_total{job="apiserver",code=~"5.."}[5m])) by (cluster) / clamp_min(sum(rate(apiserver_request_total{job="apiserver"}[5m])) by (cluster), 0.000001)',
         {'levels': [
             {'level': 'warning', 'operator': '>', 'threshold': 0.01, 'duration_seconds': 300},
             {'level': 'critical', 'operator': '>', 'threshold': 0.03, 'duration_seconds': 300},
         ]}, duration=300, unit='ratio', profile='full',
         message='{{ $labels.cluster }} 集群 API Server 5XX 错误率达到 {{ $value | humanizePercentage }}。',
         description='API Server 全局5XX请求比例持续超过阈值。',
         source_names=('K8S的APISERVER存在返回错误过高', 'K8S的APISERVER存在返回错误'), sort_order=610),
    rule('apiserver', 'k8s-apiserver-resource-error-rate', 'API Server 资源请求错误率过高',
         'sum(rate(apiserver_request_total{job="apiserver",code=~"5.."}[5m])) by (cluster,resource,subresource,verb) / clamp_min(sum(rate(apiserver_request_total{job="apiserver"}[5m])) by (cluster,resource,subresource,verb), 0.000001)',
         {'levels': [
             {'level': 'warning', 'operator': '>', 'threshold': 0.05, 'duration_seconds': 300},
             {'level': 'critical', 'operator': '>', 'threshold': 0.10, 'duration_seconds': 300},
         ]}, duration=300, unit='ratio', profile='full',
         message='{{ $labels.cluster }} 集群 API Server 的 {{ $labels.verb }} {{ $labels.resource }}/{{ $labels.subresource }} 请求错误率达到 {{ $value | humanizePercentage }}。',
         description='按资源、子资源和动作统计API Server 5XX错误率。',
         source_names=('K8S的APISERVER资源存在返回错误过高', 'K8S的APISERVER资源存在返回错误'), sort_order=620),
    rule('apiserver', 'k8s-client-certificate-expiring', 'K8S 客户端证书即将过期',
         'histogram_quantile(0.01, sum by (cluster,job,le) (rate(apiserver_client_certificate_expiration_seconds_bucket{job="apiserver"}[5m])))',
         {'levels': [
             {'level': 'warning', 'operator': '<', 'threshold': 604800, 'duration_seconds': 300},
             {'level': 'critical', 'operator': '<', 'threshold': 86400, 'duration_seconds': 300},
         ]}, duration=300, unit='seconds', profile='full',
         message='{{ $labels.cluster }} 集群存在即将在 {{ printf "%.0f" $value }} 秒内过期的K8S客户端证书。',
         description='K8S客户端证书剩余有效期低于7天或24小时。',
         source_names=('K8S客户端证书即将过期', 'K8S客户端证书24小时内过期'), sort_order=630),
    rule('apiserver', 'k8s-apiserver-down', 'API Server 掉线',
         'absent(up{job="apiserver"} == 1)', {'operator': '>', 'threshold': 0},
         level='critical', duration=300, profile='full',
         message='{{ $labels.cluster }} 集群 Prometheus Targets 无法发现可用的 API Server。',
         description='Prometheus未发现任何可用API Server目标。',
         source_names=('APISERVER掉线',), sort_order=640),
]
