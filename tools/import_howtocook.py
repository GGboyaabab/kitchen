"""Import structured recipes from a checked-out howtocook source tree.

The upstream project is Unlicense at the time this tool was written. Review its
license again when updating the source. This importer stores text recipes only,
not upstream images or Markdown files.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import admin_api
import app

INGREDIENT_HEADINGS = ('原料', '食材', '配料', '用料', '材料')
STEP_HEADINGS = ('步骤', '操作', '做法')
RECIPE_CATEGORIES = ('meat_dish', 'vegetable_dish', 'aquatic', 'soup', 'staple', 'breakfast')


def clean_line(value):
    value = re.sub(r'!?(?:\[[^]]*\])?\([^)]*\)', '', value)
    value = re.sub(r'[`*_>#]', '', value)
    return re.sub(r'\s+', ' ', value).strip(' -–—:：')


def title_of(lines):
    heading = next((line for line in lines if line.startswith('# ')), '')
    value = clean_line(heading[2:])
    value = re.sub(r'（[^）]*）|\([^)]*\)|【[^】]*】|\[[^]]*\]', '', value).strip()
    value = re.sub(r'(的)?(?:做法|食谱)$', '', value).strip()
    return app.name_of(value)


def split_sections(lines):
    headings = [(index, clean_line(line.lstrip('# '))) for index, line in enumerate(lines) if re.match(r'^#{2,3}\s+', line)]
    step_index = next((index for index, heading in headings if any(word in heading for word in STEP_HEADINGS)), None)
    if step_index is None:
        return [], [], []
    ingredient_index = next((index for index, heading in headings if index < step_index and any(word in heading for word in INGREDIENT_HEADINGS)), None)
    if ingredient_index is None:
        return [], [], []
    calculation_index = next((index for index, heading in headings if ingredient_index < index < step_index and '计算' in heading), None)
    following = next((index for index, _ in headings if index > ingredient_index), step_index)
    amount_start = calculation_index + 1 if calculation_index is not None else ingredient_index + 1
    amounts = [clean_line(line.lstrip('-* ')) for line in lines[amount_start:step_index if calculation_index is not None else following] if line.lstrip().startswith(('-', '*'))]
    required = [clean_line(line.lstrip('-* ')) for line in lines[ingredient_index + 1:following] if line.lstrip().startswith(('-', '*'))]
    next_heading = next((index for index, _ in headings if index > step_index), len(lines))
    steps = [clean_line(re.sub(r'^\s*\d+[.、]\s*', '', line)) for line in lines[step_index + 1:next_heading] if re.match(r'^\s*\d+[.、]\s*', line)]
    return [line for line in amounts if line], [line for line in steps if line], [line for line in required if line]


def ingredient_names(amounts):
    result = []
    ignored = {'适量', '少许', '可选', '根据', '准备', '工具', '备注'}
    for amount in amounts:
        head = re.split(r'[（(，,、：:\d]', amount, maxsplit=1)[0]
        words = re.findall(r'[\u4e00-\u9fff]{2,12}', head)
        if not words or words[0] in ignored:
            continue
        try:
            name = app.name_of(words[0])
        except ValueError:
            continue
        if name not in result:
            result.append(name)
    return result[:12]


def parse(path, source_root):
    lines = path.read_text(encoding='utf-8').splitlines()
    amounts, steps, required = split_sections(lines)
    ingredients = ingredient_names(required + amounts)
    if not ingredients or not amounts or not steps:
        raise ValueError('missing recipe sections')
    return {
        'id': 'howtocook-' + hashlib.sha256(str(path.relative_to(source_root)).encode()).hexdigest()[:16],
        'name': title_of(lines), 'minutes': int(next(iter(re.findall(r'(\d{1,3})\s*分钟', '\n'.join(lines[:20]))), 30)), 'servings': 2,
        'ingredients': ingredients, 'amounts': amounts[:60], 'steps': steps[:60],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path, help='extracted howtocook repository root')
    parser.add_argument('--limit', type=int, default=100)
    parser.add_argument('--data', type=Path, default=ROOT / 'data')
    args = parser.parse_args()
    if args.limit < 1:
        parser.error('--limit must be positive')
    dishes = args.source / 'dishes'
    if not dishes.is_dir():
        parser.error('source must contain a dishes directory')
    app.DATA = args.data
    imported = skipped = 0
    queues = [sorted((dishes / category).rglob('*.md')) for category in RECIPE_CATEGORIES if (dishes / category).is_dir()]
    paths = []
    while any(queues) and len(paths) < args.limit * 4:
        for queue in queues:
            if queue:
                paths.append(queue.pop(0))
    with app.db() as conn:
        for path in paths:
            if imported >= args.limit:
                break
            try:
                recipe = admin_api.valid_recipe(app, parse(path, args.source))
            except (OSError, UnicodeError, ValueError, TypeError):
                skipped += 1
                continue
            conn.execute('INSERT OR REPLACE INTO recipes VALUES (?,?)', (recipe['id'], json.dumps(recipe, ensure_ascii=False)))
            conn.executemany('INSERT OR IGNORE INTO ingredients VALUES (?)', [(name,) for name in recipe['ingredients']])
            imported += 1
        conn.execute("INSERT OR REPLACE INTO metadata VALUES ('howtocook_source','Anduin2017/HowToCook master, Unlicense')")
    print('Imported %s recipes; skipped %s files.' % (imported, skipped))


if __name__ == '__main__':
    main()
