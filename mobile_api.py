"""Small, token-protected API used by the family-facing mini program."""
import json
import os
import re
import secrets
from urllib.parse import parse_qs, urlsplit
import io

from PIL import Image

import admin_api


def _authorized(h):
    token = os.getenv('KITCHEN_APP_TOKEN', '')
    auth = h.headers.get('Authorization', '')
    return len(token) >= 24 and secrets.compare_digest(auth.encode(), ('Bearer ' + token).encode())


def _snapshot(k):
    state = k.load_state()
    with k.db() as conn:
        ingredients = [row[0] for row in conn.execute('SELECT name FROM ingredients ORDER BY rowid')]
    recipe = next((item for item in k.recipes() if item['id'] == state['recipe']), None)
    return {
        'ingredients': ingredients,
        'state': state,
        'recommendations': k.recommend(state),
        'recipe': recipe,
    }


def _templates(k, state):
    selected = set(state['selected'])
    def score(recipe):
        matches = len(selected & set(recipe['ingredients']))
        overtime = max(0, recipe['minutes'] - state['minutes'])
        return (-matches, overtime, recipe['minutes'], recipe['name'])
    return sorted(k.recipes(), key=score)[:3]


def _generated_recipe(k, state):
    if not state['selected']:
        raise ValueError('请先至少选择一种食材。')
    context = _templates(k, state)
    result = k.api('CHAT', 'chat/completions', {
        'model': k.model_config('CHAT')['model'],
        'messages': [
            {'role': 'system', 'content': (k.ROOT / 'prompts/generate_recipe.txt').read_text(encoding='utf-8')},
            {'role': 'user', 'content': json.dumps({
                'available_ingredients': state['selected'], 'servings': state['people'], 'max_minutes': state['minutes'],
                'reference_recipes': context,
            }, ensure_ascii=False)},
        ], 'thinking': {'type': 'disabled'}, 'response_format': {'type': 'json_object'}, 'stream': False,
    })
    text = k.response_text(result).strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text, flags=re.I)
    try:
        recipe = admin_api.valid_recipe(k, json.loads(text))
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        raise ValueError('模型没有返回可用菜谱，请重试。') from exc
    if not set(recipe['ingredients']) & set(state['selected']):
        raise ValueError('生成菜谱没有使用已选食材，请重试。')
    recipe['source'] = 'ai_with_recipe_retrieval'
    recipe['references'] = [item['id'] for item in context]
    return recipe


def _data(h):
    length = int(h.headers.get('Content-Length', '0'))
    if not 0 < length <= 128 * 1024:
        raise ValueError('请求大小不正确。')
    value = json.loads(h.rfile.read(length))
    if not isinstance(value, dict):
        raise ValueError('需要 JSON 对象。')
    return value


def dispatch(h, k, path, data):
    if h.command == 'GET':
        if path == '/app/state':
            return _snapshot(k)
        if path == '/app/job':
            job_id = parse_qs(urlsplit(h.path).query).get('id', [''])[0]
            with admin_api.LOCK:
                return dict(admin_api.JOBS.get(job_id, {'status': 'failed', 'error': '任务不存在或服务已重启，请重新提问。'}))
        raise ValueError('未知接口。')

    state = k.load_state()
    if path == '/app/toggle':
        name = k.name_of(data.get('name', ''))
        with k.db() as conn:
            if not conn.execute('SELECT 1 FROM ingredients WHERE name=?', (name,)).fetchone():
                raise ValueError('食材不存在。')
        if name in state['selected']:
            state['selected'].remove(name)
        else:
            state['selected'].append(name)
        state.update(recipe=None, step=0)
        k.save_state(state)
        return _snapshot(k)
    if path == '/app/preferences':
        people, minutes = data.get('people'), data.get('minutes')
        if type(people) is not int or type(minutes) is not int or not 1 <= people <= 12 or not 5 <= minutes <= 240:
            raise ValueError('人数应为 1～12，时间为 5～240 分钟。')
        state.update(people=people, minutes=minutes)
        k.save_state(state)
        return _snapshot(k)
    if path == '/app/start':
        recipe_id = data.get('recipe')
        if recipe_id not in [item['id'] for item in k.recipes()]:
            raise ValueError('找不到这道菜。')
        state.update(recipe=recipe_id, step=0)
        k.save_state(state)
        return _snapshot(k)
    if path == '/app/step':
        recipe = next((item for item in k.recipes() if item['id'] == state['recipe']), None)
        delta = data.get('delta')
        if not recipe or delta not in (-1, 1):
            raise ValueError('当前没有可推进的菜谱。')
        state['step'] = max(0, min(len(recipe['steps']), state['step'] + delta))
        k.save_state(state)
        return _snapshot(k)
    if path == '/app/ask':
        recipe = next((item for item in k.recipes() if item['id'] == state['recipe']), None)
        question = data.get('question', '').strip() if isinstance(data.get('question', ''), str) else ''
        if not recipe or not 1 <= len(question) <= 500:
            raise ValueError('请先开始一道菜，并输入 1～500 字的问题。')
        def work():
            result = k.api('CHAT', 'chat/completions', {
                'model': k.model_config('CHAT')['model'],
                'messages': [
                    {'role': 'system', 'content': (k.ROOT / 'prompts/assistant.txt').read_text(encoding='utf-8')},
                    {'role': 'user', 'content': json.dumps({'recipe': recipe, 'step': state['step'] + 1, 'people': state['people'], 'question': question}, ensure_ascii=False)},
                ], 'thinking': {'type': 'disabled'}, 'stream': False,
            })
            return {'answer': k.response_text(result)}
        return admin_api.submit(work)
    if path == '/app/generate-recipe':
        return admin_api.submit(lambda: {'recipe': _generated_recipe(k, state)})
    if path == '/app/save-generated':
        recipe_data = data.get('recipe')
        recipe = admin_api.valid_recipe(k, recipe_data)
        with k.db() as conn:
            conn.execute('INSERT OR REPLACE INTO recipes VALUES (?,?)', (recipe['id'], json.dumps(recipe, ensure_ascii=False)))
            conn.executemany('INSERT OR IGNORE INTO ingredients VALUES (?)', [(name,) for name in recipe['ingredients']])
        return _snapshot(k)
    raise ValueError('未知接口。')


def handle(h, k):
    if not _authorized(h):
        h.send(b'{"error":"Unauthorized"}', 'application/json', 401)
        return
    path = urlsplit(h.path).path
    try:
        if path == '/app/icon' and h.command == 'GET':
            name = k.name_of(parse_qs(urlsplit(h.path).query).get('name', [''])[0])
            png = k.saved_icon(name)
            if png:
                h.send(png, 'image/png')
            else:
                # A stable plain placeholder until the owner chooses to generate an icon.
                image = Image.new('1', (320, 320), 1)
                buffer = io.BytesIO()
                image.save(buffer, 'PNG')
                h.send(buffer.getvalue(), 'image/png')
            return
        data = _data(h) if h.command == 'POST' else {}
        with k.STATE_LOCK:
            result = dispatch(h, k, path, data)
        h.send(json.dumps(result, ensure_ascii=False).encode(), 'application/json; charset=utf-8')
    except (ValueError, KeyError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
        h.send(json.dumps({'error': str(exc) if isinstance(exc, ValueError) else '请求格式无效。'}, ensure_ascii=False).encode(), 'application/json; charset=utf-8', 400)
    except Exception:
        h.send(json.dumps({'error': '服务端操作失败，请检查配置。'}, ensure_ascii=False).encode(), 'application/json; charset=utf-8', 500)
