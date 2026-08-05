from django.core.management.base import BaseCommand
from django.db import connection

LEGACY_TABLES = [
    'cmdb_configitem',
    'cmdb_cirelation',
]


class Command(BaseCommand):
    help = '预览/清理已下线 CMDB 遗留表数据（迁移前门禁使用）；默认只预览。'

    def add_arguments(self, parser):
        parser.add_argument(
            '--confirm',
            action='store_true',
            help='确认执行删除；不提供该参数时只输出待删除数量。',
        )

    def handle(self, *args, **options):
        counts = {}
        with connection.cursor() as cursor:
            for table in LEGACY_TABLES:
                if connection.vendor == 'mysql':
                    cursor.execute(
                        'SELECT COUNT(*) FROM information_schema.tables '
                        'WHERE table_schema = DATABASE() AND table_name = %s',
                        [table],
                    )
                else:
                    cursor.execute(
                        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = %s",
                        [table],
                    )
                exists = cursor.fetchone()[0]
                if not exists:
                    continue
                cursor.execute(f'SELECT COUNT(*) FROM `{table}`')
                counts[table] = cursor.fetchone()[0]

        self.stdout.write('遗留 CMDB 数据预览：')
        for table, count in counts.items():
            self.stdout.write(f'  {table}: {count}')
        if not counts:
            self.stdout.write(self.style.SUCCESS('没有遗留 CMDB 表，无需清理。'))

        if not options['confirm']:
            self.stdout.write(self.style.WARNING('未执行删除；确认备份和回滚方案后使用 --confirm。'))
            return

        if not counts:
            return

        with connection.cursor() as cursor:
            for table in counts:
                cursor.execute(f'DELETE FROM `{table}`')
        self.stdout.write(self.style.SUCCESS('遗留 CMDB 数据已清理。'))
