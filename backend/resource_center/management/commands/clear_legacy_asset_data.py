from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from cmdb.models import CIRelation, ConfigItem
from ops.models import MiddlewareAsset


class Command(BaseCommand):
    help = '清理已被资源中心替代的旧配置项和中间件资产；默认只预览。'

    def add_arguments(self, parser):
        parser.add_argument(
            '--confirm',
            action='store_true',
            help='确认执行删除；不提供该参数时只输出待删除数量。',
        )

    def handle(self, *args, **options):
        counts = {
            'cmdb_relations': CIRelation.objects.count(),
            'cmdb_config_items': ConfigItem.objects.count(),
            'middleware_assets': MiddlewareAsset.objects.count(),
        }
        self.stdout.write('遗留资产数据预览：')
        for name, count in counts.items():
            self.stdout.write(f'  {name}: {count}')

        if not options['confirm']:
            self.stdout.write(self.style.WARNING('未执行删除；确认备份和回滚方案后使用 --confirm。'))
            return

        if not any(counts.values()):
            self.stdout.write(self.style.SUCCESS('没有需要清理的遗留资产数据。'))
            return

        try:
            with transaction.atomic():
                CIRelation.objects.all().delete()
                ConfigItem.objects.all().delete()
                MiddlewareAsset.objects.all().delete()
        except Exception as exc:
            raise CommandError(f'遗留资产数据清理失败，事务已回滚：{exc}') from exc
        self.stdout.write(self.style.SUCCESS('遗留资产数据已清理。任务执行目标、主机凭据和资源中心数据未删除。'))
