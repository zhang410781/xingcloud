from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ops", "0075_alert_root_cause_alert_suggestion"),
    ]

    operations = [
        migrations.AddField("alertrule", "source", models.CharField(blank=True, default="custom", max_length=64, verbose_name="模板来源")),
        migrations.AddField("alertrule", "notify_config", models.JSONField(blank=True, default=dict, verbose_name="通知配置")),
        migrations.AddField("alertrule", "group_window", models.PositiveIntegerField(default=5, verbose_name="聚合窗口(分钟)")),
        migrations.AddField("alertrule", "repeat_interval", models.PositiveIntegerField(default=30, verbose_name="重复通知间隔(分钟)")),
        migrations.AddField("alertrule", "mute_schedule", models.JSONField(blank=True, default=dict, verbose_name="静默配置")),
        migrations.AddField("alertrule", "escalation_minutes", models.PositiveIntegerField(default=0, verbose_name="升级等待(分钟)")),
        migrations.RemoveField("alertrule", "template"),
        migrations.CreateModel(
            name="AlertSilence",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=128, verbose_name="静默名称")),
                ("matchers", models.JSONField(blank=True, default=list, verbose_name="匹配条件")),
                ("starts_at", models.DateTimeField(verbose_name="开始时间")),
                ("ends_at", models.DateTimeField(verbose_name="结束时间")),
                ("reason", models.CharField(blank=True, default="", max_length=255, verbose_name="原因")),
                ("created_by", models.CharField(blank=True, default="", max_length=64, verbose_name="创建人")),
                ("is_enabled", models.BooleanField(default=True, verbose_name="启用")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="创建时间")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="更新时间")),
            ],
            options={"verbose_name": "告警静默", "verbose_name_plural": "告警静默", "ordering": ["-created_at"]},
        ),
        migrations.RemoveField("alertnotificationlog", "rule"),
        migrations.AddField("alertnotificationlog", "rule_id", models.IntegerField(blank=True, null=True, verbose_name="规则ID")),
        migrations.RemoveField("alertnotificationlog", "channel"),
        migrations.AddField("alertnotificationlog", "channel_id", models.IntegerField(blank=True, null=True, verbose_name="渠道ID")),
        migrations.DeleteModel("AlertNotificationRule"),
        migrations.DeleteModel("AlertAggregationRule"),
        migrations.DeleteModel("AlertInhibitionRule"),
        migrations.DeleteModel("AlertMuteRule"),
        migrations.DeleteModel("AlertEscalationPolicy"),
        migrations.DeleteModel("AlertRuleTemplate"),
    ]