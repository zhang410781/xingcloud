from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase


class FrontendRouteTests(SimpleTestCase):
    def setUp(self):
        self._temp_dir = TemporaryDirectory()
        self.dist_dir = Path(self._temp_dir.name)
        (self.dist_dir / 'index.html').write_text('<html>spa index</html>', encoding='utf-8')
        (self.dist_dir / 'assets').mkdir()
        (self.dist_dir / 'assets' / 'app.js').write_text('window.app = true', encoding='utf-8')
        self._dist_patch = patch('xing_cloud.frontend_views.FRONTEND_DIST_DIR', self.dist_dir)
        self._dist_patch.start()

    def tearDown(self):
        self._dist_patch.stop()
        self._temp_dir.cleanup()

    def test_asset_management_routes_use_spa_index(self):
        for path in ('/assets/registration', '/assets/middleware'):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(b''.join(response.streaming_content), b'<html>spa index</html>')
                self.assertEqual(response['Cache-Control'], 'no-cache, no-store, must-revalidate')

    def test_compiled_frontend_asset_is_still_served_as_static_file(self):
        response = self.client.get('/assets/app.js')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b''.join(response.streaming_content), b'window.app = true')
        self.assertEqual(response['Cache-Control'], 'public, max-age=31536000, immutable')
