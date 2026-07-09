from django.db import migrations, models


def seed_event_environments(apps, schema_editor):
    return None


class Migration(migrations.Migration):

    dependencies = [
        ('eventwall', '0005_rename_business_line_verbose_to_system'),
    ]

    operations = [
        migrations.CreateModel(
            name='EventEnvironment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(max_length=64, unique=True, verbose_name='环境标识')),
                ('name', models.CharField(max_length=128, verbose_name='环境名称')),
                ('aliases', models.JSONField(blank=True, default=list, verbose_name='环境别名')),
                ('description', models.CharField(blank=True, default='', max_length=255, verbose_name='说明')),
                ('enabled', models.BooleanField(db_index=True, default=True, verbose_name='启用状态')),
                ('sort_order', models.PositiveIntegerField(default=100, verbose_name='排序')),
                ('last_seen_at', models.DateTimeField(blank=True, null=True, verbose_name='最近事件时间')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
            ],
            options={
                'verbose_name': '事件中心环境',
                'verbose_name_plural': '事件中心环境',
                'ordering': ['sort_order', 'code'],
            },
        ),
        migrations.AddIndex(
            model_name='eventenvironment',
            index=models.Index(fields=['enabled', 'sort_order'], name='eventwall_env_enabled_sort_idx'),
        ),
        migrations.RunPython(seed_event_environments, migrations.RunPython.noop),
    ]
