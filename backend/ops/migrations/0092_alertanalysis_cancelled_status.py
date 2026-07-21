from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ops', '0091_alert_notification_storm_threshold'),
    ]

    operations = [
        migrations.AlterField(
            model_name='alertanalysis',
            name='status',
            field=models.CharField(
                choices=[
                    ('pending', '待研判'),
                    ('running', '研判中'),
                    ('completed', '已完成'),
                    ('partial', '部分完成'),
                    ('failed', '失败'),
                    ('cancelled', '已取消'),
                ],
                db_index=True,
                default='pending',
                max_length=16,
                verbose_name='状态',
            ),
        ),
    ]
