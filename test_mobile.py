import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib import error, request

import app
import mobile_api


class MobileApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=app.ROOT, prefix='.test-')
        self.old_data, app.DATA = app.DATA, Path(self.directory.name)
        self.environment = patch.dict(os.environ, {'KITCHEN_APP_TOKEN': 'test-app-' + 'x' * 32}, clear=True)
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
            headers['Authorization'] = 'Bearer ' + os.environ['KITCHEN_APP_TOKEN']
        req = request.Request(self.url + '/app/' + path, json.dumps(data).encode() if data is not None else None, headers)
        with request.urlopen(req) as response:
            return json.load(response)

    def test_token_guarded_cooking_flow(self):
        with self.assertRaises(error.HTTPError) as caught:
            self.call('state', auth=False)
        self.assertEqual(caught.exception.code, 401)
        state = self.call('state')
        self.assertIn('鸡蛋', state['ingredients'])
        state = self.call('toggle', {'name': '鸡蛋'})
        self.assertIn('鸡蛋', state['state']['selected'])
        state = self.call('preferences', {'people': 3, 'minutes': 15})
        self.assertEqual((state['state']['people'], state['state']['minutes']), (3, 15))
        state = self.call('start', {'recipe': 'tomato-eggs'})
        self.assertEqual(state['recipe']['id'], 'tomato-eggs')
        state = self.call('step', {'delta': 1})
        self.assertEqual(state['state']['step'], 1)

    def test_generated_recipe_uses_selected_ingredient_and_valid_schema(self):
        state = app.load_state()
        state.update(selected=['鸡腿', '土豆'], people=2, minutes=40)
        response = {'choices': [{'message': {'content': json.dumps({
            'name': '鸡腿土豆焖锅', 'minutes': 35, 'servings': 2, 'ingredients': ['鸡腿', '土豆'],
            'amounts': ['鸡腿 2 个', '土豆 2 个'], 'steps': ['鸡肉彻底加热至熟透，中心温度达到 74°C。'],
        }, ensure_ascii=False)}}]}
        with patch.object(app, 'api', return_value=response):
            recipe = mobile_api._generated_recipe(app, state)
        self.assertEqual(recipe['source'], 'ai_with_recipe_retrieval')
        self.assertIn('鸡腿', recipe['ingredients'])


if __name__ == '__main__':
    unittest.main()
