"""Authenticated JSON API shared by the native WeChat management client."""
import base64
from concurrent.futures import ThreadPoolExecutor
import json
import os
import re
import secrets
import threading
from urllib.parse import parse_qs, urlsplit
import uuid

from cryptography.fernet import Fernet
from PIL import Image
import io

POOL = ThreadPoolExecutor(max_workers=1)
JOBS = {}
LOCK = threading.Lock()


def submit(work):
    with LOCK:
        if sum(j['status'] in ('queued', 'running') for j in JOBS.values()) >= 10:
            raise ValueError('待处理任务较多，请稍后再试。')
        if len(JOBS) >= 100:
            for key in list(JOBS):
                if JOBS[key]['status'] in ('done', 'failed'):
                    del JOBS[key]
                    break
        job_id = uuid.uuid4().hex
        JOBS[job_id] = {'id': job_id, 'status': 'queued'}

    def run():
        with LOCK:
            JOBS[job_id]['status'] = 'running'
        try:
            result = work()
            value = {'id': job_id, 'status': 'done', 'result': result}
        except Exception as exc:
            value = {'id': job_id, 'status': 'failed', 'error': str(exc) if isinstance(exc, ValueError) else '任务失败，请检查服务端配置。'}
        with LOCK:
            JOBS[job_id] = value
    POOL.submit(run)
    return {'job': job_id}


def valid_recipe(k, value):
    if not isinstance(value, dict):
        raise ValueError('菜谱格式不正确。')
    result = {'id': value.get('id') or uuid.uuid4().hex}
    if not isinstance(result['id'], str) or not re.fullmatch(r'[a-zA-Z0-9-]{1,64}', result['id']):
        raise ValueError('菜谱 ID 无效。')
    result['name'] = k.name_of(value.get('name', ''))
    for key, maximum, width in [('ingredients', 40, 24), ('amounts', 60, 200), ('steps', 60, 1000)]:
        items = value.get(key)
        if not isinstance(items, list) or not 1 <= len(items) <= maximum or any(not isinstance(x, str) or not 1 <= len(x.strip()) <= width for x in items):
            raise ValueError('菜谱 %s 不能为空，且每项长度须符合限制。' % key)
        result[key] = [k.name_of(x) if key == 'ingredients' else x.strip() for x in items]
    for key, maximum in [('minutes', 1440), ('servings', 12)]:
        number = value.get(key)
        if type(number) is not int or not 1 <= number <= maximum:
            raise ValueError('时间或人数超出范围。')
        result[key] = number
    return result


def config_view(k):
    values = []
    for role in k.MODEL_DEFAULTS:
        c = k.model_config(role)
        values.append({'role': role, 'base': c['base'], 'model': c['model'],
                       'configured': bool(c['key']), 'mask': '••••••（已配置）' if c['key'] else '未配置'})
    return values


def save_config(k, data):
    role = data.get('role')
    if role not in k.MODEL_DEFAULTS:
        raise ValueError('未知模型用途。')
    base, model = data.get('base', '').strip().rstrip('/'), data.get('model', '').strip()
    url = urlsplit(base)
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('请填写不含用户名、密码或查询参数的 HTTPS 接口基址。')
    if not re.fullmatch(r'[\w./:-]{1,160}', model):
        raise ValueError('模型名称无效。')
    token = data.get('token', '')
    if not isinstance(token, str) or len(token) > 2048 or any(ord(x) < 33 or ord(x) > 126 for x in token):
        raise ValueError('Token 格式无效。')
    if data.get('clear_token'):
        token = ''
    elif not token:
        token = k.model_config(role)['key']
    try:
        cipher = Fernet(os.environ['KITCHEN_SECRET_KEY'].encode())
    except (KeyError, ValueError) as exc:
        raise ValueError('服务端需要配置 KITCHEN_SECRET_KEY，才能保存模型配置。') from exc
    encrypted = cipher.encrypt(token.encode()).decode() if token else ''
    with k.db() as conn:
        conn.execute('INSERT OR REPLACE INTO model_configs VALUES (?,?,?,?)', (role, base, model, encrypted))
    return {'saved': True}


def dispatch(h, k, path, data):
    if h.command == 'GET':
        if path == '/admin/ingredients':
            with k.db() as conn:
                names = [row[0] for row in conn.execute('SELECT name FROM ingredients ORDER BY rowid')]
            return {'ingredients': [{'name': name, 'generated': bool(k.saved_icon(name))} for name in names]}
        if path == '/admin/recipes':
            return {'recipes': k.recipes()}
        if path == '/admin/models':
            return {'models': config_view(k)}
        if path == '/admin/job':
            job_id = parse_qs(urlsplit(h.path).query).get('id', [''])[0]
            with LOCK:
                return dict(JOBS.get(job_id, {'status': 'failed', 'error': '任务不存在或服务已重启，请重新操作。'}))
        raise ValueError('未知接口。')
    if path == '/admin/ingredients/save':
        names = data.get('names')
        if not isinstance(names, list) or not 1 <= len(names) <= 20:
            raise ValueError('每次添加 1～20 种食材。')
        names = list(dict.fromkeys(k.name_of(x) for x in names))
        with k.db() as conn:
            conn.executemany('INSERT OR IGNORE INTO ingredients VALUES (?)', [(x,) for x in names])
        return {'saved': True}
    if path in ('/admin/ingredients/delete', '/admin/ingredients/rename'):
        name = k.name_of(data.get('name', ''))
        new_name = k.name_of(data.get('new_name', '')) if path.endswith('rename') else None
        with k.db() as conn:
            if not conn.execute('SELECT 1 FROM ingredients WHERE name=?', (name,)).fetchone():
                raise ValueError('食材不存在。')
            records = [(row[0], json.loads(row[1])) for row in conn.execute('SELECT id,value FROM recipes')]
            if not new_name and any(name in r['ingredients'] for _, r in records):
                raise ValueError('菜谱仍在引用这个食材，请先修改相关菜谱。')
            if new_name:
                if conn.execute('SELECT 1 FROM ingredients WHERE name=?', (new_name,)).fetchone():
                    raise ValueError('该名称已存在。')
                conn.execute('UPDATE ingredients SET name=? WHERE name=?', (new_name, name))
                conn.execute('UPDATE ingredient_icons SET name=? WHERE name=?', (new_name, name))
                for recipe_id, recipe in records:
                    recipe['ingredients'] = [new_name if x == name else x for x in recipe['ingredients']]
                    conn.execute('UPDATE recipes SET value=? WHERE id=?', (json.dumps(recipe, ensure_ascii=False), recipe_id))
            else:
                conn.execute('DELETE FROM ingredients WHERE name=?', (name,))
                conn.execute('DELETE FROM ingredient_icons WHERE name=?', (name,))
            row = conn.execute('SELECT value FROM state WHERE id=1').fetchone()
            if row:
                state = json.loads(row[0])
                state['selected'] = [new_name if x == name else x for x in state['selected'] if new_name or x != name]
                conn.execute('UPDATE state SET value=? WHERE id=1', (json.dumps(state, ensure_ascii=False),))
        return {'saved': True}
    if path == '/admin/recipes/save':
        recipe = valid_recipe(k, data)
        with k.db() as conn:
            active = conn.execute('SELECT value FROM state WHERE id=1').fetchone()
            if active and json.loads(active[0]).get('recipe') == recipe['id']:
                raise ValueError('这道菜正在跟做，请先在做饭首页切换另一道菜，再编辑。')
            conn.execute('INSERT OR REPLACE INTO recipes VALUES (?,?)', (recipe['id'], json.dumps(recipe, ensure_ascii=False)))
            conn.executemany('INSERT OR IGNORE INTO ingredients VALUES (?)', [(x,) for x in recipe['ingredients']])
        return {'saved': True, 'id': recipe['id']}
    if path == '/admin/recipes/delete':
        with k.db() as conn:
            row = conn.execute('SELECT value FROM state WHERE id=1').fetchone()
            if row and json.loads(row[0]).get('recipe') == data.get('id'):
                raise ValueError('这道菜正在跟做，不能删除。')
            conn.execute('DELETE FROM recipes WHERE id=?', (data.get('id'),))
        return {'saved': True}
    if path == '/admin/models/save':
        return save_config(k, data)
    if path == '/admin/models/test':
        role = data.get('role')
        if role not in k.MODEL_DEFAULTS or not k.model_config(role)['key']:
            raise ValueError('请先配置并保存 Token。')
        if role == 'IMAGE':
            return {'message': '已配置 Token；生图接口没有统一的免费连通测试，请生成一张图片验证权限（可能收费）。'}
        return submit(lambda: {'message': k.response_text(k.api(role, 'chat/completions', {
            'model': k.model_config(role)['model'], 'messages': [{'role': 'user', 'content': '只回复 OK'}],
            'stream': False}))})
    if path == '/admin/recognize':
        note, photo = data.get('note', ''), data.get('photo', b'')
        if not isinstance(note, str) or len(note) > 500 or not isinstance(photo, bytes) or len(photo) > 8 * 1024 * 1024 or not (note.strip() or photo):
            raise ValueError('请选择 8 MB 以内的照片或填写 500 字以内的说明。')
        return submit(lambda: {'names': k.recognize(photo, note)})
    if path == '/admin/generate':
        name = k.name_of(data.get('name', ''))
        with k.db() as conn:
            if not conn.execute('SELECT 1 FROM ingredients WHERE name=?', (name,)).fetchone():
                raise ValueError('请先添加并确认食材。')
        force = data.get('force') is True
        return submit(lambda: {'message': '图片已保存' if k.generate_icon(name, force) else '已复用已有图片，没有再次生图'})
    raise ValueError('未知接口。')


def handle(h, k):
    token = os.getenv('KITCHEN_ADMIN_TOKEN', '')
    auth = h.headers.get('Authorization', '')
    if len(token) < 24 or not secrets.compare_digest(auth.encode(), ('Bearer ' + token).encode()):
        h.send(b'{"error":"Unauthorized"}', 'application/json', 401)
        return
    path = urlsplit(h.path).path
    try:
        if path == '/admin/icon' and h.command == 'GET':
            name = k.name_of(parse_qs(urlsplit(h.path).query).get('name', [''])[0])
            png = k.saved_icon(name)
            if not png:
                image = Image.new('1', (320, 320), 1)
                buffer = io.BytesIO()
                image.save(buffer, 'PNG')
                png = buffer.getvalue()
            h.send(png, 'image/png')
            return
        data = {}
        if h.command == 'POST':
            if h.headers.get('Content-Type', '').startswith('multipart/form-data'):
                data = h.fields()
            else:
                length = int(h.headers.get('Content-Length', '0'))
                if not 0 < length <= 128 * 1024:
                    raise ValueError('请求大小不正确。')
                data = json.loads(h.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError('需要 JSON 对象。')
        with k.STATE_LOCK:
            result = dispatch(h, k, path, data)
        h.send(json.dumps(result, ensure_ascii=False).encode(), 'application/json; charset=utf-8')
    except (ValueError, KeyError, TypeError, UnicodeError):
        # Never return request bodies or provider tokens in an error response.
        import sys
        exc = sys.exc_info()[1]
        message = str(exc) if type(exc) is ValueError else '请求格式无效。'
        if isinstance(exc, json.JSONDecodeError):
            message = 'JSON 格式不正确。'
        h.send(json.dumps({'error': message}, ensure_ascii=False).encode(), 'application/json; charset=utf-8', 400)
    except Exception:
        h.send('{"error":"服务端操作失败，请检查配置。"}'.encode(), 'application/json; charset=utf-8', 500)
