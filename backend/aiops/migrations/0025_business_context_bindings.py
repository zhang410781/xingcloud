from django.db import migrations, models
import django.db.models.deletion
from django.utils.text import slugify


def backfill_business_context(apps, schema_editor):
    Environment = apps.get_model('aiops', 'AIOpsKnowledgeEnvironment')
    K8sCluster = apps.get_model('ops', 'K8sCluster')
    TaskResourceGroup = apps.get_model('ops', 'TaskResourceGroup')

    used_codes = set()
    used_metrics = set()
    used_logs = set()
    used_clusters = set()
    used_asset_envs = set()

    for environment in Environment.objects.order_by('-is_default', 'id').iterator():
        metric_environment = ''
        if environment.metric_datasource_id:
            metric_environment = str(environment.metric_datasource.environment or '').strip().lower()
        base = metric_environment or slugify(environment.name or '', allow_unicode=False) or f'context-{environment.id}'
        code = base
        suffix = 2
        while code in used_codes:
            code = f'{base}-{suffix}'
            suffix += 1
        used_codes.add(code)
        environment.code = code
        environment.business_line = environment.name or code

        if environment.metric_datasource_id in used_metrics:
            environment.metric_datasource_id = None
            environment.metric_datasource_ids = []
        elif environment.metric_datasource_id:
            used_metrics.add(environment.metric_datasource_id)

        if environment.log_datasource_id in used_logs:
            environment.log_datasource_id = None
            environment.log_datasource_ids = []
        elif environment.log_datasource_id:
            used_logs.add(environment.log_datasource_id)

        cluster_ids = environment.k8s_cluster_ids if isinstance(environment.k8s_cluster_ids, list) else []
        valid_clusters = []
        for raw_id in cluster_ids:
            try:
                item_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            if item_id not in used_clusters and K8sCluster.objects.filter(pk=item_id).exists():
                valid_clusters.append(item_id)
        if len(valid_clusters) == 1:
            environment.k8s_cluster_id = valid_clusters[0]
            used_clusters.add(valid_clusters[0])

        asset_ids = environment.task_resource_environment_ids if isinstance(environment.task_resource_environment_ids, list) else []
        valid_assets = []
        for raw_id in asset_ids:
            try:
                item_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            if item_id in used_asset_envs:
                continue
            if TaskResourceGroup.objects.filter(pk=item_id, group_type='environment').exists():
                valid_assets.append(item_id)
        if len(valid_assets) == 1:
            environment.task_resource_environment_id = valid_assets[0]
            used_asset_envs.add(valid_assets[0])

        environment.save(update_fields=[
            'code', 'business_line', 'metric_datasource', 'metric_datasource_ids',
            'log_datasource', 'log_datasource_ids', 'k8s_cluster', 'task_resource_environment',
        ])


class Migration(migrations.Migration):

    dependencies = [
        ('ops', '0081_remove_deployment_uniq_ops_curr_biz_app_docker_host_and_more'),
        ('aiops', '0024_knowledge_environment_single_datasources'),
    ]

    operations = [
        migrations.AddField(
            model_name='aiopsknowledgeenvironment',
            name='business_line',
            field=models.CharField(blank=True, default='', max_length=128, verbose_name='业务线'),
        ),
        migrations.AddField(
            model_name='aiopsknowledgeenvironment',
            name='code',
            field=models.SlugField(blank=True, max_length=128, null=True, unique=True, verbose_name='业务上下文编码'),
        ),
        migrations.AddField(
            model_name='aiopsknowledgeenvironment',
            name='environment_type',
            field=models.CharField(choices=[('prod', '生产'), ('test', '测试'), ('dev', '开发')], default='prod', max_length=16, verbose_name='环境类型'),
        ),
        migrations.AddField(
            model_name='aiopsknowledgeenvironment',
            name='owner',
            field=models.CharField(blank=True, default='', max_length=64, verbose_name='负责人'),
        ),
        migrations.AddField(
            model_name='aiopsknowledgeenvironment',
            name='k8s_cluster',
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='aiops_knowledge_environment', to='ops.k8scluster', verbose_name='K8s 集群'),
        ),
        migrations.AddField(
            model_name='aiopsknowledgeenvironment',
            name='task_resource_environment',
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='aiops_knowledge_environment', to='ops.taskresourcegroup', verbose_name='资产环境分组'),
        ),
        migrations.RunPython(backfill_business_context, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='aiopsknowledgeenvironment',
            name='code',
            field=models.SlugField(max_length=128, unique=True, verbose_name='业务上下文编码'),
        ),
        migrations.AlterField(
            model_name='aiopsknowledgeenvironment',
            name='metric_datasource',
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='aiops_knowledge_environments', to='ops.metricdatasource', verbose_name='指标数据源'),
        ),
        migrations.AlterField(
            model_name='aiopsknowledgeenvironment',
            name='log_datasource',
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='aiops_knowledge_environments', to='ops.logdatasource', verbose_name='日志数据源'),
        ),
    ]
