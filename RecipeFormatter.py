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

# Page margins: left/right restored to 0.5in; top/bottom increased by 50% (0.25in -> 0.375in)
# Increase side margins by 30% (0.5in -> 0.65in)
LEFT_RIGHT_MARGIN = 0.65 * inch
PAGE_TOP_MARGIN = 0.375 * inch
PAGE_BOTTOM_MARGIN = 0.375 * inch
# Fraction of each column's available space to actually use for content
SECTION_FILL = 0.9

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
        fontSize=9,
        textColor='#555555',
        spaceAfter=6,
        alignment=TA_LEFT,
        leftIndent=0
    )

    # Source style: slightly reduced spacing from the info line, and smaller space after
    source_style = ParagraphStyle(
        'RecipeSource',
        parent=styles['Normal'],
        fontSize=9,
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
        spaceAfter=8,
        spaceBefore=4,
        alignment=TA_CENTER
    )
    
    # Ingredients: left aligned, single-spaced (tight leading), small spacing after each line
    ingredient_style = ParagraphStyle(
        'IngredientText',
        parent=styles['BodyText'],
        fontSize=9,
        leading=9,
        spaceAfter=0,
        alignment=TA_LEFT,
        leftIndent=0.1*inch
    )
    
    # Directions: similar tight leading to keep content compact
    direction_style = ParagraphStyle(
        'DirectionText',
        parent=styles['BodyText'],
        fontSize=9,
        leading=12,
        spaceAfter=6,
        alignment=TA_LEFT,
        leftIndent=0.1*inch
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
    Format the first page with recipe info, ingredients, and directions in two columns
    
    Returns a list of platypus elements for the first page
    """
    elements = []
    overflow_ingredients = []
    
    # Title (left aligned at top)
    recipe_name = recipe_data.get('name', 'Recipe')
    title_para = Paragraph(recipe_name, styles['title'])
    elements.append(title_para)
    
    # Recipe Info (servings, times, source, etc.)
    info_parts = []
    servings = recipe_data.get('servings', '')
    prep_time = recipe_data.get('prep_time', '')
    cook_time = recipe_data.get('cook_time', '')
    total_time = recipe_data.get('total_time', '')
    
    if servings:
        info_parts.append(f"<b>Servings:</b> {servings}")
    if prep_time:
        info_parts.append(f"<b>Prep:</b> {prep_time}")
    if cook_time:
        info_parts.append(f"<b>Cook:</b> {cook_time}")
    if total_time:
        info_parts.append(f"<b>Total:</b> {total_time}")
    
    if info_parts:
        info_text = " | ".join(info_parts)
        info_para = Paragraph(info_text, styles['info'])
        elements.append(info_para)
    
    source = recipe_data.get('source', '')
    source_url = recipe_data.get('source_url', '')
    if source or source_url:
        source_text = source if source else "Source"
        if source_url:
            source_text = f"<u>{source_text}</u>"
        elements.append(Paragraph(f"<b>Source:</b> {source_text}", styles['info']))
    
    spacer_height = 0.2 * inch
    elements.append(Spacer(1, spacer_height))
    
    # Create two-column layout with vertical line
    # Compute usable width inside left/right document margins so the table aligns
    usable_width = letter[0] - 2 * LEFT_RIGHT_MARGIN
    # Use straightforward 30/70 column split of the usable width, but only
    # fill SECTION_FILL (92%) of each column so content doesn't touch edges.
    left_col_width = usable_width * 0.30 * SECTION_FILL
    right_col_width = usable_width * 0.70 * SECTION_FILL
    
    # Build left column (Ingredients)
    left_col_elements = []
    left_col_heading = Paragraph("Ingredients", styles['section_heading'])
    left_col_elements.append(left_col_heading)

    ingredients = recipe_data.get('ingredients', '')
    ingredient_paragraphs = []
    if ingredients:
        ingredients_lines = ingredients.strip().split('\n')
        for ingredient in ingredients_lines:
            if ingredient.strip():
                ingredient_paragraphs.append(Paragraph(f"• {ingredient.strip()}", styles['ingredient']))

    # Estimate available vertical space for the two-column area by measuring
    # the header (title + info) heights and subtracting from page height.
    header_height = 0
    try:
        # Wrap title and info to get exact heights
        w, h = title_para.wrap(usable_width, letter[1])
        header_height += h
        if 'info' in locals():
            w, h = info_para.wrap(usable_width, letter[1])
            header_height += h
    except Exception:
        # Fallback estimate
        header_height = styles['title'].fontSize + styles['info'].fontSize * 2

    header_height += spacer_height

    available_height = letter[1] - PAGE_TOP_MARGIN - PAGE_BOTTOM_MARGIN - header_height

    # Measure ingredient paragraphs to determine overflow
    cum_height = 0
    fit_count = 0
    # include section heading height
    try:
        w, h = left_col_heading.wrap(left_col_width, available_height)
        cum_height += h
    except Exception:
        cum_height += styles['section_heading'].fontSize * 1.5

    for p in ingredient_paragraphs:
        w, h = p.wrap(left_col_width, available_height)
        if cum_height + h <= available_height:
            cum_height += h
            fit_count += 1
        else:
            break

    # Prepare left column elements: either all or only the fit portion
    if fit_count >= len(ingredient_paragraphs):
        # All ingredients fit
        left_col_elements.extend(ingredient_paragraphs)
    else:
        # Some ingredients overflow: put fit portion in left column and record overflow
        left_col_elements.extend(ingredient_paragraphs[:fit_count])
        overflow_ingredients = ingredient_paragraphs[fit_count:]
    
    # Build right column (Directions)
    right_col_elements = []
    right_col_elements.append(Paragraph("Directions", styles['section_heading']))
    
    directions = recipe_data.get('directions', '')
    if directions:
        direction_paragraphs = directions.split('\n\n')
        for i, direction in enumerate(direction_paragraphs, 1):
            if direction.strip():
                step_text = f"<b>Step {i}:</b> {direction.strip()}"
                right_col_elements.append(Paragraph(step_text, styles['direction']))

    # Notes: place in the same right column below Directions with same formatting
    notes = recipe_data.get('notes', '')
    if notes:
        right_col_elements.append(Paragraph("Notes", styles['section_heading']))
        right_col_elements.append(Paragraph(notes, styles['direction']))
    
    # Create table with vertical line separator
    table_data = [
        [left_col_elements, right_col_elements]
    ]
    
    col_widths = [left_col_width, right_col_width]
    
    recipe_table = Table(table_data, colWidths=col_widths)
    recipe_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        # Zero out table side paddings so the table aligns exactly with document margins;
        # paragraph styles handle internal indentation.
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        # Draw a vertical line before the right column to separate ingredients and directions
        ('LINEBEFORE', (1, 0), (1, 0), 1, colors.grey),
    ]))

    # Ensure the table's height will fit in the available frame. If not, move more
    # ingredient paragraphs to the overflow until it fits. If even with zero
    # ingredients the table doesn't fit, fall back to rendering directions
    # as full-width and move all ingredients to the overflow.
    tw, th = recipe_table.wrap(usable_width, available_height)
    while th > available_height and len(left_col_elements) > 1:
        # Move one more ingredient to overflow
        # left_col_elements[0] is the heading
        current_count = len(left_col_elements) - 1
        # reduce by one
        new_count = max(0, current_count - 1)
        left_col_elements = [left_col_heading] + ingredient_paragraphs[:new_count]
        overflow_ingredients = ingredient_paragraphs[new_count:]
        table_data = [[left_col_elements, right_col_elements]]
        recipe_table = Table(table_data, colWidths=col_widths)
        recipe_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('LINEBEFORE', (1, 0), (1, 0), 1, colors.grey),
        ]))
        tw, th = recipe_table.wrap(usable_width, available_height)

    if th > available_height and len(left_col_elements) <= 1:
        # Fallback: put directions as full-width and move all ingredients to overflow
        elements.append(Paragraph("Directions", styles['section_heading']))
        for p in right_col_elements[1:]:
            elements.append(p)
        overflow_ingredients = ingredient_paragraphs
        return elements, overflow_ingredients

    elements.append(recipe_table)

    # Nutritional information - placed beneath the two-column layout and formatted as a single line
    nutritional_info = recipe_data.get('nutritional_info', '')
    if nutritional_info:
        # Normalize lines into a single pipe-separated line
        lines = [ln.strip() for ln in nutritional_info.strip().splitlines() if ln.strip()]
        single_line = ' | '.join(lines)
        elements.append(Spacer(1, 0.08*inch))
        elements.append(Paragraph(f"<b>Nutritional Information:</b> {single_line}", styles['ingredient']))

    # If there are overflow ingredients, return them so the caller can
    # place them on a following page (e.g., before image or as a continued
    # Ingredients section).
    return elements, overflow_ingredients

def format_recipe_second_page(recipe_data, image_path, styles, overflow_ingredients=None):
    """
    Format the second page with image, nutritional info, and notes
    
    Returns a list of platypus elements for the second page
    """
    elements = []
    
    elements.append(PageBreak())
    
    # If there are overflow ingredients, paginate them at the start of the second page
    if overflow_ingredients:
        usable_width = letter[0] - 2 * LEFT_RIGHT_MARGIN
        # Apply SECTION_FILL here too so continued Ingredients use the same
        # reduced width as the first-page columns.
        usable_width = usable_width * SECTION_FILL
        elements.append(Paragraph("Ingredients (continued)", styles['section_heading']))
        # Reserve some space at top
        top_reserved = 0.15 * inch
        current_height = 0
        max_height = letter[1] - PAGE_TOP_MARGIN - PAGE_BOTTOM_MARGIN - top_reserved
        for p in overflow_ingredients:
            w, h = p.wrap(usable_width, max_height)
            if current_height + h <= max_height:
                elements.append(p)
                current_height += h
            else:
                elements.append(PageBreak())
                elements.append(Paragraph("Ingredients (continued)", styles['section_heading']))
                elements.append(p)
                current_height = h
        elements.append(Spacer(1, 0.15*inch))

    # Add image if available
    if image_path and os.path.exists(image_path):
        try:
            elements.append(Spacer(1, 0.3*inch))
            img = Image(image_path, width=5*inch, height=3*inch)
            elements.append(img)
            elements.append(Spacer(1, 0.2*inch))
        except Exception as e:
            print(f"  Error adding image: {e}")
    
    # Removed nutritional info and notes from second page to avoid duplication.
    # Nutritional information is shown beneath the two-column layout on the first page.
    
    return elements