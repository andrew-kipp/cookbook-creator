"""
PDF to JSON Recipe Converter

Reverses the RecipeFormatter layout to extract recipe data from a PDF
and produce a Paprika-compatible JSON file.

Relies on the known layout produced by RecipeFormatter.py:
  - Page 1:
      Title (size 20, bold)
      Info line (Servings | Prep | Cook | Total)
      Source line
      Two-column table: 30% Ingredients (left) / 70% Directions+Notes (right)
      Nutritional Information beneath the table
  - Page 2 (optional): overflow ingredients + recipe image (no text extracted)

Usage:
    python PDFToJSONRecipe.py "All Recipes/Recipe Name (0 Stars).pdf"
    Outputs: All Recipes/Recipe Name.json

    Or import and call pdf_to_json(pdf_path) -> dict
"""

import fitz  # PyMuPDF
import json
import os
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path


# ── Layout constants (match RecipeFormatter.py, converted to PDF points) ──────
# 1 inch = 72 pt
COLUMN_SPLIT_X = 180.0   # x0 threshold: < this = left col, >= this = right col
TITLE_FONT_SIZE = 14.0   # minimum font size to identify the title
HEADING_FONT_SIZE = 11.0 # minimum font size for section headings (Ingredients/Directions/Notes)
Y_TOLERANCE = 3.0        # points — spans within this y-distance are on the same line
BULLET_CHARS = {'\u2022', '\u00b7', '\u25cf', '\u25aa', '\uf0b7', '\uf0a7'}


def _group_spans_by_y(spans):
    """Group spans into rows by approximate y-coordinate."""
    rows = {}
    for s in spans:
        placed = False
        for key in rows:
            if abs(s['y0'] - key) <= Y_TOLERANCE:
                rows[key].append(s)
                placed = True
                break
        if not placed:
            rows[s['y0']] = [s]
    # Sort each row by x0
    for key in rows:
        rows[key].sort(key=lambda sp: sp['x0'])
    return dict(sorted(rows.items()))


def _extract_spans(page):
    """Return all non-empty text spans from a page as list of dicts."""
    spans = []
    d = page.get_text('dict')
    for block in d['blocks']:
        if block['type'] != 0:
            continue
        for line in block['lines']:
            for span in line['spans']:
                text = span['text'].strip()
                if text:
                    spans.append({
                        'text': text,
                        'x0': span['bbox'][0],
                        'y0': span['bbox'][1],
                        'size': span['size'],
                        'bold': 'Bold' in span['font'],
                    })
    return spans


def _strip_bullet(text):
    """Remove leading bullet character and surrounding whitespace."""
    if text and text[0] in BULLET_CHARS:
        return text[1:].strip()
    return text.strip()


def _parse_header(header_rows):
    """
    Extract name, servings, prep_time, cook_time, total_time, source
    from the rows above the two-column table.
    """
    name_parts = []
    servings = prep_time = cook_time = total_time = source = ''

    info_keys = {'Servings:', 'Prep:', 'Cook:', 'Total:'}
    info_y = None
    source_y = None

    for y, row in header_rows.items():
        bold_texts = [s['text'] for s in row if s['bold']]
        # Title: bold span(s) with large font
        for s in row:
            if s['bold'] and s['size'] >= TITLE_FONT_SIZE and s['text'] not in info_keys:
                name_parts.append(s['text'])
        # Detect info line y
        if info_y is None and any(t in info_keys for t in bold_texts):
            info_y = y
        # Detect source line y
        if source_y is None and any('Source:' in t for t in bold_texts):
            source_y = y

    # Parse info line
    if info_y is not None:
        info_row = header_rows[info_y]
        bold_spans = [s for s in info_row if s['bold']]
        normal_spans = [s for s in info_row if not s['bold']]

        for ks in bold_spans:
            key = ks['text'].rstrip(':').strip()
            # Find the first non-bold span to the right of this key span
            candidates = [v for v in normal_spans if v['x0'] > ks['x0'] - 5]
            candidates.sort(key=lambda v: v['x0'])
            if candidates:
                val = candidates[0]['text'].rstrip('|').strip()
                if key == 'Servings':
                    servings = val
                elif key == 'Prep':
                    prep_time = val
                elif key == 'Cook':
                    cook_time = val
                elif key == 'Total':
                    total_time = val

    # Parse source line
    if source_y is not None:
        src_row = header_rows[source_y]
        normal_spans = [s for s in src_row if not s['bold']]
        if normal_spans:
            source = normal_spans[0]['text'].strip()

    name = ' '.join(name_parts).strip()
    return name, servings, prep_time, cook_time, total_time, source


def _is_section_heading(span):
    """True if this span is a column heading that should be skipped during content parsing.
    Note: 'Notes' is intentionally excluded here so it reaches _parse_directions_and_notes
    as a section-switch marker."""
    return (span['bold']
            and span['size'] >= HEADING_FONT_SIZE
            and span['text'].strip() in ('Ingredients', 'Ingredients (continued)', 'Directions'))


def _parse_columns(table_rows):
    """
    Split table rows into left (ingredients) and right (directions/notes) spans,
    stopping when we hit the Nutritional Information label.

    Returns:
        left_spans  – list of spans for ingredients
        right_rows  – OrderedDict of y -> [spans] for directions + notes
        nutr_spans  – list of spans for nutritional info
    """
    left_spans = []
    right_rows = {}
    nutr_spans = []
    in_nutr = False

    for y, row in table_rows.items():
        # Check for nutritional info marker
        for s in row:
            if s['bold'] and 'Nutritional Information:' in s['text']:
                in_nutr = True
                break

        if in_nutr:
            # Collect the non-label spans from the same row as the marker, plus all subsequent
            for s in row:
                if not (s['bold'] and 'Nutritional Information:' in s['text']):
                    nutr_spans.append(s)
            continue

        for s in row:
            if _is_section_heading(s):
                continue  # skip column headings
            if s['x0'] < COLUMN_SPLIT_X:
                left_spans.append(s)
            else:
                if y not in right_rows:
                    right_rows[y] = []
                right_rows[y].append(s)

    right_rows = dict(sorted(right_rows.items()))
    return left_spans, right_rows, nutr_spans


def _parse_ingredients(left_spans):
    """
    Reconstruct ingredient lines from left-column spans.
    Spans starting with a bullet begin a new ingredient;
    non-bullet spans are continuations of the previous ingredient.
    """
    ingredients = []
    current_line = None

    # Sort by y then x
    left_spans = sorted(left_spans, key=lambda s: (s['y0'], s['x0']))

    for s in left_spans:
        text = s['text'].strip()
        if text[0] in BULLET_CHARS:
            if current_line is not None:
                ingredients.append(current_line)
            current_line = _strip_bullet(text)
        else:
            # Continuation of previous ingredient
            if current_line is not None:
                current_line = current_line + ' ' + text
            else:
                current_line = text

    if current_line is not None:
        ingredients.append(current_line)

    return '\n'.join(ingredients)


def _parse_directions_and_notes(right_rows):
    """
    Reconstruct directions (as original \n\n-separated paragraphs) and notes
    from right-column rows.
    """
    steps = []
    current_step_parts = []
    notes_parts = []
    in_notes = False

    step_label_re = re.compile(r'^Step \d+:$')

    for y, row in right_rows.items():
        bold_texts = [s['text'].strip() for s in row if s['bold']]
        normal_spans = [s for s in row if not s['bold']]

        # Detect Notes heading (bold "Notes" in right column)
        if any(t == 'Notes' for t in bold_texts):
            if current_step_parts:
                steps.append(' '.join(current_step_parts).strip())
                current_step_parts = []
            in_notes = True
            continue

        if in_notes:
            notes_parts.extend(s['text'] for s in row)
            continue

        # Detect step label "Step N:"
        is_step_start = any(step_label_re.match(t) for t in bold_texts)
        if is_step_start:
            if current_step_parts:
                steps.append(' '.join(current_step_parts).strip())
                current_step_parts = []
            # Add the non-bold text from this same line (first line of the step)
            step_first = ' '.join(s['text'] for s in normal_spans).strip()
            if step_first:
                current_step_parts.append(step_first)
        else:
            # Continuation line
            line_text = ' '.join(s['text'] for s in row).strip()
            if line_text:
                current_step_parts.append(line_text)

    if current_step_parts:
        steps.append(' '.join(current_step_parts).strip())

    directions = '\n\n'.join(steps)
    notes = ' '.join(notes_parts).strip()
    return directions, notes


def _parse_nutritional_info(nutr_spans):
    """Join all nutritional info spans into a single string.
    RecipeFormatter joins nutritional items with ' | ' for display; strip those back to spaces."""
    if not nutr_spans:
        return ''
    nutr_spans = sorted(nutr_spans, key=lambda s: (s['y0'], s['x0']))
    # Group by y-line to preserve structure
    rows = _group_spans_by_y(nutr_spans)
    lines = [' '.join(s['text'] for s in row) for row in rows.values()]
    result = ' '.join(lines)
    result = re.sub(r'\s*\|\s*', ' ', result).strip()
    return result


def pdf_to_json(pdf_path):
    """
    Extract recipe data from a PDF created by RecipeFormatter and return
    a Paprika-compatible JSON dict.

    Args:
        pdf_path: path to the PDF file

    Returns:
        dict with all Paprika recipe fields
    """
    pdf_path = str(pdf_path)
    doc = fitz.open(pdf_path)

    # ── Collect all text spans from page 0 ─────────────────────────────────
    page = doc[0]
    spans = _extract_spans(page)

    # ── Find table_y (y of "Ingredients" heading) ──────────────────────────
    table_y = None
    for s in sorted(spans, key=lambda sp: sp['y0']):
        if s['bold'] and s['text'].strip() == 'Ingredients':
            table_y = s['y0']
            break

    if table_y is None:
        # Fallback: everything is header
        table_y = max(s['y0'] for s in spans) + 1

    # ── Split spans into header and table sections ──────────────────────────
    header_spans = [s for s in spans if s['y0'] < table_y - Y_TOLERANCE]
    table_spans  = [s for s in spans if s['y0'] >= table_y - Y_TOLERANCE]

    header_rows = _group_spans_by_y(header_spans)
    table_rows  = _group_spans_by_y(table_spans)

    # ── Parse header ────────────────────────────────────────────────────────
    name, servings, prep_time, cook_time, total_time, source = _parse_header(header_rows)

    # ── Parse columns ───────────────────────────────────────────────────────
    left_spans, right_rows, nutr_spans = _parse_columns(table_rows)

    # ── Check page 2+ for overflow content (ingredients + directions/notes) ──
    # Section headings and continuation headings that should be skipped
    OVERFLOW_SKIP_HEADINGS = {
        'Ingredients (continued)', 'Directions (continued)', 'Directions', 'Ingredients'
    }
    # Track whether we've entered the nutritional info section on an overflow page
    in_nutr_overflow = False
    next_right_y = max(right_rows.keys(), default=0) + 100000  # offset for page-2+ right rows

    for page_num in range(1, doc.page_count):
        extra_page = doc[page_num]
        extra_spans = _extract_spans(extra_page)
        if not extra_spans:
            continue
        extra_rows = _group_spans_by_y(extra_spans)
        for y, row in extra_rows.items():
            # Check for nutritional info marker (can appear on overflow pages)
            if not in_nutr_overflow:
                for s in row:
                    if s['bold'] and 'Nutritional Information:' in s['text']:
                        in_nutr_overflow = True
                        break
            if in_nutr_overflow:
                # Exit nutr mode when we reach the overflow table section headings
                hit_section = any(
                    s['bold'] and s['text'].strip() in OVERFLOW_SKIP_HEADINGS
                    for s in row
                )
                if hit_section:
                    in_nutr_overflow = False
                else:
                    # Only collect left-column spans; right column can't be nutr info
                    for s in row:
                        if (not (s['bold'] and 'Nutritional Information:' in s['text'])
                                and s['x0'] < COLUMN_SPLIT_X):
                            nutr_spans.append(s)
                    continue

            for s in row:
                heading_text = s['text'].strip()
                # Skip known section/continuation headings
                if s['bold'] and heading_text in OVERFLOW_SKIP_HEADINGS:
                    continue
                if _is_section_heading(s):
                    continue
                if s['x0'] < COLUMN_SPLIT_X:
                    left_spans.append(s)
                else:
                    # Right column overflow: append with page-offset y to preserve order
                    right_rows[next_right_y] = right_rows.get(next_right_y, [])
                    right_rows[next_right_y].append(s)
                    next_right_y += 1

    right_rows = dict(sorted(right_rows.items()))

    # ── Parse sections ──────────────────────────────────────────────────────
    ingredients = _parse_ingredients(left_spans)
    directions, notes = _parse_directions_and_notes(right_rows)
    nutritional_info = _parse_nutritional_info(nutr_spans)

    # ── Rating from filename ────────────────────────────────────────────────
    pdf_stem = Path(pdf_path).stem
    rating_match = re.search(r'\((\d+)\s*Stars?\)', pdf_stem, re.IGNORECASE)
    rating = int(rating_match.group(1)) if rating_match else 0

    # ── Assemble JSON ───────────────────────────────────────────────────────
    recipe = {
        'name': name,
        'uid': str(uuid.uuid4()).upper(),
        'created': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'hash': '',
        'servings': servings,
        'prep_time': prep_time,
        'cook_time': cook_time,
        'total_time': total_time,
        'ingredients': ingredients,
        'directions': directions,
        'notes': notes,
        'nutritional_info': nutritional_info,
        'source': source,
        'source_url': '',   # URLs are not printed in the PDF
        'image_url': '',
        'rating': rating,
        'difficulty': '',
        'description': '',
        'categories': [],
        'photos': [],
        'photo': None,
        'photo_large': None,
        'photo_data': None,
        'photo_hash': None,
    }

    doc.close()
    return recipe


def main():
    if len(sys.argv) < 2:
        print('Usage: python PDFToJSONRecipe.py <path_to_pdf>')
        print('Example: python PDFToJSONRecipe.py "All Recipes/Recipe Name (0 Stars).pdf"')
        sys.exit(1)

    pdf_path = sys.argv[1]
    if not os.path.exists(pdf_path):
        print(f'Error: File not found: {pdf_path}')
        sys.exit(1)

    print(f'Processing: {pdf_path}')
    recipe = pdf_to_json(pdf_path)

    # Derive output path: same folder, base name (strip rating suffix)
    pdf_stem = Path(pdf_path).stem
    base_name = re.sub(r'\s*\(\d+\s*Stars?\)\s*$', '', pdf_stem, flags=re.IGNORECASE).strip()
    output_path = Path(pdf_path).parent / f'{base_name}.json'

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(recipe, f, indent=2, ensure_ascii=False)

    print(f'Saved: {output_path}')
    print(f'  name:         {recipe["name"]}')
    print(f'  servings:     {recipe["servings"]}')
    print(f'  prep_time:    {recipe["prep_time"]}')
    print(f'  cook_time:    {recipe["cook_time"]}')
    print(f'  total_time:   {recipe["total_time"]}')
    print(f'  source:       {recipe["source"]}')
    print(f'  rating:       {recipe["rating"]}')
    print(f'  ingredients:  {len(recipe["ingredients"].splitlines())} lines')
    directions_count = len([p for p in recipe["directions"].split("\n\n") if p.strip()])
    print(f'  directions:   {directions_count} steps')
    print(f'  notes:        {bool(recipe["notes"].strip())}')
    print(f'  nutritional:  {bool(recipe["nutritional_info"].strip())}')


if __name__ == '__main__':
    main()
