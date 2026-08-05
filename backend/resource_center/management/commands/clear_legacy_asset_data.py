from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from ops.models import MiddlewareAsset


class Command(BaseCommand):
    help = '清理任务中心遗留的中间件资产（已被资源中心替代）；默认只预览。'

    def add_arguments(self, parser):
        parser.add_argument(
            '--confirm',
            action='store_true',
            help='确认执行删除；不提供该参数时只输出待删除数量。',
        )

    def handle(self, *args, **options):
        counts = {
            'middleware_assets': MiddlewareAsset.objects.count(),
        }
        self.stdout.write('遗留中间件资产预览：')
        for name, count in counts.items():
            self.stdout.write(f'  {name}: {count}')

        if not options['confirm']:
            self.stdout.write(self.style.WARNING('未执行删除；确认备份和回滚方案后使用 --confirm。'))
            return

        if not any(counts.values()):
            self.stdout.write(self.style.SUCCESS('没有需要清理的遗留中间件资产。'))
            return

        try:
            with transaction.atomic():
                MiddlewareAsset.objects.all().delete()
        except Exception as exc:
            raise CommandError(f'遗留中间件资产清理失败，事务已回滚：{exc}') from exc
        self.stdout.write(self.style.SUCCESS('遗留中间件资产已清理。任务执行目标、主机凭据和资源中心数据未删除。'))
