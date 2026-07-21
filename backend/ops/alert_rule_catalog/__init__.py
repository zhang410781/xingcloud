from .apiserver import RULES as APISERVER_RULES
from .network import RULES as NETWORK_RULES
from .storage import RULES as STORAGE_RULES
from .system import RULES as SYSTEM_RULES
from .workload import RULES as WORKLOAD_RULES


K8S_AGENT_RULE_TEMPLATES = [
    *APISERVER_RULES,
    *WORKLOAD_RULES,
    *NETWORK_RULES,
    *STORAGE_RULES,
    *SYSTEM_RULES,
]

REFERENCE_RULE_COUNT = 52
NORMALIZED_RULE_COUNT = 46
REFERENCE_RULE_NAMES = tuple(
    name
    for rule in K8S_AGENT_RULE_TEMPLATES
    for name in rule.get('source_rule_names', ())
)

