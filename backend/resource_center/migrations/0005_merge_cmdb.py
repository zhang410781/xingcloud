import json

from django.db import migrations, models


def _table_exists(connection, name):
    with connection.cursor() as cursor:
        if connection.vendor == 'mysql':
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = %s",
                [name],
            )
        else:
            cursor.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = %s",
                [name],
            )
        return cursor.fetchone()[0] > 0


def _rename_table(schema_editor, old_name, new_name):
    with schema_editor.connection.cursor() as cursor:
        if schema_editor.connection.vendor == 'mysql':
            cursor.execute(f'RENAME TABLE {old_name} TO {new_name}')
        else:
            cursor.execute(f'ALTER TABLE {old_name} RENAME TO {new_name}')


def adopt_or_create_resource_node(apps, schema_editor):
    """旧 cmdb_resourcenode 表存在则改名接管（数据原位不动）；全新库则按 state 建表。"""
    model = apps.get_model('resource_center', 'ResourceNode')

    if _table_exists(schema_editor.connection, 'cmdb_resourcenode'):
        _rename_table(schema_editor, 'cmdb_resourcenode', 'resource_center_resourcenode')
    elif not _table_exists(schema_editor.connection, 'resource_center_resourcenode'):
        schema_editor.create_model(model)


def validate_and_drop_cmdb_tables(apps, schema_editor):
    """校验 cmdb 存量数据为 0 后删除遗留五表（cost/request 随功能下线直接删除）。"""
    connection = schema_editor.connection

    for table in ('cmdb_configitem', 'cmdb_cirelation'):
        if not _table_exists(connection, table):
            continue
        with connection.cursor() as cursor:
            cursor.execute(f'SELECT COUNT(*) FROM {table}')
            if cursor.fetchone()[0]:
                raise RuntimeError(
                    f'{table} 仍有存量数据，请先执行 python manage.py clear_legacy_cmdb_data --confirm 后重试'
                )

    for table in (
        'cmdb_cirelation',
        'cmdb_costrecord',
        'cmdb_resourcerequest',
        'cmdb_configitem',
        'cmdb_citype',
    ):
        with connection.cursor() as cursor:
            cursor.execute(f'DROP TABLE IF EXISTS {table}')


class Migration(migrations.Migration):

    dependencies = [
        ('resource_center', '0004_remove_discoverysource_rc_k8s_source_has_cluster_and_more'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name='ResourceNode',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('name', models.CharField(max_length=100, verbose_name='名称')),
                        (
                            'node_type',
                            models.CharField(
                                choices=[('biz', '业务线'), ('env', '环境')], max_length=20, verbose_name='节点类型'
                            ),
                        ),
                        (
                            'parent',
                            models.ForeignKey(
                                blank=True,
                                null=True,
                                on_delete=models.deletion.CASCADE,
                                related_name='children',
                                to='resource_center.resourcenode',
                                verbose_name='父节点',
                            ),
                        ),
                        ('sort_order', models.IntegerField(default=0, verbose_name='排序')),
                    ],
                    options={'verbose_name': '资源分组节点', 'verbose_name_plural': '资源分组节点'},
                ),
            ],
        ),
        migrations.RunPython(adopt_or_create_resource_node, migrations.RunPython.noop),
        migrations.RunPython(validate_and_drop_cmdb_tables, migrations.RunPython.noop),
    ]
