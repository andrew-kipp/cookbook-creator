import sys, json, re
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

RECIPES_DIR = Path('All Recipes')
renamed = 0
skipped = 0
for jf in sorted(RECIPES_DIR.glob('*.json')):
    with open(jf, 'r', encoding='utf-8') as f:
        data = json.load(f)
    name = data.get('name', '')
    safe_name = re.sub(r'[<>:"/\\|?*]', '', name).strip()
    expected = RECIPES_DIR / (safe_name + '.json')
    if jf == expected:
        skipped += 1
        continue
    if expected.exists():
        print(f'CONFLICT (target already exists, skipping): {jf.name} -> {expected.name}')
        skipped += 1
        continue
    jf.rename(expected)
    print(f'Renamed: {jf.name}')
    print(f'     to: {expected.name}')
    print()
    renamed += 1

print(f'Done: {renamed} renamed, {skipped} already correct.')
