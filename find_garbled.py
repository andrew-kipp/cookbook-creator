import sys, json, re
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

RECIPES_DIR = Path('All Recipes')
mismatches = []
for jf in sorted(RECIPES_DIR.glob('*.json')):
    with open(jf, 'r', encoding='utf-8') as f:
        data = json.load(f)
    name = data.get('name', '')
    safe_name = re.sub(r'[<>:"/\\|?*]', '', name).strip()
    expected = safe_name + '.json'
    actual = jf.name
    if actual != expected:
        mismatches.append((jf, expected))

for jf, expected in mismatches:
    print(f'GARBLED: {repr(jf.name)}')
    print(f'CORRECT: {repr(expected)}')
    print()
print(f'Total: {len(mismatches)} garbled files')
