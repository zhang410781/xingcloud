from django.db import migrations


def clear_test_templates(apps, schema_editor):
    channel_model = apps.get_model('ops', 'AlertNotificationChannel')
    for channel in channel_model.objects.all():
        update_fields = []
        if (channel.template_title or '').strip().lower() == 'test':
            channel.template_title = ''
            update_fields.append('template_title')
        if (channel.template_body or '').strip().lower() == 'test':
            channel.template_body = ''
            update_fields.append('template_body')
        if update_fields:
            channel.save(update_fields=update_fields)


class Migration(migrations.Migration):

    dependencies = [
        ('ops', '0071_normalize_task_metadata'),
    ]

    operations = [
        migrations.RunPython(clear_test_templates, migrations.RunPython.noop),
    ]
