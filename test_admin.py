import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib import error, request

from cryptography.fernet import Fernet
import admin_api
import app


class AdminTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=app.ROOT, prefix='.test-')
        self.old_data, app.DATA = app.DATA, Path(self.directory.name)
        self.environment = patch.dict(os.environ, {'KITCHEN_ADMIN_TOKEN': 'test-admin-' + 'x' * 32,
                                                 'KITCHEN_SECRET_KEY': Fernet.generate_key().decode()}, clear=True)
        self.environment.start()
        self.server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:%s' % self.server.server_port

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.environment.stop()
        app.DATA = self.old_data
        self.directory.cleanup()

    def call(self, path, data=None, auth=True):
        headers = {'Content-Type': 'application/json'}
        if auth:
            headers['Authorization'] = 'Bearer ' + os.environ['KITCHEN_ADMIN_TOKEN']
        req = request.Request(self.url + '/admin/' + path,
                              json.dumps(data).encode() if data is not None else None, headers)
        with request.urlopen(req) as response:
            return json.load(response)

    def test_admin_auth_and_encrypted_token_never_returned(self):
        with self.assertRaises(error.HTTPError) as caught:
            self.call('models', auth=False)
        self.assertEqual(caught.exception.code, 401)
        config = {'role': 'CHAT', 'base': 'https://api.deepseek.com', 'model': 'deepseek-flash', 'token': 'my-secret-provider-key'}
        self.call('models/save', config)
        response = self.call('models')
        self.assertNotIn(config['token'], json.dumps(response))
        with app.db() as conn:
            encrypted = conn.execute("SELECT token FROM model_configs WHERE role='CHAT'").fetchone()[0]
        self.assertNotIn(config['token'], encrypted)
        self.assertEqual(app.model_config('CHAT')['key'], config['token'])
        self.call('models/save', {**config, 'token': '', 'model': 'another-model'})
        self.assertEqual(app.model_config('CHAT')['key'], config['token'])
        self.call('models/save', {**config, 'clear_token': True})
        self.assertEqual(app.model_config('CHAT')['key'], '')

    def test_recipe_crud_is_visible_to_kindle_and_validated(self):
        recipe = {'name': '测试菜', 'minutes': 10, 'servings': 2, 'ingredients': ['豆腐'], 'amounts': ['豆腐 1 块'], 'steps': ['加热至熟透。']}
        recipe_id = self.call('recipes/save', recipe)['id']
        self.assertIn('测试菜', app.page().decode())
        self.call('recipes/save', {**recipe, 'id': recipe_id, 'name': '更新菜'})
        self.assertIn('更新菜', app.page().decode())
        with self.assertRaises(error.HTTPError):
            self.call('recipes/save', {**recipe, 'steps': []})
        state = app.load_state()
        state['recipe'] = recipe_id
        app.save_state(state)
        with self.assertRaises(error.HTTPError):
            self.call('recipes/delete', {'id': recipe_id})
        state['recipe'] = None
        app.save_state(state)
        self.call('recipes/delete', {'id': recipe_id})
        self.assertNotIn(recipe_id, [r['id'] for r in app.recipes()])

    def test_ingredients_delete_stays_deleted_and_rename_updates_references(self):
        self.call('ingredients/delete', {'name': '胡萝卜'})
        self.assertNotIn('胡萝卜', [x['name'] for x in self.call('ingredients')['ingredients']])
        with self.assertRaises(error.HTTPError):
            self.call('ingredients/delete', {'name': '土豆'})
        self.call('ingredients/rename', {'name': '土豆', 'new_name': '黄土豆'})
        self.assertIn('黄土豆', next(r for r in app.recipes() if r['id'] == 'potato-chicken')['ingredients'])
        self.assertNotIn('土豆', [x['name'] for x in self.call('ingredients')['ingredients']])
        with self.assertRaises(error.HTTPError):
            self.call('ingredients/save', {'names': ['有效食材', '<script>']})
        self.assertNotIn('有效食材', [x['name'] for x in self.call('ingredients')['ingredients']])

    def test_background_recognition_requires_confirmation(self):
        with patch.object(app, 'recognize', return_value=['牛肉']):
            job_id = self.call('recognize', {'note': '这是牛肉'})['job']
            deadline = time.monotonic() + 3
            while True:
                job = self.call('job?id=' + job_id)
                if job['status'] in ('done', 'failed') or time.monotonic() > deadline:
                    break
                time.sleep(0.02)
        self.assertEqual(job['status'], 'done')
        self.assertEqual(job['result']['names'], ['牛肉'])
        self.assertNotIn('牛肉', [x['name'] for x in self.call('ingredients')['ingredients']])

    def test_old_png_survives_model_change(self):
        old_key = app.icon_key('鸡腿')
        with app.db() as conn:
            conn.execute('INSERT INTO icons VALUES (?,?)', (old_key, b'persisted-png'))
            conn.execute('INSERT INTO ingredient_icons VALUES (?,?)', ('鸡腿', old_key))
        self.call('models/save', {'role': 'IMAGE', 'base': 'https://image.example.com', 'model': 'new-model', 'token': 'test-key'})
        self.assertEqual(app.saved_icon('鸡腿'), b'persisted-png')
        with patch.object(app, 'api') as mocked:
            self.assertFalse(app.generate_icon('鸡腿'))
            mocked.assert_not_called()


if __name__ == '__main__':
    unittest.main()
