"""
Recipe PDF Formatter Template

This module provides formatting functions for creating professional recipe PDFs.
It handles the layout with a two-column design:
- Left column (30%): Ingredients list
- Right column (70%): Directions
- Vertical separator line between columns
- Image on second page
"""

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.platypus import Table, TableStyle, Paragraph, Spacer, Image, PageBreak
from reportlab.lib import colors
import os

# Characters not supported by ReportLab's default Helvetica font, or that need
# escaping for ReportLab's XML-like Paragraph parser.
_CHAR_MAP = {
    # '&' must be escaped to '&amp;' for ReportLab's Paragraph XML parser.
    # '&' followed directly by a letter is treated as an entity start (&name;)
    # and produces corrupted output (e.g. "S&B)" → "S&B;)").
    # PyMuPDF always extracts the rendered glyph '&', so normalise() is unchanged.
    '&': '&amp;',
    # Unicode fraction characters (U+2150–U+215E)
    '\u2150': '1/7',  '\u2151': '1/9',  '\u2152': '1/10',
    '\u2153': '1/3',  '\u2154': '2/3',
    '\u2155': '1/5',  '\u2156': '2/5',  '\u2157': '3/5',  '\u2158': '4/5',
    '\u2159': '1/6',  '\u215a': '5/6',
    '\u215b': '1/8',  '\u215c': '3/8',  '\u215d': '5/8',  '\u215e': '7/8',
    # Degree units (U+2109=℉, U+2103=℃) — use degree sign + letter instead
    '\u2109': '\u00b0F',   # ℉ → °F
    '\u2103': '\u00b0C',   # ℃ → °C
    # Windows-1252 "mojibake": bytes 0x80–0x9F stored as raw Unicode code points
    '\x96': '-',    # U+0096 (byte 0x96 in Win-1252 = en dash) → hyphen
    '\x97': '--',   # U+0097 (byte 0x97 in Win-1252 = em dash) → double hyphen
    '\x91': "'",    # U+0091 = left single quote → apostrophe
    '\x92': "'",    # U+0092 = right single quote → apostrophe
    '\x93': '"',    # U+0093 = left double quote → straight quote
    '\x94': '"',    # U+0094 = right double quote → straight quote
    '\x95': '\u2022',  # U+0095 = bullet → standard bullet (in Helvetica)
    '\x85': '...',  # U+0085 = ellipsis control char → three dots
}
# Keep old name as alias for test_pdf_to_json.py compatibility
_FRACTION_MAP = {k: v for k, v in _CHAR_MAP.items() if '\u2150' <= k <= '\u215e'}

def _safe(text):
    """Replace characters unsupported by Helvetica with ASCII/Latin-1 equivalents."""
    if not text:
        return text
    for ch, rep in _CHAR_MAP.items():
        if ch in text:
            text = text.replace(ch, rep)
    return text

# Page margins: left/right restored to 0.5in; top/bottom increased by 50% (0.25in -> 0.375in)
# Increase side margins by 30% (0.5in -> 0.65in)
LEFT_RIGHT_MARGIN = 0.65 * inch
PAGE_TOP_MARGIN = 0.375 * inch
PAGE_BOTTOM_MARGIN = 0.375 * inch
# Fraction of each column's available space to actually use for content
SECTION_FILL = 0.9
# ReportLab's SimpleDocTemplate Frame has 6pt internal padding on each side.
# Available height inside a frame = (page height - doc margins - 2 * FRAME_PADDING).
FRAME_PADDING = 6

def get_recipe_styles():
    """Return custom styles for recipe formatting"""
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'RecipeTitle',
        parent=styles['Heading1'],
        fontSize=20,
        textColor='#2C3E50',
        spaceAfter=6,
        alignment=TA_LEFT,
        leftIndent=0
    )

    info_style = ParagraphStyle(
        'RecipeInfo',
        parent=styles['Normal'],
        fontSize=10,
        textColor='#555555',
        spaceAfter=3,
        alignment=TA_LEFT,
        leftIndent=0
    )

    # Source style: slightly reduced spacing from the info line, and smaller space after
    source_style = ParagraphStyle(
        'RecipeSource',
        parent=styles['Normal'],
        fontSize=10,
        textColor='#555555',
        spaceBefore=6,
        spaceAfter=3,
        alignment=TA_LEFT,
        leftIndent=0
    )

    section_heading_style = ParagraphStyle(
        'SectionHeading',
        parent=styles['Heading2'],
        fontSize=12,
        textColor='#34495E',
        spaceAfter=4,
        spaceBefore=5,
        alignment=TA_CENTER
    )

    # Ingredients: left aligned, single-spaced (tight leading), small spacing after each line
    ingredient_style = ParagraphStyle(
        'IngredientText',
        parent=styles['BodyText'],
        fontSize=10,
        leading=9,
        spaceAfter=0,
        alignment=TA_LEFT,
        # leftIndent=0.05*inch,
        rightIndent=0.1*inch
    )

    # Directions: similar tight leading to keep content compact
    direction_style = ParagraphStyle(
        'DirectionText',
        parent=styles['BodyText'],
        fontSize=10,
        leading=12,
        spaceAfter=2,
        alignment=TA_LEFT,
        leftIndent=0.15*inch
    )

    return {
        'title': title_style,
        'info': info_style,
        'section_heading': section_heading_style,
        'ingredient': ingredient_style,
        'direction': direction_style
    }

def format_recipe_first_page(recipe_data, styles):
    """
    Format the first page with recipe info, ingredients, and directions in two columns.
    Both columns are measured independently using actual Table.wrap() binary search so
    the rendered table is guaranteed to fit within the frame.

    Returns a 4-tuple:
        (elements, overflow_ingredients, overflow_right, overflow_directions_count)

        overflow_ingredients      – Paragraph objects for the left (ingredients) overflow
        overflow_right            – Paragraph objects for the right (directions/notes) overflow
        overflow_directions_count – integer count of direction steps in overflow_right
    """
    elements = []

    # ── Title ────────────────────────────────────────────────────────────────
    recipe_name = _safe(recipe_data.get('name', 'Recipe'))
    title_para = Paragraph(recipe_name, styles['title'])
    elements.append(title_para)

    # ── Recipe info line ─────────────────────────────────────────────────────
    info_parts = []
    if recipe_data.get('servings'):
        info_parts.append(f"<b>Servings:</b> {_safe(recipe_data['servings'])}")
    if recipe_data.get('prep_time'):
        info_parts.append(f"<b>Prep:</b> {_safe(recipe_data['prep_time'])}")
    if recipe_data.get('cook_time'):
        info_parts.append(f"<b>Cook:</b> {_safe(recipe_data['cook_time'])}")
    if recipe_data.get('total_time'):
        info_parts.append(f"<b>Total:</b> {_safe(recipe_data['total_time'])}")

    info_para = None
    if info_parts:
        info_para = Paragraph(" | ".join(info_parts), styles['info'])
        elements.append(info_para)

    source = recipe_data.get('source', '')
    source_url = recipe_data.get('source_url', '')
    source_para = None
    if source or source_url:
        source_text = _safe(source) if source else "Source"
        if source_url:
            source_text = f"<u>{source_text}</u>"
        source_para = Paragraph(f"<b>Source:</b> {source_text}", styles['info'])
        elements.append(source_para)

    spacer_height = 0.2 * inch
    elements.append(Spacer(1, spacer_height))

    # ── Column widths ────────────────────────────────────────────────────────
    usable_width = letter[0] - 2 * LEFT_RIGHT_MARGIN
    left_col_width = usable_width * 0.30 * SECTION_FILL
    right_col_width = usable_width * 0.70 * SECTION_FILL

    # ── Build ingredient Paragraph objects ───────────────────────────────────
    left_col_heading = Paragraph("Ingredients", styles['section_heading'])
    ingredient_paragraphs = []
    ingredients = recipe_data.get('ingredients', '')
    if ingredients:
        for line in ingredients.strip().split('\n'):
            if line.strip():
                ingredient_paragraphs.append(
                    Paragraph(f"• {_safe(line.strip())}", styles['ingredient'])
                )

    # ── Build direction and notes Paragraph objects ──────────────────────────
    right_col_heading = Paragraph("Directions", styles['section_heading'])
    direction_paragraphs = []
    directions = recipe_data.get('directions', '')
    if directions:
        for i, step in enumerate(directions.split('\n\n'), 1):
            if step.strip():
                direction_paragraphs.append(
                    Paragraph(f"<b>Step {i}:</b> {_safe(step.strip())}", styles['direction'])
                )

    notes_paragraphs = []
    notes = recipe_data.get('notes', '')
    if notes:
        notes_paragraphs.append(Paragraph("Notes", styles['section_heading']))
        notes_paragraphs.append(Paragraph(_safe(notes), styles['direction']))

    all_right_paragraphs = direction_paragraphs + notes_paragraphs

    # ── Accurately measure all pre-table header elements ─────────────────────
    # Paragraph.wrap() returns text height only; spaceAfter is rendered separately.
    # We must include both to know the true height consumed before the table.
    header_height = 0
    try:
        _, h = title_para.wrap(usable_width, letter[1])
        header_height += h + styles['title'].spaceAfter
        if info_para is not None:
            _, h = info_para.wrap(usable_width, letter[1])
            header_height += h + styles['info'].spaceAfter
        if source_para is not None:
            _, h = source_para.wrap(usable_width, letter[1])
            header_height += h + styles['info'].spaceAfter
    except Exception:
        header_height = styles['title'].fontSize + styles['info'].fontSize * 2 + 20
    header_height += spacer_height
    available_height = letter[1] - PAGE_TOP_MARGIN - PAGE_BOTTOM_MARGIN - 2 * FRAME_PADDING - header_height

    # ── Reserve space for nutritional info so it always fits on page 1 ────────
    nutritional_info = recipe_data.get('nutritional_info', '')
    if nutritional_info:
        nutr_lines = [ln.strip() for ln in nutritional_info.strip().splitlines() if ln.strip()]
        nutr_single = ' | '.join(nutr_lines)
        nutr_preview = Paragraph(f"<b>Nutritional Information:</b> {nutr_single}", styles['ingredient'])
        try:
            _, nutr_h = nutr_preview.wrap(usable_width, letter[1])
        except Exception:
            nutr_h = styles['ingredient'].fontSize * 1.5
        available_height -= nutr_h + 0.08 * inch  # paragraph height + spacer before it

    # ── Table helpers ─────────────────────────────────────────────────────────
    def _make_table(lce, rce):
        t = Table([[lce, rce]], colWidths=[left_col_width, right_col_width])
        t.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ('LINEBEFORE', (1, 0), (1, 0), 1, colors.grey),
        ]))
        return t

    def _col_height(elems, is_left):
        """Measure a column's rendered height via an actual Table.wrap() call.
        The other cell is a minimal Spacer so only the target column drives the height."""
        if is_left:
            t = _make_table(elems, [Spacer(1, 1)])
        else:
            t = _make_table([Spacer(1, 1)], elems)
        _, h = t.wrap(usable_width, available_height * 10)
        return h

    def _binary_search_fit(heading, items, is_left):
        """Return the maximum number of items that, with heading prepended,
        fit within available_height in the given column.
        Uses actual Table.wrap() for accurate measurement."""
        if not items:
            return 0
        if _col_height([heading] + items[:1], is_left) > available_height:
            return 0
        lo, hi = 1, len(items)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if _col_height([heading] + items[:mid], is_left) <= available_height:
                lo = mid
            else:
                hi = mid - 1
        return lo

    # ── Fit left column (ingredients) ────────────────────────────────────────
    fit_left = _binary_search_fit(left_col_heading, ingredient_paragraphs, is_left=True)
    left_col_elements = [left_col_heading] + ingredient_paragraphs[:fit_left]
    overflow_ingredients = ingredient_paragraphs[fit_left:]

    # ── Fit right column (directions + notes) ────────────────────────────────
    fit_right = _binary_search_fit(right_col_heading, all_right_paragraphs, is_left=False)
    right_col_fit = all_right_paragraphs[:fit_right]
    right_col_overflow = all_right_paragraphs[fit_right:]
    # Number of direction-step Paragraphs at the start of right_col_overflow
    overflow_directions_count = max(0, len(direction_paragraphs) - fit_right)
    right_col_elements = [right_col_heading] + right_col_fit

    # ── Build and append the two-column table ────────────────────────────────
    recipe_table = _make_table(left_col_elements, right_col_elements)
    elements.append(recipe_table)

    # ── Nutritional information (below table, single pipe-joined line) ────────
    nutritional_info = recipe_data.get('nutritional_info', '')
    if nutritional_info:
        lines = [ln.strip() for ln in nutritional_info.strip().splitlines() if ln.strip()]
        single_line = _safe(' | '.join(lines))
        elements.append(Spacer(1, 0.08 * inch))
        elements.append(Paragraph(
            f"<b>Nutritional Information:</b> {single_line}", styles['ingredient']
        ))

    return elements, overflow_ingredients, right_col_overflow, overflow_directions_count

def format_recipe_second_page(recipe_data, image_path, styles,
                              overflow_ingredients=None,
                              overflow_right=None,
                              overflow_directions_count=0):
    """
    Format page 2 (and any additional pages) with overflow content from page 1
    in a matching two-column layout, followed by the recipe image.

    Both columns are measured independently using actual Table.wrap() binary search
    so no table cell can exceed the frame height.

    overflow_ingredients      – Paragraph objects for the left (ingredients) overflow
    overflow_right            – Paragraph objects for the right (directions/notes) overflow
    overflow_directions_count – How many Paragraphs at the start of overflow_right are
                                direction steps (remainder are notes, which carry their
                                own 'Notes' heading).  Used to decide when to add a
                                'Directions (continued)' heading on overflow pages.
    """
    elements = []
    elements.append(PageBreak())

    left_remaining = list(overflow_ingredients or [])
    right_remaining = list(overflow_right or [])
    dirs_remaining = overflow_directions_count

    usable_width = letter[0] - 2 * LEFT_RIGHT_MARGIN
    left_col_width = usable_width * 0.30 * SECTION_FILL
    right_col_width = usable_width * 0.70 * SECTION_FILL
    # Usable height on overflow pages: page height minus document margins and
    # the 6pt top + 6pt bottom internal padding that ReportLab's Frame adds.
    available_height = letter[1] - PAGE_TOP_MARGIN - PAGE_BOTTOM_MARGIN - 2 * FRAME_PADDING

    def _make_overflow_table(lce, rce):
        t = Table([[lce, rce]], colWidths=[left_col_width, right_col_width])
        t.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ('LINEBEFORE', (1, 0), (1, 0), 1, colors.grey),
        ]))
        return t

    def _col_height(elems, is_left):
        """Measure column height via actual Table.wrap(). Other cell is a Spacer
        so only the target column contributes to the measured height."""
        if is_left:
            t = _make_overflow_table(elems, [Spacer(1, 1)])
        else:
            t = _make_overflow_table([Spacer(1, 1)], elems)
        _, h = t.wrap(usable_width, available_height * 10)
        return h

    def _binary_search_fit(prefix, items, is_left):
        """Return the maximum number of items from `items` such that
        [*prefix, *items[:count]] fits within available_height in the column.
        Always returns at least 1 if items is non-empty (to guarantee progress)."""
        if not items:
            return 0
        if _col_height(prefix + items[:1], is_left) > available_height:
            # Single item already overflows; force it through to avoid infinite loop
            return 1
        lo, hi = 1, len(items)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if _col_height(prefix + items[:mid], is_left) <= available_height:
                lo = mid
            else:
                hi = mid - 1
        return lo

    # ── Paginate overflow across as many pages as needed ─────────────────────
    while left_remaining or right_remaining:

        # ── Left column: max ingredients that fit this page ───────────────────
        lce_page = []
        next_left = []
        if left_remaining:
            lh = Paragraph("Ingredients (continued)", styles['section_heading'])
            fit = _binary_search_fit([lh], left_remaining, is_left=True)
            lce_page = [lh] + left_remaining[:fit]
            next_left = left_remaining[fit:]

        # ── Right column: max direction/notes paragraphs that fit this page ───
        rce_page = []
        next_right = []
        next_dirs = dirs_remaining
        if right_remaining:
            if dirs_remaining > 0:
                rh = Paragraph("Directions (continued)", styles['section_heading'])
                fit = _binary_search_fit([rh], right_remaining, is_left=False)
                rce_page = [rh] + right_remaining[:fit]
            else:
                # Notes: the "Notes" heading paragraph is already the first item
                # in right_remaining; no extra heading to prepend.
                fit = _binary_search_fit([], right_remaining, is_left=False)
                rce_page = right_remaining[:fit]
            next_right = right_remaining[fit:]
            next_dirs = max(0, dirs_remaining - fit)

        # Build table (ReportLab requires both cells to be non-empty)
        lce = lce_page if lce_page else [Spacer(1, 1)]
        rce = rce_page if rce_page else [Spacer(1, 1)]
        table = _make_overflow_table(lce, rce)

        elements.append(table)
        elements.append(Spacer(1, 0.15 * inch))

        left_remaining = next_left
        right_remaining = next_right
        dirs_remaining = next_dirs

        if left_remaining or right_remaining:
            elements.append(PageBreak())

    # ── Recipe image ─────────────────────────────────────────────────────────
    if image_path and os.path.exists(image_path):
        try:
            elements.append(Spacer(1, 0.3 * inch))
            img = Image(image_path, width=5 * inch, height=3 * inch)
            elements.append(img)
            elements.append(Spacer(1, 0.2 * inch))
        except Exception as e:
            print(f"  Error adding image: {e}")

    return elements
