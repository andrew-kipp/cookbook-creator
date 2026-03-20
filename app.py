"""
Recipe and Cookbook Creator
GUI application for converting and managing recipe files.
"""

import json
import os
import queue
import sys
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
from tkinter import ttk


# Drag-and-drop support (optional)
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    _DND_AVAILABLE = True
except ImportError:
    _DND_AVAILABLE = False

# ── Constants ─────────────────────────────────────────────────────────────────
IMAGES_SUBDIR = "Recipe Images"
IMPORT_DIR_NAME = "Paprika Recipes to Import"
COOKBOOK_FILENAME = "Cookbook.pdf"
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}
SETTINGS_FILE = Path.home() / ".cookbook_creator_settings.json"

ACCENT   = "#2C3E50"
BTN_BG   = "#3498DB"
BTN_FG   = "white"
BTN_ACT  = "#2980B9"
SEP_CLR  = "#BDC3C7"
LOG_BG   = "#F9F9F9"
LOG_FG   = "#2C3E50"
RADIO_SEL = "#2980B9"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fix_stdout():
    """Reconfigure stdout to UTF-8 on Windows if needed."""
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


# ── Category ordering for cookbook ────────────────────────────────────────────
CATEGORY_ORDER = [
    "Appetizers/Starters",
    "Mains",
    "Sides",
    "Desserts",
    "Breads",
    "Sauces/Toppings",
    "Drinks",
]
_TOC_MISC_CHILDREN = {"Breads", "Sauces/Toppings", "Drinks"}


# ── Cookbook generator ────────────────────────────────────────────────────────

def create_cookbook(recipes_dir, output_path, filter_mode="all", image_mode="none", progress_cb=None):
    """
    Generate a structured multi-page PDF cookbook with cover page, table of contents,
    per-category sections, and an alphabetical index.

    recipes_dir  : folder containing .json recipe files (and a Recipe Images subfolder)
    output_path  : full path for the output PDF
    filter_mode  : "all" | "4_and_5_stars" | "5_stars"
    image_mode   : "grouped" | "adjacent" | "none"
    progress_cb  : optional callable(str)
    """
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import (
        SimpleDocTemplate, PageBreak, Spacer, Paragraph, Table, TableStyle, Image
    )
    from RecipeFormatter import (
        get_recipe_styles, format_recipe_first_page, format_recipe_second_page,
        LEFT_RIGHT_MARGIN, PAGE_TOP_MARGIN, PAGE_BOTTOM_MARGIN, _safe,
    )

    def log(msg):
        if progress_cb:
            progress_cb(msg)
        else:
            print(msg)

    import re as _re

    recipes_dir = Path(recipes_dir)
    images_dir  = recipes_dir / IMAGES_SUBDIR
    page_w, page_h = letter
    usable_w = page_w - 2 * LEFT_RIGHT_MARGIN

    # ── Filter helpers ────────────────────────────────────────────────────────
    def _base_stem(stem):
        return _re.sub(r'\s*\(\d+\s*Stars?\)\s*$', '', stem, flags=_re.IGNORECASE).strip()

    def _rating_from_pdf(stem):
        m = _re.search(r'\((\d+)\s*Stars?\)\s*$', stem, _re.IGNORECASE)
        return int(m.group(1)) if m else 0

    def _passes_filter(rating):
        r = int(rating or 0)
        if filter_mode == "5_stars":
            return r >= 5
        if filter_mode == "4_and_5_stars":
            return r >= 4
        return True

    # ── Collect and filter recipes ────────────────────────────────────────────
    json_files = sorted(recipes_dir.glob("*.json"))
    json_stems = {jf.stem for jf in json_files}
    log(f"Found {len(json_files)} JSON file(s)")

    pdf_only = sorted(
        pdf for pdf in recipes_dir.glob("*.pdf")
        if _base_stem(pdf.stem) not in json_stems
    )
    if pdf_only:
        log(f"Found {len(pdf_only)} PDF-only recipe(s)")

    filtered = []
    for jf in json_files:
        try:
            with open(jf, encoding='utf-8') as f:
                data = json.load(f)
            if not _passes_filter(data.get('rating', 0)):
                continue
            filtered.append((jf, data))
        except Exception as e:
            log(f"  Warning: could not read {jf.name}: {e}")

    for pdf in pdf_only:
        if not _passes_filter(_rating_from_pdf(pdf.stem)):
            continue
        try:
            from PDFToJSONRecipe import pdf_to_json
            data = pdf_to_json(str(pdf))
            filtered.append((pdf, data))
        except Exception as e:
            log(f"  Warning: could not extract {pdf.name}: {e}")

    filtered.sort(key=lambda x: x[0].stem.lower())
    log(f"Recipes after filter '{filter_mode}': {len(filtered)}")
    if not filtered:
        log("No recipes match the selected filter. Cookbook not created.")
        return

    # ── Build category index ──────────────────────────────────────────────────
    all_cat_map = {}   # cat -> [(jf, data), ...]
    uncategorized = []
    for jf, data in filtered:
        cats = data.get('categories', [])
        if isinstance(cats, str):
            cats = [c.strip() for c in cats.split(',') if c.strip()]
        if not cats:
            uncategorized.append((jf, data))
            continue
        for cat in cats:
            if cat:
                all_cat_map.setdefault(cat, []).append((jf, data))

    # recipe_index.json: all categories → sorted recipe name lists
    recipe_index = {
        cat: sorted(set(d.get('name', jf.stem) for jf, d in items))
        for cat, items in sorted(all_cat_map.items())
    }
    if uncategorized:
        recipe_index['Uncategorized'] = sorted(
            set(d.get('name', jf.stem) for jf, d in uncategorized)
        )
    with open(recipes_dir / "recipe_index.json", 'w', encoding='utf-8') as f:
        json.dump(recipe_index, f, indent=2, ensure_ascii=False)
    log("Recipe index saved: recipe_index.json")

    # ── Per-category recipe lists, deduplicated (first occurrence wins) ───────
    seen_names = set()
    cat_recipe_lists = {}
    for cat in CATEGORY_ORDER:
        deduped = []
        for jf, data in all_cat_map.get(cat, []):
            name = data.get('name', jf.stem)
            if name not in seen_names:
                seen_names.add(name)
                deduped.append((jf, data))
        if deduped:
            cat_recipe_lists[cat] = deduped

    active_cats = [c for c in CATEGORY_ORDER if c in cat_recipe_lists]
    log(f"Categories: {active_cats}")

    # ── Styles ────────────────────────────────────────────────────────────────
    recipe_styles = get_recipe_styles()
    base_styles   = getSampleStyleSheet()

    def _ps(name, **kw):
        return ParagraphStyle(name, parent=base_styles['Normal'], **kw)

    cover_title_style   = _ps('CoverTitle', fontSize=36, fontName='Helvetica-Bold',
                               textColor=colors.HexColor('#2C3E50'),
                               alignment=TA_CENTER, spaceAfter=18)
    cover_sub_style     = _ps('CoverSub', fontSize=18,
                               textColor=colors.HexColor('#7F8C8D'),
                               alignment=TA_CENTER, spaceAfter=8)
    toc_heading_style   = _ps('TOCHeading', fontSize=24, fontName='Helvetica-Bold',
                               textColor=colors.HexColor('#2C3E50'),
                               alignment=TA_CENTER, spaceAfter=14)
    toc_cat_style       = _ps('TOCCat', fontSize=13,
                               textColor=colors.HexColor('#2C3E50'),
                               spaceBefore=4, spaceAfter=2)
    toc_cat_pg_style    = _ps('TOCCatPg', fontSize=13,
                               textColor=colors.HexColor('#2C3E50'),
                               alignment=TA_RIGHT, spaceBefore=4, spaceAfter=2)
    toc_sub_style       = _ps('TOCSub', fontSize=11,
                               textColor=colors.HexColor('#555555'),
                               spaceBefore=2, spaceAfter=2,
                               leftIndent=int(0.3 * inch))
    toc_sub_pg_style    = _ps('TOCSubPg', fontSize=11,
                               textColor=colors.HexColor('#555555'),
                               alignment=TA_RIGHT, spaceBefore=2, spaceAfter=2)
    cat_title_style     = _ps('CatTitle', fontSize=28, fontName='Helvetica-Bold',
                               textColor=colors.HexColor('#2C3E50'),
                               alignment=TA_CENTER, spaceAfter=14)
    cat_recipe_style    = _ps('CatRecipe', fontSize=12,
                               textColor=colors.HexColor('#2C3E50'),
                               spaceAfter=3, leftIndent=int(0.2 * inch))
    cat_recipe_pg_style = _ps('CatRecipePg', fontSize=12,
                               textColor=colors.HexColor('#7F8C8D'),
                               alignment=TA_RIGHT)
    idx_heading_style   = _ps('IdxHeading', fontSize=24, fontName='Helvetica-Bold',
                               textColor=colors.HexColor('#2C3E50'),
                               alignment=TA_CENTER, spaceAfter=14)
    idx_cat_style       = _ps('IdxCat', fontSize=12, fontName='Helvetica-Bold',
                               textColor=colors.HexColor('#2C3E50'),
                               spaceBefore=8, spaceAfter=3)
    idx_recipe_style    = _ps('IdxRecipe', fontSize=10,
                               textColor=colors.HexColor('#2C3E50'),
                               spaceAfter=2, leftIndent=int(0.3 * inch))
    img_caption_style   = _ps('ImgCaption', fontSize=7, alignment=TA_CENTER)

    # ── Image lookup ──────────────────────────────────────────────────────────
    include_image = image_mode in ("grouped", "adjacent")

    def _find_image(data):
        if not include_image:
            return None
        recipe_name = data.get('name', '')
        rating      = data.get('rating', '')
        safe = "".join(c for c in recipe_name if c.isalnum() or c in (' ', '_', '-')).strip()
        suffix = f" ({rating} stars)" if rating not in (None, '') else ""
        for ext in ('.jpg', '.jpeg', '.png', '.gif', '.webp'):
            p = images_dir / f"{safe}{suffix}{ext}"
            if p.exists():
                return str(p)
        if images_dir.exists():
            for f in images_dir.iterdir():
                if f.is_file() and f.stem.lower().startswith(safe.lower()):
                    return str(f)
        url = data.get('image_url', '')
        if url:
            try:
                from JSONToPDFRecipe import download_recipe_image
                images_dir.mkdir(parents=True, exist_ok=True)
                dl = download_recipe_image(url, recipe_name, str(images_dir), rating or None)
                if dl:
                    return dl
            except Exception:
                pass
        return None

    # ── Pre-measure recipes: base_pages (overflow check) + total_pages ────────
    log("Pre-measuring recipes...")
    recipe_cache = {}  # id(data) -> {'image': str|None, 'base_pages': int, 'total_pages': int}
    for cat in active_cats:
        for jf, data in cat_recipe_lists[cat]:
            key = id(data)
            if key in recipe_cache:
                continue
            img = _find_image(data)
            try:
                _, oi, orr, _ = format_recipe_first_page(data, recipe_styles)
                has_overflow = bool(oi or orr)
            except Exception:
                has_overflow = False
            base_pages  = 2 if has_overflow else 1
            total_pages = base_pages + (1 if image_mode == "adjacent" and img else 0)
            recipe_cache[key] = {'image': img, 'base_pages': base_pages, 'total_pages': total_pages}

    # ── Pass 1: simulate page layout to get page numbers for TOC ─────────────
    # Pre-section pages: cover(1) blank(2) TOC(3) blank(4) → categories start at 5
    p = 5

    def _p1_ensure_odd():
        nonlocal p
        if p % 2 == 0:
            p += 1

    def _p1_ensure_even():
        nonlocal p
        if p % 2 != 0:
            p += 1

    cat_start_pages    = {}  # cat -> page number
    recipe_start_pages = {}  # id(data) -> page number

    for cat in active_cats:
        _p1_ensure_odd()
        cat_start_pages[cat] = p
        p += 1  # advance past category title page (via explicit PageBreak)

        if image_mode == "grouped":
            n_imgs = sum(1 for _, d in cat_recipe_lists[cat] if recipe_cache[id(d)]['image'])
            if n_imgs:
                p += (n_imgs + 11) // 12  # each image grid page has explicit PageBreak

        # Reorder: when a 2-page recipe would land on an odd page, swap it with
        # the next recipe (if the next is 1-page) to avoid inserting a blank page.
        items = list(cat_recipe_lists[cat])
        i = 0
        while i < len(items):
            info = recipe_cache[id(items[i][1])]
            bp  = info['base_pages']
            img = info['image']
            tp  = info['total_pages']
            if tp == 2 and p % 2 != 0:
                # Try swapping with the next recipe if it is a 1-page recipe
                if i + 1 < len(items) and recipe_cache[id(items[i + 1][1])]['total_pages'] == 1:
                    items[i], items[i + 1] = items[i + 1], items[i]
                    info = recipe_cache[id(items[i][1])]
                    bp, img, tp = info['base_pages'], info['image'], info['total_pages']
                else:
                    p += 1  # fallback: blank page when no swappable neighbour
            recipe_start_pages[id(items[i][1])] = p
            is_last = (i == len(items) - 1)
            # Page advances for this recipe slot:
            #   (bp-1) = PageBreak from format_recipe_second_page when overflow
            #   +1     = explicit _pb() for adjacent image page (if applicable)
            #   +1     = explicit _pb() separator between recipes (if not last)
            advances = (bp - 1) + (1 if image_mode == "adjacent" and img else 0) + (0 if is_last else 1)
            p += advances
            i += 1
        cat_recipe_lists[cat] = items  # store reordered list for pass 2

        p += 1  # blank page after last recipe in category (explicit _pb())

    _p1_ensure_odd()
    index_start_page = p
    log(f"Index will start on page {index_start_page}")

    # ── TOC row builder ───────────────────────────────────────────────────────
    def _toc_row(label, pg_num, lbl_style, pg_style, left_indent=0):
        lbl_para = Paragraph(label, lbl_style)
        pg_para  = Paragraph(str(pg_num), pg_style)
        t = Table([[lbl_para, pg_para]],
                  colWidths=[usable_w - 0.6 * inch, 0.6 * inch])
        t.setStyle(TableStyle([
            ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING',   (0, 0), (-1, -1), left_indent),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 0),
            ('TOPPADDING',    (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        return t

    # ── Pass 2: build story ───────────────────────────────────────────────────
    story = []
    cur_page = [1]  # tracks which page we are currently writing content to

    def _pb():
        """Add an explicit PageBreak and advance the page counter."""
        story.append(PageBreak())
        cur_page[0] += 1

    def _ensure_odd():
        if cur_page[0] % 2 == 0:
            _pb()

    def _ensure_even():
        if cur_page[0] % 2 != 0:
            _pb()

    # ── Cover page (page 1) ───────────────────────────────────────────────────
    story.append(Spacer(1, page_h * 0.30))
    story.append(Paragraph("Family Recipes", cover_title_style))
    story.append(Spacer(1, 0.5 * inch))
    story.append(Paragraph("From the Kipp/Paul Household", cover_sub_style))

    # ── Blank page (page 2) ───────────────────────────────────────────────────
    _pb()

    # ── Table of Contents (page 3) ────────────────────────────────────────────
    _pb()
    story.append(Paragraph("Table of Contents", toc_heading_style))
    story.append(Spacer(1, 0.15 * inch))

    non_misc_cats  = [c for c in active_cats if c not in _TOC_MISC_CHILDREN]
    misc_cats_active = [c for c in ["Breads", "Sauces/Toppings", "Drinks"] if c in cat_start_pages]

    for cat in non_misc_cats:
        story.append(_toc_row(cat, cat_start_pages[cat], toc_cat_style, toc_cat_pg_style))
    if misc_cats_active:
        story.append(Paragraph("Misc", _ps('TOCMisc', fontSize=13,
                                           textColor=colors.HexColor('#2C3E50'),
                                           spaceBefore=2, spaceAfter=2)))
        for mc in misc_cats_active:
            story.append(_toc_row(mc, cat_start_pages[mc],
                                  toc_sub_style, toc_sub_pg_style,
                                  left_indent=12))
    story.append(_toc_row("Index", index_start_page, toc_cat_style, toc_cat_pg_style))

    # ── Blank page (page 4) ───────────────────────────────────────────────────
    _pb()

    # ── Category sections ─────────────────────────────────────────────────────
    for cat in active_cats:
        items = cat_recipe_lists[cat]

        # Category title page must be on an odd page
        _ensure_odd()

        # Category title
        story.append(Spacer(1, page_h * 0.20))
        story.append(Paragraph(_safe(cat), cat_title_style))
        story.append(Spacer(1, 0.2 * inch))

        # List every recipe with its page number
        for jf, data in items:
            rname = data.get('name', _base_stem(jf.stem))
            rpage = recipe_start_pages.get(id(data), '?')
            row = Table(
                [[Paragraph(_safe(rname), cat_recipe_style),
                  Paragraph(str(rpage), cat_recipe_pg_style)]],
                colWidths=[usable_w - 0.5 * inch, 0.5 * inch]
            )
            row.setStyle(TableStyle([
                ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING',   (0, 0), (-1, -1), 0),
                ('RIGHTPADDING',  (0, 0), (-1, -1), 0),
                ('TOPPADDING',    (0, 0), (-1, -1), 1),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
            ]))
            story.append(row)

        _pb()  # end category title page → advances to next page

        # Grouped images: 3-column × 4-row grid pages after category title
        if image_mode == "grouped":
            imgs_data = [
                (data.get('name', jf.stem), recipe_cache[id(data)]['image'])
                for jf, data in items
                if recipe_cache[id(data)]['image']
            ]
            if imgs_data:
                COLS, ROWS = 3, 4
                per_page   = COLS * ROWS
                img_w = (usable_w - (COLS - 1) * 0.1 * inch) / COLS
                img_h = img_w * 0.75
                for pi in range(0, len(imgs_data), per_page):
                    batch = list(imgs_data[pi:pi + per_page])
                    while len(batch) % COLS:
                        batch.append(('', None))
                    tbl_rows = []
                    for ri in range(0, len(batch), COLS):
                        cell_row = []
                        for name, ipath in batch[ri:ri + COLS]:
                            if ipath and os.path.exists(ipath):
                                try:
                                    cell_row.append([
                                        Image(ipath, width=img_w, height=img_h),
                                        Paragraph(_safe(name), img_caption_style),
                                    ])
                                except Exception:
                                    cell_row.append([Paragraph(_safe(name), img_caption_style)])
                            else:
                                cell_row.append([Spacer(img_w, img_h)])
                        tbl_rows.append(cell_row)
                    tbl = Table(tbl_rows, colWidths=[img_w] * COLS)
                    tbl.setStyle(TableStyle([
                        ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
                        ('ALIGN',         (0, 0), (-1, -1), 'CENTER'),
                        ('LEFTPADDING',   (0, 0), (-1, -1), 4),
                        ('RIGHTPADDING',  (0, 0), (-1, -1), 4),
                        ('TOPPADDING',    (0, 0), (-1, -1), 4),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                    ]))
                    story.append(tbl)
                    _pb()

        # Recipes
        for idx_r, (jf, data) in enumerate(items):
            info       = recipe_cache[id(data)]
            bp         = info['base_pages']
            image_path = info['image']
            tp         = info['total_pages']
            recipe_name = data.get('name', _base_stem(jf.stem))
            log(f"  Adding: {recipe_name}")

            # 2-page recipes start on even pages; the list was pre-reordered in
            # pass 1 to avoid blank pages via swaps — this is a safety fallback.
            if tp == 2:
                _ensure_even()

            # Render recipe page 1
            first_elems, oi, orr, odirs = format_recipe_first_page(data, recipe_styles)
            story.extend(first_elems)

            # Render page 2 if there is overflow
            if bp == 2:
                second_elems = format_recipe_second_page(
                    data, None, recipe_styles, oi, orr, odirs, include_image=False,
                )
                story.extend(second_elems)
                # format_recipe_second_page always prepends a PageBreak
                cur_page[0] += 1

            # Adjacent image: its own page after the recipe
            if image_mode == "adjacent" and image_path:
                _pb()
                try:
                    from PIL import Image as PILImage
                    with PILImage.open(image_path) as pil_img:
                        iw, ih = pil_img.size
                    max_w = usable_w
                    max_h = page_h - PAGE_TOP_MARGIN - PAGE_BOTTOM_MARGIN - 0.5 * inch
                    scale = min(max_w / iw, max_h / ih)
                    story.append(Spacer(1, max(0, (max_h - ih * scale) / 2)))
                    story.append(Image(image_path, width=iw * scale, height=ih * scale))
                except Exception:
                    story.append(Image(image_path, width=usable_w, height=4 * inch))

            # Separator between recipes (not after last)
            if idx_r < len(items) - 1:
                _pb()

        # Blank separator page after the last recipe in this category
        _pb()

    # ── Index ─────────────────────────────────────────────────────────────────
    # Build recipe-name → start-page lookup from the (reordered) category lists
    name_to_page = {}
    for cat in active_cats:
        for jf, data in cat_recipe_lists[cat]:
            name = data.get('name', _base_stem(jf.stem))
            if name not in name_to_page and id(data) in recipe_start_pages:
                name_to_page[name] = recipe_start_pages[id(data)]

    idx_recipe_pg_style = _ps('IdxRecipePg', fontSize=10,
                               textColor=colors.HexColor('#7F8C8D'),
                               alignment=TA_RIGHT, spaceAfter=2)

    def _idx_recipe_row(name, page_num):
        name_para = Paragraph(f"• {_safe(name)}", idx_recipe_style)
        pg_text   = str(page_num) if page_num is not None else ""
        pg_para   = Paragraph(pg_text, idx_recipe_pg_style)
        t = Table([[name_para, pg_para]],
                  colWidths=[usable_w - 0.5 * inch, 0.5 * inch])
        t.setStyle(TableStyle([
            ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING',   (0, 0), (-1, -1), 0),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 0),
            ('TOPPADDING',    (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))
        return t

    _ensure_odd()
    story.append(Paragraph("Index", idx_heading_style))
    story.append(Spacer(1, 0.15 * inch))
    for cat in sorted(recipe_index.keys()):
        story.append(Paragraph(_safe(cat), idx_cat_style))
        for rname in sorted(recipe_index[cat]):
            story.append(_idx_recipe_row(rname, name_to_page.get(rname)))

    # ── Build PDF ─────────────────────────────────────────────────────────────
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        leftMargin=LEFT_RIGHT_MARGIN,
        rightMargin=LEFT_RIGHT_MARGIN,
        topMargin=PAGE_TOP_MARGIN,
        bottomMargin=PAGE_BOTTOM_MARGIN,
    )
    def _draw_page_number(canvas, doc):
        """Draw the page number in the bottom-right margin of every page."""
        canvas.saveState()
        canvas.setFont('Helvetica', 9)
        canvas.setFillColorRGB(0.49, 0.53, 0.55)  # #7F8C8D
        canvas.drawRightString(
            page_w - LEFT_RIGHT_MARGIN,
            PAGE_BOTTOM_MARGIN * 0.45,
            str(doc.page),
        )
        canvas.restoreState()

    doc.build(story, onFirstPage=_draw_page_number, onLaterPages=_draw_page_number)
    log(f"Cookbook saved: {output_path}")


# ── Main Application ──────────────────────────────────────────────────────────

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Recipe and Cookbook Creator")
        self.root.resizable(True, True)
        self.root.minsize(600, 700)

        self._files = []          # list of file paths added by user
        self._busy = False        # True while a background operation runs
        self._log_queue = queue.Queue()
        self._settings = self._load_settings()

        self._build_ui()
        self._poll_log_queue()

    # ── UI Construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        root = self.root
        root.configure(bg="white")

        # ── Title area ──────────────────────────────────────────────────────
        title_frame = tk.Frame(root, bg=ACCENT, pady=12)
        title_frame.pack(fill=tk.X)
        tk.Label(title_frame, text="Recipe and Cookbook Creator",
                 font=("Helvetica", 16, "bold"), fg="white", bg=ACCENT).pack()
        tk.Label(title_frame,
                 text="For use with individual recipe screenshots and Paprika Recipe Manager 3 recipe files",
                 font=("Helvetica", 9), fg="#BDC3C7", bg=ACCENT).pack()

        # ── Main scrollable content ──────────────────────────────────────────
        outer = tk.Frame(root, bg="white")
        outer.pack(fill=tk.BOTH, expand=True, padx=16, pady=10)

        # ── Files section ────────────────────────────────────────────────────
        self._section_label(outer, "FILES")

        dnd_frame = tk.Frame(outer, bg="#EBF5FB", relief=tk.GROOVE, bd=2, height=80)
        dnd_frame.pack(fill=tk.X, pady=(0, 4))
        dnd_frame.pack_propagate(False)
        dnd_lbl = tk.Label(dnd_frame,
                           text="Drag & drop files here\n"
                                "(.paprikarecipes, .paprikarecipe, .pdf, .jpg, .png, ...)",
                           font=("Helvetica", 9), bg="#EBF5FB", fg="#5D6D7E", justify=tk.CENTER)
        dnd_lbl.pack(expand=True)

        if _DND_AVAILABLE:
            dnd_frame.drop_target_register(DND_FILES)
            dnd_frame.dnd_bind('<<Drop>>', self._on_dnd_drop)
            dnd_lbl.drop_target_register(DND_FILES)
            dnd_lbl.dnd_bind('<<Drop>>', self._on_dnd_drop)

        btn_row = tk.Frame(outer, bg="white")
        btn_row.pack(fill=tk.X, pady=(0, 4))
        self._btn(btn_row, "Browse Files...", self._browse_files).pack(side=tk.LEFT, padx=(0, 8))
        self._btn(btn_row, "Clear Files", self._clear_files, secondary=True).pack(side=tk.LEFT)

        list_frame = tk.Frame(outer, bg="white")
        list_frame.pack(fill=tk.X, pady=(0, 8))
        self._file_listbox = tk.Listbox(list_frame, height=5, font=("Helvetica", 8),
                                         selectmode=tk.EXTENDED, bg="#FDFEFE", relief=tk.GROOVE)
        sb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self._file_listbox.yview)
        self._file_listbox.configure(yscrollcommand=sb.set)
        self._file_listbox.pack(side=tk.LEFT, fill=tk.X, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        # ── Output folder ────────────────────────────────────────────────────
        self._hsep(outer)
        self._section_label(outer, "OUTPUT FOLDER")

        folder_row = tk.Frame(outer, bg="white")
        folder_row.pack(fill=tk.X, pady=(0, 8))
        self._folder_var = tk.StringVar()
        tk.Entry(folder_row, textvariable=self._folder_var,
                 font=("Helvetica", 9), relief=tk.GROOVE).pack(side=tk.LEFT, fill=tk.X,
                                                                 expand=True, padx=(0, 8))
        self._btn(folder_row, "Browse Folder...", self._browse_folder).pack(side=tk.LEFT)

        # ── Actions ──────────────────────────────────────────────────────────
        self._hsep(outer)
        self._section_label(outer, "ACTIONS")

        self._action_btns = []
        for lbl1, cmd1, lbl2, cmd2 in [
            ("Create Recipe PDFs from Files",         self._action_create_pdfs_from_files,
             "Create Recipe PDFs from Output Folder", self._action_create_pdfs_from_folder),
            ("Create Paprikarecipes File from Files",         self._action_create_paprikarecipes_from_files,
             "Create Paprikarecipes File from Output Folder", self._action_create_paprikarecipes_from_folder),
        ]:
            btn_row = tk.Frame(outer, bg="white")
            btn_row.pack(fill=tk.X, pady=2)
            b1 = self._btn(btn_row, lbl1, cmd1)
            b1.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))
            b2 = self._btn(btn_row, lbl2, cmd2)
            b2.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 0))
            self._action_btns.extend([b1, b2])

        # ── LLM Extraction ───────────────────────────────────────────────────
        self._hsep(outer)
        self._section_label(outer, "LLM RECIPE EXTRACTION - REQUIRES API KEY")

        llm_cfg_row = tk.Frame(outer, bg="white")
        llm_cfg_row.pack(fill=tk.X, pady=(0, 4))
        self._llm_status_lbl = tk.Label(
            llm_cfg_row, text=self._llm_status_text(),
            font=("Helvetica", 8), bg="white", fg="#5D6D7E", anchor=tk.W
        )
        self._llm_status_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._btn(llm_cfg_row, "Configure LLM...", self._show_llm_settings_dialog,
                  secondary=True).pack(side=tk.RIGHT)

        llm_btn_row = tk.Frame(outer, bg="white")
        llm_btn_row.pack(fill=tk.X, pady=2)
        b_llm1 = self._btn(llm_btn_row, "Extract Recipes from Images (Files)",
                           self._action_extract_images_from_files)
        b_llm1.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))
        b_llm2 = self._btn(llm_btn_row, "Extract Recipes from Images (Folder)",
                           self._action_extract_images_from_folder)
        b_llm2.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 0))
        self._action_btns.extend([b_llm1, b_llm2])

        # ── Cookbook creator ─────────────────────────────────────────────────
        self._hsep(outer)
        self._section_label(outer, "COOKBOOK CREATOR")

        # Filter radio buttons
        filter_row = tk.Frame(outer, bg="white")
        filter_row.pack(fill=tk.X, pady=(4, 2))
        tk.Label(filter_row, text="Filter:", font=("Helvetica", 9, "bold"),
                 bg="white", fg=ACCENT).pack(side=tk.LEFT, padx=(0, 8))
        self._filter_var = tk.StringVar(value="all")
        for label, val in [("All Recipes", "all"), ("4 & 5 Stars", "4_and_5_stars"), ("5 Stars", "5_stars")]:
            tk.Radiobutton(filter_row, text=label, variable=self._filter_var, value=val,
                           font=("Helvetica", 9), bg="white", fg=ACCENT,
                           activebackground="white").pack(side=tk.LEFT, padx=4)

        # Format radio buttons
        format_row = tk.Frame(outer, bg="white")
        format_row.pack(fill=tk.X, pady=(2, 8))
        tk.Label(format_row, text="Format:", font=("Helvetica", 9, "bold"),
                 bg="white", fg=ACCENT).pack(side=tk.LEFT, padx=(0, 8))
        self._format_var = tk.StringVar(value="none")
        for label, val in [("Grouped Images", "grouped"),
                            ("Image Adjacent to Recipe", "adjacent"),
                            ("No Images", "none")]:
            tk.Radiobutton(format_row, text=label, variable=self._format_var, value=val,
                           font=("Helvetica", 9), bg="white", fg=ACCENT,
                           activebackground="white").pack(side=tk.LEFT, padx=4)

        cb_btn = self._btn(outer, "Create Cookbook", self._action_create_cookbook)
        cb_btn.pack(fill=tk.X, pady=2)
        self._action_btns.append(cb_btn)

        # ── Status log ───────────────────────────────────────────────────────
        self._hsep(outer)
        self._section_label(outer, "STATUS LOG")
        self._log_text = scrolledtext.ScrolledText(
            outer, height=10, state=tk.DISABLED,
            font=("Courier", 8), bg=LOG_BG, fg=LOG_FG, relief=tk.GROOVE
        )
        self._log_text.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

    # ── Settings persistence ──────────────────────────────────────────────────

    def _load_settings(self) -> dict:
        try:
            with open(SETTINGS_FILE, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_settings(self, data: dict):
        # Never persist the API key — keep it in-memory only for this session.
        to_save = {k: v for k, v in data.items() if k != 'llm_api_key'}
        try:
            with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(to_save, f, indent=2)
        except Exception as e:
            messagebox.showerror("Settings Error", f"Could not save settings:\n{e}")

    def _llm_status_text(self) -> str:
        provider = self._settings.get('llm_provider', '')
        model    = self._settings.get('llm_model', '')
        has_key  = bool(self._settings.get('llm_api_key', ''))
        if provider and has_key:
            from ImageToPDFRecipe import PROVIDERS
            name = PROVIDERS.get(provider, {}).get('name', provider)
            return f"Provider: {name}  |  Model: {model or 'default'}  |  API key: configured"
        return "No LLM configured — click 'Configure LLM...' to set up"

    # ── Widget helpers ────────────────────────────────────────────────────────

    def _section_label(self, parent, text):
        tk.Label(parent, text=text, font=("Helvetica", 9, "bold"),
                 fg=ACCENT, bg="white").pack(anchor=tk.W, pady=(6, 2))

    def _hsep(self, parent):
        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=6)

    def _btn(self, parent, text, command, secondary=False):
        bg = "#95A5A6" if secondary else BTN_BG
        ab = "#7F8C8D" if secondary else BTN_ACT
        return tk.Button(parent, text=text, command=command,
                         bg=bg, fg=BTN_FG, activebackground=ab, activeforeground=BTN_FG,
                         font=("Helvetica", 9), relief=tk.FLAT, padx=10, pady=5,
                         cursor="hand2")

    # ── File management ───────────────────────────────────────────────────────

    def _on_dnd_drop(self, event):
        # tkinterdnd2 returns paths in braces if they have spaces
        raw = event.data
        paths = []
        # Parse brace-wrapped items (Windows DnD)
        import re
        items = re.findall(r'\{([^}]+)\}|(\S+)', raw)
        for braced, unbraced in items:
            p = braced or unbraced
            if p:
                paths.append(p)
        self._add_files(paths)

    def _browse_files(self):
        paths = filedialog.askopenfilenames(
            title="Select recipe files",
            filetypes=[
                ("All supported files",
                 "*.paprikarecipes *.paprikarecipe *.pdf "
                 "*.jpg *.jpeg *.png *.gif *.webp *.bmp"),
                ("Paprika batch files", "*.paprikarecipes"),
                ("Paprika recipe files", "*.paprikarecipe"),
                ("PDF files", "*.pdf"),
                ("Image files", "*.jpg *.jpeg *.png *.gif *.webp *.bmp"),
                ("All files", "*.*"),
            ]
        )
        self._add_files(list(paths))

    def _add_files(self, paths):
        for p in paths:
            if p not in self._files:
                self._files.append(p)
                self._file_listbox.insert(tk.END, os.path.basename(p))

    def _clear_files(self):
        self._files.clear()
        self._file_listbox.delete(0, tk.END)

    def _browse_folder(self):
        folder = filedialog.askdirectory(title="Select output folder")
        if folder:
            self._folder_var.set(folder)

    # ── Validation ────────────────────────────────────────────────────────────

    def _get_output_folder(self):
        folder = self._folder_var.get().strip()
        if not folder:
            messagebox.showerror("No folder selected",
                                 "Please select an output folder before running.")
            return None
        return folder

    # ── Background task runner ────────────────────────────────────────────────

    def _run_task(self, fn):
        """Run fn() in a background thread; disable buttons while running."""
        if self._busy:
            messagebox.showwarning("Busy", "Another operation is already running.")
            return
        self._busy = True
        for b in self._action_btns:
            b.configure(state=tk.DISABLED)
        self._log("─" * 50)

        def worker():
            try:
                fn()
            except Exception as e:
                self._log(f"ERROR: {e}")
            finally:
                self._log_queue.put(None)  # signal done

        threading.Thread(target=worker, daemon=True).start()

    def _on_task_done(self):
        self._busy = False
        for b in self._action_btns:
            b.configure(state=tk.NORMAL)

    # ── Log helpers ───────────────────────────────────────────────────────────

    def _log(self, msg):
        """Thread-safe log append."""
        self._log_queue.put(str(msg) + "\n")

    def _poll_log_queue(self):
        try:
            while True:
                item = self._log_queue.get_nowait()
                if item is None:
                    self._on_task_done()
                else:
                    self._log_text.configure(state=tk.NORMAL)
                    self._log_text.insert(tk.END, item)
                    self._log_text.see(tk.END)
                    self._log_text.configure(state=tk.DISABLED)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_log_queue)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _action_create_pdfs_from_files(self):
        folder = self._get_output_folder()
        if not folder:
            return

        paprika_files = [f for f in self._files
                         if f.lower().endswith('.paprikarecipes') or f.lower().endswith('.paprikarecipe')]

        if not paprika_files:
            messagebox.showerror("No files",
                                 "Please add .paprikarecipes or .paprikarecipe files first.")
            return

        def task():
            from JSONToPDFRecipe import process_json_to_pdf
            self._log(f"Extracting {len(paprika_files)} Paprika file(s) to: {folder}")
            from PaprikaExtract import extract_paprika_files
            extract_paprika_files(paprika_files, folder, progress_cb=self._log)
            self._log("Creating PDFs for extracted JSON files...")
            process_json_to_pdf(folder, progress_cb=self._log)

        self._run_task(task)

    def _action_create_pdfs_from_folder(self):
        folder = self._get_output_folder()
        if not folder:
            return

        def task():
            recipes_dir = Path(folder)
            json_files    = list(recipes_dir.glob("*.json"))
            paprika_files = (list(recipes_dir.glob("*.paprikarecipe")) +
                             list(recipes_dir.glob("*.paprikarecipes")))

            if not json_files and not paprika_files:
                self._log("No .json or .paprikarecipe/.paprikarecipes files found in output folder.")
                return

            from JSONToPDFRecipe import process_json_to_pdf
            if json_files:
                self._log(f"Creating PDFs for {len(json_files)} JSON file(s) in: {folder}")
                process_json_to_pdf(folder, progress_cb=self._log)
            else:
                self._log(f"Extracting {len(paprika_files)} Paprika file(s) from: {folder}")
                from PaprikaExtract import extract_paprika_files
                extract_paprika_files([str(f) for f in paprika_files], folder,
                                      progress_cb=self._log)
                self._log("Creating PDFs for extracted JSON files...")
                process_json_to_pdf(folder, progress_cb=self._log)

        self._run_task(task)

    def _action_create_json_from_files(self):
        folder = self._get_output_folder()
        if not folder:
            return

        paprika_files = [f for f in self._files
                         if f.lower().endswith('.paprikarecipes') or f.lower().endswith('.paprikarecipe')]
        pdf_files = [f for f in self._files if f.lower().endswith('.pdf')]

        if not paprika_files and not pdf_files:
            messagebox.showerror("No files",
                                 "Please add .paprikarecipes, .paprikarecipe, or .pdf files first.")
            return

        def task():
            if paprika_files:
                self._log(f"Extracting {len(paprika_files)} Paprika file(s) to: {folder}")
                from PaprikaExtract import extract_paprika_files
                extract_paprika_files(paprika_files, folder, progress_cb=self._log)

            if pdf_files:
                self._log(f"Converting {len(pdf_files)} PDF file(s) to JSON...")
                from PDFToJSONRecipe import pdf_to_json
                import re
                for pdf in pdf_files:
                    try:
                        self._log(f"  Converting: {os.path.basename(pdf)}")
                        recipe = pdf_to_json(pdf)
                        base = re.sub(r'\s*\(\d+\s*Stars?\)\s*$', '', Path(pdf).stem,
                                      flags=re.IGNORECASE).strip()
                        out = os.path.join(folder, base + '.json')
                        with open(out, 'w', encoding='utf-8') as f:
                            json.dump(recipe, f, indent=2, ensure_ascii=False)
                        self._log(f"    Saved: {os.path.basename(out)}")
                    except Exception as e:
                        self._log(f"    Error: {e}")

        self._run_task(task)

    def _action_create_json_from_folder(self):
        folder = self._get_output_folder()
        if not folder:
            return

        def task():
            recipes_dir   = Path(folder)
            paprika_files = (list(recipes_dir.glob("*.paprikarecipe")) +
                             list(recipes_dir.glob("*.paprikarecipes")))
            pdf_files     = list(recipes_dir.glob("*.pdf"))

            if not paprika_files and not pdf_files:
                self._log("No .paprikarecipe, .paprikarecipes, or .pdf files found in output folder.")
                return

            if paprika_files:
                self._log(f"Extracting {len(paprika_files)} Paprika file(s) from: {folder}")
                from PaprikaExtract import extract_paprika_files
                extract_paprika_files([str(f) for f in paprika_files], folder,
                                      progress_cb=self._log)

            if pdf_files:
                self._log(f"Converting {len(pdf_files)} PDF file(s) to JSON...")
                from PDFToJSONRecipe import pdf_to_json
                import re
                for pdf in pdf_files:
                    try:
                        self._log(f"  Converting: {pdf.name}")
                        recipe = pdf_to_json(str(pdf))
                        base = re.sub(r'\s*\(\d+\s*Stars?\)\s*$', '', pdf.stem,
                                      flags=re.IGNORECASE).strip()
                        out = recipes_dir / (base + '.json')
                        with open(out, 'w', encoding='utf-8') as f:
                            json.dump(recipe, f, indent=2, ensure_ascii=False)
                        self._log(f"    Saved: {out.name}")
                    except Exception as e:
                        self._log(f"    Error: {e}")

        self._run_task(task)

    def _action_create_paprikarecipes_from_files(self):
        folder = self._get_output_folder()
        if not folder:
            return

        source_files = [f for f in self._files if f.lower().endswith('.pdf')]
        if not source_files:
            messagebox.showerror("No files",
                                 "Please add .pdf files to the file list first.")
            return

        def task():
            self._log(f"Creating Paprikarecipes bundle from {len(source_files)} file(s)...")
            self._log(f"Output folder: {folder}")
            from CreatePaprikaImport import create_paprikarecipes_bundle
            create_paprikarecipes_bundle(source_files, folder, progress_cb=self._log)

        self._run_task(task)

    def _action_create_paprikarecipes_from_folder(self):
        folder = self._get_output_folder()
        if not folder:
            return

        def task():
            from pathlib import Path as _Path
            recipes_dir = _Path(folder)
            json_files = list(recipes_dir.glob("*.json"))
            pdf_files  = list(recipes_dir.glob("*.pdf"))

            if not json_files and not pdf_files:
                self._log("No .json or .pdf files found in the output folder.")
                return

            if len(json_files) >= len(pdf_files):
                source_files = [str(f) for f in json_files]
                self._log(f"Using {len(source_files)} JSON file(s) from: {folder}")
            else:
                source_files = [str(f) for f in pdf_files]
                self._log(f"Using {len(source_files)} PDF file(s) from: {folder}")

            from CreatePaprikaImport import create_paprikarecipes_bundle
            create_paprikarecipes_bundle(source_files, folder, progress_cb=self._log)

        self._run_task(task)

    def _show_llm_settings_dialog(self):
        from ImageToPDFRecipe import PROVIDERS

        dlg = tk.Toplevel(self.root)
        dlg.title("Configure LLM")
        dlg.resizable(False, False)
        dlg.grab_set()  # modal
        dlg.configure(bg="white")

        pad = {"padx": 12, "pady": 6}

        # Provider row
        tk.Label(dlg, text="Provider:", font=("Helvetica", 9, "bold"),
                 bg="white", fg=ACCENT).grid(row=0, column=0, sticky=tk.W, **pad)
        provider_var = tk.StringVar(value=self._settings.get('llm_provider', 'anthropic'))
        provider_cb = ttk.Combobox(dlg, textvariable=provider_var, state="readonly", width=28,
                                   values=[k for k in PROVIDERS])
        provider_cb.grid(row=0, column=1, sticky=tk.W, **pad)

        # Model row
        tk.Label(dlg, text="Model:", font=("Helvetica", 9, "bold"),
                 bg="white", fg=ACCENT).grid(row=1, column=0, sticky=tk.W, **pad)
        model_var = tk.StringVar(value=self._settings.get('llm_model', ''))
        model_cb = ttk.Combobox(dlg, textvariable=model_var, state="readonly", width=28)
        model_cb.grid(row=1, column=1, sticky=tk.W, **pad)

        def _refresh_models(*_):
            key = provider_var.get()
            models = PROVIDERS.get(key, {}).get('models', [])
            model_cb['values'] = models
            current = model_var.get()
            if current not in models:
                model_var.set(PROVIDERS.get(key, {}).get('default_model', models[0] if models else ''))

        provider_var.trace_add('write', _refresh_models)
        _refresh_models()

        # API key row
        tk.Label(dlg, text="API Key:", font=("Helvetica", 9, "bold"),
                 bg="white", fg=ACCENT).grid(row=2, column=0, sticky=tk.W, **pad)
        key_var = tk.StringVar(value=self._settings.get('llm_api_key', ''))
        key_entry = tk.Entry(dlg, textvariable=key_var, show="*", width=30,
                             font=("Helvetica", 9), relief=tk.GROOVE)
        key_entry.grid(row=2, column=1, sticky=tk.EW, **pad)

        # Hint
        hint_var = tk.StringVar()
        hint_lbl = tk.Label(dlg, textvariable=hint_var, font=("Helvetica", 8),
                            bg="white", fg="#7F8C8D", wraplength=300, justify=tk.LEFT)
        hint_lbl.grid(row=3, column=0, columnspan=2, sticky=tk.W, padx=12, pady=(0, 4))

        def _update_hint(*_):
            key  = provider_var.get()
            hint = PROVIDERS.get(key, {}).get('install_hint', '')
            hint_var.set(f"Install: {hint}" if hint else "")

        provider_var.trace_add('write', _update_hint)
        _update_hint()

        # Buttons
        btn_row = tk.Frame(dlg, bg="white")
        btn_row.grid(row=4, column=0, columnspan=2, pady=(4, 12))

        def _save():
            self._settings['llm_provider'] = provider_var.get()
            self._settings['llm_model']    = model_var.get()
            self._settings['llm_api_key']  = key_var.get().strip()
            self._save_settings(self._settings)
            self._llm_status_lbl.configure(text=self._llm_status_text())
            dlg.destroy()

        tk.Button(btn_row, text="Save", command=_save,
                  bg=BTN_BG, fg=BTN_FG, activebackground=BTN_ACT, activeforeground=BTN_FG,
                  font=("Helvetica", 9), relief=tk.FLAT, padx=16, pady=4,
                  cursor="hand2").pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(btn_row, text="Cancel", command=dlg.destroy,
                  bg="#95A5A6", fg=BTN_FG, activebackground="#7F8C8D", activeforeground=BTN_FG,
                  font=("Helvetica", 9), relief=tk.FLAT, padx=16, pady=4,
                  cursor="hand2").pack(side=tk.LEFT)

        dlg.update_idletasks()
        # Centre the dialog over the main window
        mx = self.root.winfo_x() + (self.root.winfo_width()  - dlg.winfo_width())  // 2
        my = self.root.winfo_y() + (self.root.winfo_height() - dlg.winfo_height()) // 2
        dlg.geometry(f"+{mx}+{my}")

    def _action_extract_images_from_files(self):
        folder = self._get_output_folder()
        if not folder:
            return

        image_files = [
            f for f in self._files
            if Path(f).suffix.lower() in IMAGE_EXTENSIONS
        ]
        if not image_files:
            messagebox.showerror("No images",
                                 "Please add image files (.jpg, .png, etc.) to the file list first.")
            return

        provider = self._settings.get('llm_provider', '')
        api_key  = self._settings.get('llm_api_key', '')
        model    = self._settings.get('llm_model') or None
        if not provider or not api_key:
            messagebox.showerror("LLM not configured",
                                 "Please configure an LLM provider and API key first.")
            return

        def task():
            from ImageToPDFRecipe import extract_recipes_from_image
            total_recipes = 0
            for img_path in image_files:
                self._log(f"Processing: {os.path.basename(img_path)}")
                try:
                    pdfs = extract_recipes_from_image(
                        img_path, folder, provider, api_key, model, progress_cb=self._log
                    )
                    total_recipes += len(pdfs)
                except Exception as e:
                    self._log(f"  Error: {e}")
            self._log(f"Done. {total_recipes} recipe(s) saved to: {folder}")

        self._run_task(task)

    def _action_extract_images_from_folder(self):
        folder = self._get_output_folder()
        if not folder:
            return

        provider = self._settings.get('llm_provider', '')
        api_key  = self._settings.get('llm_api_key', '')
        model    = self._settings.get('llm_model') or None
        if not provider or not api_key:
            messagebox.showerror("LLM not configured",
                                 "Please configure an LLM provider and API key first.")
            return

        def task():
            recipes_dir = Path(folder)
            image_files = [
                f for f in recipes_dir.iterdir()
                if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS
            ]
            if not image_files:
                self._log("No image files found in the output folder.")
                return

            self._log(f"Found {len(image_files)} image(s) in: {folder}")
            from ImageToPDFRecipe import extract_recipes_from_image
            total_recipes = 0
            for img_path in sorted(image_files):
                self._log(f"Processing: {img_path.name}")
                try:
                    pdfs = extract_recipes_from_image(
                        str(img_path), folder, provider, api_key, model, progress_cb=self._log
                    )
                    total_recipes += len(pdfs)
                except Exception as e:
                    self._log(f"  Error: {e}")
            self._log(f"Done. {total_recipes} recipe(s) saved to: {folder}")

        self._run_task(task)

    def _action_create_cookbook(self):
        folder = self._get_output_folder()
        if not folder:
            return

        filter_mode = self._filter_var.get()
        image_mode  = self._format_var.get()
        output_path = os.path.join(folder, COOKBOOK_FILENAME)

        def task():
            self._log(f"Creating cookbook...")
            self._log(f"  Folder:  {folder}")
            self._log(f"  Filter:  {filter_mode}")
            self._log(f"  Images:  {image_mode}")
            self._log(f"  Output:  {output_path}")
            create_cookbook(folder, output_path, filter_mode, image_mode,
                            progress_cb=self._log)

        self._run_task(task)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    _fix_stdout()
    if _DND_AVAILABLE:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    app = App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
