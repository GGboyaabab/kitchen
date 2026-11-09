import base64
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib import error, parse, request

from PIL import Image
import app


class KitchenTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=app.ROOT, prefix='.test-')
        self.old_data = app.DATA
        app.DATA = Path(self.directory.name)

    def tearDown(self):
        app.DATA = self.old_data
        self.directory.cleanup()

    def test_alias_validation_and_no_partial_import(self):
        self.assertEqual(app.name_of(' 西红柿 '), '番茄')
        with self.assertRaises(ValueError):
            app.name_of('../data')

    def test_state_survives_reload(self):
        state = app.load_state()
        state.update(selected=['鸡腿', '土豆'], recipe='potato-chicken', step=3)
        app.save_state(state)
        self.assertEqual(app.load_state(), state)

    def test_separate_domestic_keys_and_routes(self):
        env = {'VISION_API_KEY': 'vision-test', 'CHAT_API_KEY': 'chat-test', 'IMAGE_API_KEY': 'image-test'}
        expected = [('VISION', 'dashscope.aliyuncs.com', 'vision-test'),
                    ('CHAT', 'api.deepseek.com', 'chat-test'),
                    ('IMAGE', 'operator.las.cn-beijing.volces.com', 'image-test')]
        with patch.dict(app.os.environ, env, clear=True):
            for role, host, key in expected:
                with patch.object(app.request, 'urlopen') as mocked:
                    mocked.return_value.__enter__.return_value = io.BytesIO(b'{}')
                    app.api(role, 'test', {'model': 'test'})
                    req = mocked.call_args.args[0]
                    self.assertEqual(parse.urlsplit(req.full_url).hostname, host)
                    self.assertEqual(req.get_header('Authorization'), 'Bearer ' + key)
                    self.assertEqual(json.loads(req.data), {'model': 'test'})

    def test_recommendation_uses_actual_selected_ingredients(self):
        state = app.load_state()
        state['selected'] = ['番茄', '鸡蛋']
        self.assertEqual(app.recommend(state)[0]['id'], 'tomato-eggs')

    def test_generated_png_is_monochrome_and_reused(self):
        buffer = io.BytesIO()
        Image.new('RGB', (32, 32), 'white').save(buffer, 'PNG')
        response = {'data': [{'b64_json': base64.b64encode(buffer.getvalue()).decode()}]}
        with patch.object(app, 'api', return_value=response) as mocked:
            self.assertTrue(app.generate_icon('鸡腿'))
            self.assertFalse(app.generate_icon('鸡腿'))
            self.assertEqual(mocked.call_count, 1)
        with app.db() as conn:
            blob = conn.execute('SELECT png FROM icons WHERE key=?', (app.icon_key('鸡腿'),)).fetchone()[0]
        image = Image.open(io.BytesIO(blob))
        self.assertEqual(image.mode, '1')
        self.assertEqual(image.size, (320, 320))

    def test_recognition_normalizes_and_requires_confirmation(self):
        response = {'choices': [{'message': {'content': '{"ingredients":["洋芋","土豆","鸡蛋"]}'}}]}
        with patch.object(app, 'api', return_value=response):
            self.assertEqual(app.recognize(b'', '这些食材'), ['土豆', '鸡蛋'])
        self.assertEqual(app.load_state()['selected'], [])

    def test_http_toggle_restore_escape_and_cross_origin(self):
        server = app.HTTPServer(('127.0.0.1', 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = 'http://127.0.0.1:%s' % server.server_port
        try:
            with request.urlopen(url) as response:
                self.assertIn('选手边的食材', response.read().decode())
            payload = parse.urlencode({'name': '鸡蛋'}).encode()
            with request.urlopen(url + '/toggle', payload) as response:
                self.assertEqual(response.status, 200)
            self.assertEqual(app.load_state()['selected'], ['鸡蛋'])
            forged = request.Request(url + '/toggle', payload, {'Origin': 'https://example.com'})
            with self.assertRaises(error.HTTPError) as caught:
                request.urlopen(forged)
            self.assertEqual(caught.exception.code, 403)
            self.assertEqual(app.load_state()['selected'], ['鸡蛋'])
            self.assertNotIn('<script>', app.page(message='<script>').decode())
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
