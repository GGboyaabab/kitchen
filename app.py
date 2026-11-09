"""Local kitchen prototype. Server-rendered forms also work without JavaScript."""
import argparse
from contextlib import contextmanager, nullcontext
import base64
import hashlib
import html
import io
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import sys
import threading
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from urllib import error, parse, request

from PIL import Image, ImageOps
from cryptography.fernet import Fernet, InvalidToken

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('KITCHEN_DATA', str(ROOT / 'data')))
RECIPES = json.loads((ROOT / 'recipes.json').read_text(encoding='utf-8'))
ALIASES = {'西红柿': '番茄', '洋芋': '土豆', '鸡子': '鸡蛋'}
SEEDS = ['鸡腿', '土豆', '鸡蛋', '番茄', '青菜', '香菇', '胡萝卜', '豆腐']
MAX_BODY = 9 * 1024 * 1024
GENERATION_LOCK = threading.Lock()
STATE_LOCK = threading.RLock()
MODEL_DEFAULTS = {
    'VISION': ('DASHSCOPE_API_KEY', 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'qwen3-vl-plus'),
    'CHAT': ('DEEPSEEK_API_KEY', 'https://api.deepseek.com', 'deepseek-flash'),
    'IMAGE': ('LAS_API_KEY', 'https://operator.las.cn-beijing.volces.com/api/v1/online', 'doubao-seedream-4-5-251128'),
}


def name_of(value):
    value = str(value).strip()
    if not re.fullmatch(r'[\w\u4e00-\u9fff ·-]{1,24}', value):
        raise ValueError('食材名称限 1～24 个中文、字母或数字，不要填写句子。')
    return ALIASES.get(value, value)


@contextmanager
def db():
    DATA.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATA / 'kitchen.sqlite3')
    try:
        with conn:
            conn.execute('CREATE TABLE IF NOT EXISTS ingredients (name TEXT PRIMARY KEY)')
            conn.execute('CREATE TABLE IF NOT EXISTS icons (key TEXT PRIMARY KEY, png BLOB NOT NULL)')
            conn.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY, value TEXT NOT NULL)')
            conn.execute('CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT)')
            conn.execute('CREATE TABLE IF NOT EXISTS recipes (id TEXT PRIMARY KEY, value TEXT NOT NULL)')
            conn.execute('CREATE TABLE IF NOT EXISTS model_configs (role TEXT PRIMARY KEY, base TEXT, model TEXT, token TEXT)')
            conn.execute('CREATE TABLE IF NOT EXISTS ingredient_icons (name TEXT PRIMARY KEY, key TEXT NOT NULL)')
            if not conn.execute("SELECT 1 FROM metadata WHERE key='seeded'").fetchone():
                conn.executemany('INSERT OR IGNORE INTO ingredients VALUES (?)', [(x,) for x in SEEDS])
                conn.executemany('INSERT OR IGNORE INTO recipes VALUES (?,?)', [(r['id'], json.dumps(r, ensure_ascii=False)) for r in RECIPES])
                conn.execute("INSERT INTO metadata VALUES ('seeded','1')")
            yield conn
    finally:
        conn.close()


def load_state():
    with db() as conn:
        row = conn.execute('SELECT value FROM state WHERE id=1').fetchone()
    return json.loads(row[0]) if row else {'selected': [], 'recipe': None, 'step': 0, 'people': 2, 'minutes': 30}


def save_state(state):
    with db() as conn:
        conn.execute('INSERT OR REPLACE INTO state VALUES (1,?)', (json.dumps(state, ensure_ascii=False),))


def recipes():
    with db() as conn:
        return [json.loads(row[0]) for row in conn.execute('SELECT value FROM recipes ORDER BY rowid')]


def model_config(role):
    key_env, base, model = MODEL_DEFAULTS[role]
    key = os.getenv(role + '_API_KEY') or os.getenv(key_env, '')
    base, model = os.getenv(role + '_BASE_URL', base), os.getenv(role + '_MODEL', model)
    with db() as conn:
        row = conn.execute('SELECT base,model,token FROM model_configs WHERE role=?', (role,)).fetchone()
    if row:
        base, model, token = row
        key = ''
        if token:
            try:
                key = Fernet(os.environ['KITCHEN_SECRET_KEY'].encode()).decrypt(token.encode()).decode()
            except (KeyError, ValueError, InvalidToken) as exc:
                raise ValueError('无法解密模型 Token，请检查服务端 KITCHEN_SECRET_KEY。') from exc
    return {'base': base.rstrip('/'), 'model': model, 'key': key}


def icon_key(name):
    # The prompt and model are part of the cache key so style changes are explicit.
    config = model_config('IMAGE')
    raw = name + (ROOT / 'prompts/icon.txt').read_text(encoding='utf-8') + config['model'] + config['base']
    return hashlib.sha256(raw.encode()).hexdigest()


def saved_icon(name):
    with db() as conn:
        row = conn.execute('SELECT icons.png FROM ingredient_icons JOIN icons ON icons.key=ingredient_icons.key WHERE name=?', (name,)).fetchone()
        if not row:
            row = conn.execute('SELECT png FROM icons WHERE key=?', (icon_key(name),)).fetchone()
    return row[0] if row else None


def api(role, path, payload):
    config = model_config(role)
    key, base = config['key'], config['base']
    if not key:
        raise ValueError('尚未配置 %s 模型 Token。手动选食材、推荐菜和跟做可直接使用。' % role)
    if parse.urlsplit(base).scheme != 'https':
        raise ValueError('模型接口必须使用 HTTPS。')
    req = request.Request(base + '/' + path,
                          json.dumps(payload).encode(),
                          {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    try:
        with request.urlopen(req, timeout=180) as response:
            return json.load(response)
    except error.HTTPError as exc:
        raise ValueError('模型 API 请求失败（HTTP %s），请检查额度、模型权限和配置。' % exc.code) from exc
    except (error.URLError, TimeoutError) as exc:
        raise ValueError('模型连接失败或超时，请稍后重试。') from exc


def response_text(result):
    try:
        text = result['choices'][0]['message']['content']
        if not isinstance(text, str):
            raise ValueError()
        return text
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValueError('模型未返回可读取的文字，请重试。') from exc


def recognize(photo, note):
    content = [{'type': 'text', 'text': note or '识别照片中的食材。'}]
    if photo:
        try:
            image = Image.open(io.BytesIO(photo))
            image = ImageOps.exif_transpose(image).convert('RGB')
            image.thumbnail((1600, 1600))
            buffer = io.BytesIO()
            image.save(buffer, 'JPEG', quality=85)
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            raise ValueError('照片无法读取，请使用 JPEG、PNG 或 WebP，最大 8 MB。') from exc
        content.append({'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + base64.b64encode(buffer.getvalue()).decode()}})
    result = api('VISION', 'chat/completions', {'model': model_config('VISION')['model'],
                 'messages': [{'role': 'system', 'content': (ROOT / 'prompts/recognize.txt').read_text(encoding='utf-8')},
                              {'role': 'user', 'content': content}],
                 'response_format': {'type': 'json_object'}, 'stream': False})
    try:
        names = json.loads(response_text(result))['ingredients']
        if not isinstance(names, list) or len(names) > 20 or any(not isinstance(x, str) for x in names):
            raise ValueError()
        return list(dict.fromkeys(name_of(x) for x in names))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('识别结果格式不正确，请重试或手动输入。') from exc


def generate_icon(name, force=False):
    with GENERATION_LOCK:
        return _generate_icon(name, force)


def _generate_icon(name, force):
    key = icon_key(name)
    with db() as conn:
        if not force and saved_icon(name):
            return False
    result = api('IMAGE', 'images/generations', {'model': model_config('IMAGE')['model'],
                 'prompt': (ROOT / 'prompts/icon.txt').read_text(encoding='utf-8').replace('{name}', name),
                 'size': '2K', 'response_format': 'b64_json', 'sequential_image_generation': 'disabled', 'stream': False})
    try:
        raw = base64.b64decode(result['data'][0]['b64_json'], validate=True)
        image = Image.open(io.BytesIO(raw)).convert('RGBA')
        background = Image.new('RGBA', image.size, 'white')
        background.alpha_composite(image)
        image = background.convert('L').resize((320, 320), Image.Resampling.LANCZOS)
        image = image.point(lambda p: 255 if p > 180 else 0).convert('1')
        buffer = io.BytesIO()
        image.save(buffer, 'PNG')
    except (KeyError, IndexError, ValueError, OSError) as exc:
        raise ValueError('生图结果无法读取，没有保存，请重试。') from exc
    with db() as conn:
        conn.execute('INSERT OR REPLACE INTO icons VALUES (?,?)', (key, buffer.getvalue()))
        conn.execute('INSERT OR REPLACE INTO ingredient_icons VALUES (?,?)', (name, key))
    return True


def recommend(state):
    selected = set(state['selected'])
    return sorted(recipes(), key=lambda r: (len(set(r['ingredients']) - selected), r['minutes'] > state['minutes'], r['minutes']))


def e(value):
    return html.escape(str(value), quote=True)


def form(action, fields='', label='确定', css=''):
    return '<form method="post" action="/%s" class="%s">%s<button>%s</button></form>' % (action, css, fields, label)


def hidden(name, value):
    return '<input type="hidden" name="%s" value="%s">' % (e(name), e(value))


def seed_icon(name):
    # Baseline vector illustrations are placeholders; generated assets are monochrome PNG.
    shapes = {
        '鸡蛋': '<path d="M50 12C32 12 20 46 20 64a30 27 0 0060 0C80 46 68 12 50 12Z"/>',
        '土豆': '<path d="M18 37Q6 60 25 77Q49 94 77 72Q98 48 76 25Q46 5 18 37Z"/><path d="M30 40h3m27-9h3M48 63h3m21-12h3"/>',
        '番茄': '<path d="M48 33C5 11 2 80 42 86Q83 94 89 54Q89 21 55 33"/><path d="M50 15v22m-18-9 18 9 17-13m-17 13-7 13m7-13 17 8"/>',
        '鸡腿': '<path d="M64 58C94 65 98 29 78 19Q48 3 40 37L23 59Q8 52 9 66Q5 79 20 76L40 59Q49 64 64 58Z"/>',
        '香菇': '<path d="M9 56Q15 8 50 12Q87 15 92 56Z"/><path d="M40 56 35 88h30l-5-32M29 35h1m31-7h1m12 15h1"/>',
        '青菜': '<path d="M45 88Q7 63 14 30Q35 15 47 58Q37 5 60 10Q83 20 58 63Q79 27 91 44Q99 65 55 88ZM47 58l3 30"/>',
        '胡萝卜': '<path d="M24 35 75 44 29 90ZM45 39Q25 2 42 12l13 23Q48 1 65 9l-3 28Q90 10 87 28L72 42M32 53l14 3m-12 9 7 2"/>',
        '豆腐': '<path d="M15 35 62 16 89 33 42 53ZM15 35v38l27 17 47-22V33M42 53v37"/>',
    }
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><g fill="white" stroke="black" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round">' + shapes.get(name, '<path d="M20 30h60v50H20ZM30 20v10m20-10v10m20-10v10"/>') + '</g></svg>'


def page(tab='pick', message='', candidates=None):
    state = load_state()
    with db() as conn:
        names = [x[0] for x in conn.execute('SELECT name FROM ingredients ORDER BY rowid')]
    cached = {x for x in names if saved_icon(x)}
    body = '<p class="eyebrow">KITCHEN / KINDLE</p><h1>今天，做点什么？</h1><p>选好手边的食材，做一顿合心意的饭。</p>'
    body += '<nav><a href="/">选食材</a><a href="/?tab=cook">跟着做</a><a href="/?tab=library">手机食材库</a></nav>'
    if message:
        body += '<p class="notice" role="status">%s</p>' % e(message)
    if tab == 'library':
        body += '<h2>让食材库慢慢长大</h2><p>拍照识别只产生候选名称，请先确认。生成图片另行点击，已有图片会复用。</p>'
        body += '<form action="/recognize" method="post" enctype="multipart/form-data"><label>拍照 / 选照片<input type="file" name="photo" accept="image/jpeg,image/png,image/webp" capture="environment"></label><label>补充说明<input name="note" maxlength="500" placeholder="例如：左边是鸡腿，不是鸭腿"></label><button>识别食材（调用 API）</button></form>'
        body += '<h2>确认 / 手动添加</h2>'
        body += form('add', '<label>食材名称，用逗号分隔<input name="names" maxlength="500" value="%s" placeholder="鸡腿，土豆，鸡蛋" required></label>' % e('，'.join(candidates or [])), '确认加入食材库')
        body += '<div class="cards">'
        for name in names:
            body += '<section class="card"><img src="/icon?name=%s" alt=""><h3>%s</h3><p>%s</p>%s</section>' % (parse.quote(name), e(name), '黑白 PNG 已保存' if name in cached else '内置示意图 / 尚未生图', form('generate', hidden('name', name), '复用已存图片' if name in cached else '生成图片（调用 API）'))
        body += '</div>'
    elif tab == 'cook':
        recipe = next((r for r in recipes() if r['id'] == state['recipe']), None)
        if not recipe:
            body += '<h2>还没开始做饭</h2><p>先选食材，再选一道菜。</p><a href="/">去选食材 →</a>'
        else:
            step = state['step']
            body += '<h2>%s</h2><p>参考份量 %s 人 · 你选择了 %s 人；原型暂未自动换算用量。</p>' % (e(recipe['name']), recipe['servings'], state['people'])
            body += '<details><summary>查看用量和完整步骤</summary><ul>%s</ul><ol>%s</ol></details>' % (''.join('<li>%s</li>' % e(x) for x in recipe['amounts']), ''.join('<li>%s</li>' % e(x) for x in recipe['steps']))
            if step < len(recipe['steps']):
                body += '<p class="eyebrow">第 %s / %s 步</p><article class="step">%s</article>' % (step + 1, len(recipe['steps']), e(recipe['steps'][step]))
                body += '<div class="actions">' + form('step', hidden('delta', -1), '上一步') + form('step', hidden('delta', 1), '下一步 / 完成') + '</div>'
                body += form('ask', '<label>遇到问题？<input name="question" maxlength="500" required placeholder="没有生抽怎么办？"></label>', '询问助手（调用 API）')
            else:
                body += '<h2>这道菜完成了。</h2><p>下次打开仍会保留这次进度。</p><a href="/">再选一道菜 →</a>'
    else:
        body += '<h2>01 / 选手边的食材</h2><div class="cards">'
        for name in names:
            selected = name in state['selected']
            body += form('toggle', hidden('name', name), '<img src="/icon?name=%s" alt="">' % parse.quote(name) + ('✓ ' if selected else '＋ ') + e(name), 'card chosen' if selected else 'card')
        body += '</div><p>已选：%s</p>' % e('、'.join(state['selected']) or '还没有，点图片即可选择')
        body += form('preferences', '<label>几个人吃<input type="number" name="people" value="%s" min="1" max="12" required></label><label>可用分钟<input type="number" name="minutes" value="%s" min="5" max="240" required></label>' % (state['people'], state['minutes']), '更新用餐条件')
        body += '<h2>02 / 今天可以做</h2><p>先按缺少食材数量排序，再考虑时间。默认油、盐等调料需自行确认。</p>'
        for recipe in recommend(state):
            missing = set(recipe['ingredients']) - set(state['selected'])
            body += '<section class="recipe"><h3>%s</h3><p>%s 分钟%s · %s</p>%s</section>' % (e(recipe['name']), recipe['minutes'], '（超出所选时间）' if recipe['minutes'] > state['minutes'] else '', '还缺：' + e('、'.join(sorted(missing))) if missing else '主要食材已齐', form('start', hidden('recipe', recipe['id']), '查看备料，开始做'))
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>厨房 · Kindle</title><link rel="stylesheet" href="/style.css"><main>' + body + '<footer>本地原型 · 无动画，不自动刷新<br>照片识别、生图和答疑需要后端 API；图标保存在本机 data 目录。</footer></main></html>').encode('utf-8')


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Avoid logging uploaded text or auth credentials.
        print('%s %s' % (self.command, parse.urlsplit(self.path).path))

    def authorized(self):
        password = os.getenv('KITCHEN_PASSWORD')
        if password:
            expected = 'Basic ' + base64.b64encode(('kitchen:' + password).encode()).decode()
            if not secrets.compare_digest(self.headers.get('Authorization', ''), expected):
                self.send_response(401)
                self.send_header('WWW-Authenticate', 'Basic realm="Kitchen"')
                self.end_headers()
                return False
        return True

    def send(self, body, kind='text/html; charset=utf-8', status=200):
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith('/admin/'):
            import admin_api
            admin_api.handle(self, sys.modules[__name__])
            return
        if self.path.startswith('/app/'):
            import mobile_api
            mobile_api.handle(self, sys.modules[__name__])
            return
        if not self.authorized():
            return
        url = parse.urlsplit(self.path)
        query = parse.parse_qs(url.query)
        if url.path.startswith('/animations/'):
            relative = url.path[len('/animations/'):]
            if not relative:
                relative = 'index.html'
            animation_root = ROOT / 'animations'
            target = (animation_root / relative).resolve()
            allowed = {'.html': 'text/html; charset=utf-8', '.css': 'text/css', '.js': 'application/javascript', '.json': 'application/json', '.svg': 'image/svg+xml'}
            if not target.is_relative_to(animation_root) or not target.is_file() or target.suffix not in allowed:
                self.send(b'Not found', 'text/plain', 404)
                return
            self.send(target.read_bytes(), allowed[target.suffix])
            return
        if url.path == '/style.css':
            self.send((ROOT / 'style.css').read_bytes(), 'text/css')
        elif url.path == '/icon':
            try:
                name = name_of(query.get('name', [''])[0])
            except ValueError:
                self.send(b'Invalid name', 'text/plain', 400)
                return
            png = saved_icon(name)
            self.send(png if png else seed_icon(name).encode(), 'image/png' if png else 'image/svg+xml')
        elif url.path == '/':
            self.send(page(query.get('tab', ['pick'])[0]))
        else:
            self.send(b'Not found', 'text/plain', 404)

    def fields(self):
        length = int(self.headers.get('Content-Length', '0'))
        if not 0 <= length <= MAX_BODY:
            raise ValueError('上传太大，请选择 8 MB 以内的照片。')
        raw = self.rfile.read(length)
        content_type = self.headers.get('Content-Type', '')
        if content_type.startswith('multipart/form-data'):
            msg = BytesParser(policy=default).parsebytes(('Content-Type: ' + content_type + '\r\nMIME-Version: 1.0\r\n\r\n').encode() + raw)
            fields = {}
            for part in msg.iter_parts():
                name = part.get_param('name', header='content-disposition')
                value = part.get_payload(decode=True) or b''
                fields[name] = value if name == 'photo' else value.decode('utf-8')
            return fields
        return {k: v[0] for k, v in parse.parse_qs(raw.decode('utf-8'), keep_blank_values=True).items()}

    def do_POST(self):
        if self.path.startswith('/admin/'):
            import admin_api
            admin_api.handle(self, sys.modules[__name__])
            return
        if self.path.startswith('/app/'):
            import mobile_api
            mobile_api.handle(self, sys.modules[__name__])
            return
        with STATE_LOCK if parse.urlsplit(self.path).path in ('/toggle', '/preferences', '/start', '/step') else nullcontext():
            self.form_post()

    def form_post(self):
        if not self.authorized():
            return
        origin = self.headers.get('Origin') or self.headers.get('Referer')
        if origin and parse.urlsplit(origin).netloc != self.headers.get('Host'):
            self.send(b'Origin rejected', 'text/plain', 403)
            return
        tab = 'pick'
        try:
            fields = self.fields()
            state = load_state()
            action = parse.urlsplit(self.path).path
            message = ''
            if action == '/toggle':
                name = name_of(fields['name'])
                with db() as conn:
                    if not conn.execute('SELECT 1 FROM ingredients WHERE name=?', (name,)).fetchone():
                        raise ValueError('请先把这个食材加入食材库。')
                if name in state['selected']:
                    state['selected'].remove(name)
                else:
                    state['selected'].append(name)
            elif action == '/preferences':
                people, minutes = int(fields['people']), int(fields['minutes'])
                if not 1 <= people <= 12 or not 5 <= minutes <= 240:
                    raise ValueError('人数应为 1～12，时间为 5～240 分钟。')
                state.update(people=people, minutes=minutes)
            elif action == '/start':
                if fields['recipe'] not in [r['id'] for r in recipes()]:
                    raise ValueError('找不到这道菜。')
                state.update(recipe=fields['recipe'], step=0)
                tab = 'cook'
            elif action == '/step':
                recipe = next(r for r in recipes() if r['id'] == state['recipe'])
                delta = int(fields['delta'])
                if delta not in (-1, 1):
                    raise ValueError('无效步骤。')
                state['step'] = max(0, min(len(recipe['steps']), state['step'] + delta))
                tab = 'cook'
            elif action == '/recognize':
                tab = 'library'
                photo, note = fields.get('photo', b''), fields.get('note', '').strip()
                if len(photo) > 8 * 1024 * 1024 or len(note) > 500 or not (photo or note):
                    raise ValueError('请选择 8 MB 以内的照片，或填写 500 字以内的说明。')
                names = recognize(photo, note)
                self.send(page(tab, '请检查并修改名称后，再确认加入。' if names else '没有识别到食材，请手动填写。', names))
                return
            elif action == '/add':
                tab = 'library'
                names = [name_of(x) for x in re.split(r'[,，、\n]+', fields['names']) if x.strip()]
                if not 1 <= len(names) <= 20:
                    raise ValueError('每次添加 1～20 种食材。')
                with db() as conn:
                    conn.executemany('INSERT OR IGNORE INTO ingredients VALUES (?)', [(x,) for x in names])
                message = '已加入食材库；名称已去重，没有自动调用生图。'
            elif action == '/generate':
                tab = 'library'
                name = name_of(fields['name'])
                with db() as conn:
                    if not conn.execute('SELECT 1 FROM ingredients WHERE name=?', (name,)).fetchone():
                        raise ValueError('请先确认并添加食材。')
                message = '黑白 PNG 已生成并保存。' if generate_icon(name) else '已复用原有图片，本次没有调用生图 API。'
            elif action == '/ask':
                tab = 'cook'
                recipe = next(r for r in recipes() if r['id'] == state['recipe'])
                question = fields['question'].strip()
                if not 1 <= len(question) <= 500:
                    raise ValueError('问题限 1～500 字。')
                result = api('CHAT', 'chat/completions', {'model': model_config('CHAT')['model'],
                    'messages': [{'role': 'system', 'content': (ROOT / 'prompts/assistant.txt').read_text(encoding='utf-8')},
                    {'role': 'user', 'content': json.dumps({'recipe': recipe, 'step': state['step'] + 1, 'people': state['people'], 'question': question}, ensure_ascii=False)}],
                    'thinking': {'type': 'disabled'}, 'stream': False})
                message = response_text(result) or '助手未返回回答，请重试。'
            else:
                self.send(b'Not found', 'text/plain', 404)
                return
            if action in ('/toggle', '/preferences', '/start', '/step'):
                save_state(state)
            if message:
                self.send(page(tab, message))
            else:
                self.send_response(303)
                self.send_header('Location', '/?tab=' + tab)
                self.end_headers()
        except (ValueError, KeyError, StopIteration, UnicodeError) as exc:
            self.send(page(tab, str(exc) or '操作无效，请返回重试。'), status=400)
        except Exception:
            self.send(page(tab, '操作失败，未能完成。请检查服务端配置后重试。'), status=500)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', default=8765, type=int)
    args = parser.parse_args()
    if args.host not in ('127.0.0.1', 'localhost', '::1') and not os.getenv('KITCHEN_PASSWORD'):
        parser.error('局域网模式需要设置 KITCHEN_PASSWORD，用户名为 kitchen。')
    print('Kitchen: http://%s:%s' % (args.host, args.port), flush=True)
    # shortcut: one household; add per-user sessions before shared hosting.
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
