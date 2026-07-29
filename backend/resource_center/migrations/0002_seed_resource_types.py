from django.db import migrations


RESOURCE_TYPES = [
    ('product', '产品', 'organization', 'Briefcase'),
    ('business_system', '业务系统', 'organization', 'Grid'),
    ('application_service', '应用服务', 'organization', 'Service'),
    ('physical_server', '物理机', 'compute', 'Monitor'),
    ('virtual_machine', '虚拟机', 'compute', 'Cpu'),
    ('k8s_cluster', 'K8S 集群', 'compute', 'Connection'),
    ('k8s_node', 'K8S 节点', 'compute', 'SetUp'),
    ('mysql', 'MySQL', 'platform', 'Coin'),
    ('postgresql', 'PostgreSQL', 'platform', 'Coin'),
    ('redis', 'Redis', 'platform', 'DataBoard'),
    ('kafka', 'Kafka', 'platform', 'DataLine'),
    ('rocketmq', 'RocketMQ', 'platform', 'Promotion'),
]


def seed_resource_types(apps, schema_editor):
    ResourceType = apps.get_model('resource_center', 'ResourceType')
    for code, name, category, icon in RESOURCE_TYPES:
        ResourceType.objects.update_or_create(
            code=code,
            defaults={'name': name, 'category': category, 'icon': icon, 'is_builtin': True, 'is_enabled': True},
        )


class Migration(migrations.Migration):
    dependencies = [('resource_center', '0001_initial')]
    operations = [migrations.RunPython(seed_resource_types, migrations.RunPython.noop)]
