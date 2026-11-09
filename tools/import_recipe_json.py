"""Import a reviewed JSON recipe export into the local kitchen database.

Use only data you are allowed to redistribute or use in this application.
Expected format: a JSON list, or {"recipes": [...]} with the app's recipe fields.
"""
import argparse
import json
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import admin_api
import app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path, help='reviewed JSON recipe export')
    parser.add_argument('--limit', type=int, default=100, help='maximum recipes to import')
    parser.add_argument('--data', type=Path, default=ROOT / 'data', help='kitchen data directory')
    args = parser.parse_args()
    if args.limit < 1:
        parser.error('--limit must be positive')
    raw = json.loads(args.source.read_text(encoding='utf-8'))
    records = raw.get('recipes') if isinstance(raw, dict) else raw
    if not isinstance(records, list):
        parser.error('source must be a JSON list or an object with a recipes list')
    app.DATA = args.data
    imported, skipped = 0, 0
    with app.db() as conn:
        for record in records[:args.limit]:
            try:
                recipe = admin_api.valid_recipe(app, record)
            except (ValueError, TypeError):
                skipped += 1
                continue
            conn.execute('INSERT OR REPLACE INTO recipes VALUES (?,?)', (recipe['id'], json.dumps(recipe, ensure_ascii=False)))
            conn.executemany('INSERT OR IGNORE INTO ingredients VALUES (?)', [(name,) for name in recipe['ingredients']])
            imported += 1
    print('Imported %s recipes; skipped %s invalid records.' % (imported, skipped))


if __name__ == '__main__':
    main()
