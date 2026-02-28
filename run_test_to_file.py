"""Wrapper that runs the test logic and writes output to test_output.txt with UTF-8 encoding."""
import sys
import io
import json
import os
import re
from pathlib import Path

# Redirect stdout to a UTF-8 file
out = io.open(Path(__file__).parent / 'test_output.txt', 'w', encoding='utf-8')

sys.path.insert(0, str(Path(__file__).parent))
from PDFToJSONRecipe import pdf_to_json

RECIPES_DIR = Path(__file__).parent / 'All Recipes'
COMPARE_FIELDS = [
    'name', 'servings', 'prep_time', 'cook_time', 'total_time',
    'source', 'rating', 'ingredients', 'directions', 'notes',
    'nutritional_info',
]

def normalise(value):
    if isinstance(value, str):
        return ' '.join(value.split())
    return value

def compare_recipes(pdf_path, json_path):
    with open(json_path, encoding='utf-8') as f:
        expected = json.load(f)
    extracted = pdf_to_json(pdf_path)
    mismatches = []
    for field in COMPARE_FIELDS:
        exp_val = normalise(expected.get(field, ''))
        got_val = normalise(extracted.get(field, ''))
        if exp_val != got_val:
            mismatches.append((field, exp_val, got_val))
    return mismatches

pdf_files = sorted(RECIPES_DIR.glob('*.pdf'))
if not pdf_files:
    out.write('No PDF files found in ' + str(RECIPES_DIR) + '\n')
    out.close()
    sys.exit(1)

total = len(pdf_files)
passed = 0
failed = 0
skipped = 0
all_field_failures = {}

for pdf_path in pdf_files:
    stem = re.sub(r'\s*\(\d+\s*Stars?\)\s*$', '', pdf_path.stem, flags=re.IGNORECASE).strip()
    json_path = RECIPES_DIR / f'{stem}.json'

    if not json_path.exists():
        out.write(f'  [SKIP] No JSON for: {pdf_path.name}\n')
        skipped += 1
        continue

    try:
        mismatches = compare_recipes(pdf_path, json_path)
    except Exception as e:
        out.write(f'  [ERROR] {pdf_path.name}: {e}\n')
        failed += 1
        continue

    if not mismatches:
        passed += 1
    else:
        failed += 1
        out.write(f'\n[FAIL] {pdf_path.name}\n')
        for field, expected_val, got_val in mismatches:
            all_field_failures[field] = all_field_failures.get(field, 0) + 1
            exp_short = (str(expected_val)[:200] + '...') if len(str(expected_val)) > 200 else str(expected_val)
            got_short = (str(got_val)[:200] + '...') if len(str(got_val)) > 200 else str(got_val)
            out.write(f'  Field: {field}\n')
            out.write(f'    EXPECTED: {exp_short}\n')
            out.write(f'    GOT:      {got_short}\n')

out.write(f'\n{"="*60}\n')
out.write(f'Results: {passed}/{total} passed, {failed} failed, {skipped} skipped\n')
if all_field_failures:
    out.write('\nField failure counts:\n')
    for field, count in sorted(all_field_failures.items(), key=lambda x: -x[1]):
        out.write(f'  {field}: {count}\n')

out.close()
print(f'Done. Results: {passed}/{total} passed, {failed} failed, {skipped} skipped')
