"""
Test script: runs pdf_to_json() on every PDF in 'All Recipes' and compares
the result against the matching existing .json file.

Fields compared (others like uid/created/photos differ by design):
  name, servings, prep_time, cook_time, total_time, source,
  rating, ingredients, directions, notes, nutritional_info
"""

import json
import os
import sys
from pathlib import Path

# Fix encoding for Windows console
sys.stdout.reconfigure(encoding='utf-8')

# Ensure the project root is on the path
sys.path.insert(0, str(Path(__file__).parent))
from PDFToJSONRecipe import pdf_to_json

RECIPES_DIR = Path(__file__).parent / 'All Recipes'
COMPARE_FIELDS = [
    'name', 'servings', 'prep_time', 'cook_time', 'total_time',
    'source', 'rating', 'ingredients', 'directions', 'notes',
    'nutritional_info',
]

# Must stay in sync with RecipeFormatter._CHAR_MAP — maps source chars to what
# the PDF pipeline renders, so round-trip comparisons are fair.
_CHAR_MAP = {
    # Unicode fractions
    '\u2150': '1/7',  '\u2151': '1/9',  '\u2152': '1/10',
    '\u2153': '1/3',  '\u2154': '2/3',
    '\u2155': '1/5',  '\u2156': '2/5',  '\u2157': '3/5',  '\u2158': '4/5',
    '\u2159': '1/6',  '\u215a': '5/6',
    '\u215b': '1/8',  '\u215c': '3/8',  '\u215d': '5/8',  '\u215e': '7/8',
    # Degree units
    '\u2109': '\u00b0F',   # ℉ → °F
    '\u2103': '\u00b0C',   # ℃ → °C
    # Windows-1252 mojibake bytes stored as Unicode control points
    '\x96': '-',    '\x97': '--',
    '\x91': "'",    '\x92': "'",
    '\x93': '"',    '\x94': '"',
    '\x95': '\u2022',
    '\x85': '...',
}
# Legacy alias used by some callers
_FRACTION_MAP = {k: v for k, v in _CHAR_MAP.items() if '\u2150' <= k <= '\u215e'}

def normalise(value):
    """Normalise a field value for round-trip comparison:
    - Strip invisible Unicode characters (zero-width spaces, BOM, etc.)
    - Map characters that RecipeFormatter._safe() replaces, so the expected
      and extracted values go through the same transformations.
    - Collapse all whitespace."""
    if isinstance(value, str):
        import re
        value = re.sub(r'[\u200b\u200c\u200d\u200e\u200f\ufeff]', '', value)
        for ch, rep in _CHAR_MAP.items():
            value = value.replace(ch, rep)
        return ' '.join(value.split())
    return value


def compare_recipes(pdf_path, json_path):
    """Return list of (field, expected, got) tuples for mismatches."""
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


def main():
    pdf_files = sorted(RECIPES_DIR.glob('*.pdf'))
    if not pdf_files:
        print('No PDF files found in', RECIPES_DIR)
        sys.exit(1)

    total = len(pdf_files)
    passed = 0
    failed = 0
    skipped = 0
    all_field_failures = {}  # field -> count

    for pdf_path in pdf_files:
        # Derive expected JSON path (strip rating suffix from stem)
        import re
        stem = re.sub(r'\s*\(\d+\s*Stars?\)\s*$', '', pdf_path.stem, flags=re.IGNORECASE).strip()
        json_path = RECIPES_DIR / f'{stem}.json'

        if not json_path.exists():
            print(f'  [SKIP] No JSON for: {pdf_path.name}')
            skipped += 1
            continue

        try:
            mismatches = compare_recipes(pdf_path, json_path)
        except Exception as e:
            print(f'  [ERROR] {pdf_path.name}: {e}')
            failed += 1
            continue

        if not mismatches:
            passed += 1
        else:
            failed += 1
            print(f'\n[FAIL] {pdf_path.name}')
            for field, expected, got in mismatches:
                all_field_failures[field] = all_field_failures.get(field, 0) + 1
                # Truncate long diffs
                exp_short = (str(expected)[:200] + '…') if len(str(expected)) > 200 else str(expected)
                got_short = (str(got)[:200] + '…') if len(str(got)) > 200 else str(got)
                print(f'  Field: {field}')
                print(f'    EXPECTED: {exp_short}')
                print(f'    GOT:      {got_short}')

    print(f'\n{"="*60}')
    print(f'Results: {passed}/{total} passed, {failed} failed, {skipped} skipped')
    if all_field_failures:
        print('\nField failure counts:')
        for field, count in sorted(all_field_failures.items(), key=lambda x: -x[1]):
            print(f'  {field}: {count}')


if __name__ == '__main__':
    main()
