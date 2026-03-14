"""
Image to PDF Recipe Extractor

Uses an LLM (Claude, GPT-4o, or Gemini) to extract recipe data from
screenshot/image files, saves each recipe as JSON, then renders a formatted
PDF using the existing RecipeFormatter pipeline.  A single image may contain
more than one recipe.
"""

import base64
import json
import os
import re
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate
from RecipeFormatter import (
    get_recipe_styles,
    format_recipe_first_page,
    format_recipe_second_page,
    LEFT_RIGHT_MARGIN,
    PAGE_TOP_MARGIN,
    PAGE_BOTTOM_MARGIN,
)

# Image file extensions accepted by the app
SUPPORTED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}
IMAGES_SUBDIR = "Recipe Images"

# ── Extraction prompt ─────────────────────────────────────────────────────────

EXTRACTION_PROMPT = """\
Extract all recipes from this image. Return a JSON array — one object per recipe found.

Each recipe object must use exactly these fields:
{
  "name": "Recipe Name",
  "servings": "4 servings",
  "prep_time": "10 mins",
  "cook_time": "30 mins",
  "total_time": "40 mins",
  "ingredients": "1 cup flour\\n2 eggs\\n...",
  "directions": "Step one description.\\n\\nStep two description.",
  "notes": "",
  "source": "",
  "source_url": "",
  "rating": null,
  "categories": [],
  "nutritional_info": ""
}

Rules:
- ingredients: one ingredient per line (newline-separated)
- directions: steps separated by blank lines (double newline between steps)
- rating: integer 1-5 or null
- categories: list of strings e.g. ["Dinner", "Italian"], or []
- nutritional_info: pipe-separated values e.g. "Calories: 350 | Protein: 25g", or ""
- Use "" for absent string fields, null for absent rating, [] for absent lists
- Return ONLY the JSON array — no markdown, no extra commentary
- Even if only one recipe is found, return an array with one element
"""

# ── Helpers ───────────────────────────────────────────────────────────────────

def _encode_image(image_path: str) -> tuple:
    """Return (base64_data, media_type) for an image file."""
    ext = Path(image_path).suffix.lower()
    media_map = {
        '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
        '.png': 'image/png',  '.gif': 'image/gif',
        '.webp': 'image/webp',
    }
    media_type = media_map.get(ext, 'image/jpeg')
    with open(image_path, 'rb') as f:
        data = base64.standard_b64encode(f.read()).decode('utf-8')
    return data, media_type


def _to_supported_format(image_path: str) -> str:
    """
    Convert BMP (and any other unsupported format) to a temporary PNG.
    Returns the original path unchanged if the format is already supported.
    """
    if Path(image_path).suffix.lower() in {'.jpg', '.jpeg', '.png', '.gif', '.webp'}:
        return image_path
    try:
        from PIL import Image as PILImage
        import tempfile
        img = PILImage.open(image_path)
        tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        img.save(tmp.name, 'PNG')
        return tmp.name
    except ImportError:
        raise ImportError(
            "Pillow is required to process BMP files. Run: pip install Pillow"
        )


def _parse_json_response(text: str) -> list:
    """Extract and parse a JSON array from LLM response text."""
    # Strip markdown code fences
    text = re.sub(r'^```(?:json)?\s*', '', text.strip(), flags=re.MULTILINE)
    text = re.sub(r'\s*```\s*$', '', text.strip(), flags=re.MULTILINE)
    text = text.strip()
    # Find the outermost JSON array
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match:
        text = match.group(0)
    recipes = json.loads(text)
    if isinstance(recipes, dict):
        recipes = [recipes]
    return recipes


def _recipe_to_pdf(recipe_data: dict, output_dir: str) -> str:
    """
    Save recipe_data as a JSON file, then render a formatted PDF.
    Returns the path of the created PDF.
    """
    name   = recipe_data.get('name', 'Unknown Recipe')
    rating = recipe_data.get('rating', '')

    # Save JSON alongside the PDF
    json_path = os.path.join(output_dir, f"{name}.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(recipe_data, f, indent=2, ensure_ascii=False)

    # Build PDF path
    rating_suffix = f" ({rating} Stars)" if rating not in (None, '') else ""
    pdf_path = os.path.join(output_dir, f"{name}{rating_suffix}.pdf")

    # Images subfolder (required by formatter even when not embedding images)
    images_folder = os.path.join(output_dir, IMAGES_SUBDIR)
    os.makedirs(images_folder, exist_ok=True)

    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=letter,
        leftMargin=LEFT_RIGHT_MARGIN,
        rightMargin=LEFT_RIGHT_MARGIN,
        topMargin=PAGE_TOP_MARGIN,
        bottomMargin=PAGE_BOTTOM_MARGIN,
    )
    styles = get_recipe_styles()
    story  = []

    first_page_elements, overflow_ingredients, overflow_right, overflow_directions_count = \
        format_recipe_first_page(recipe_data, styles)
    story.extend(first_page_elements)
    story.extend(format_recipe_second_page(
        recipe_data, None, styles,
        overflow_ingredients, overflow_right, overflow_directions_count,
        include_image=False,
    ))

    doc.build(story)
    return pdf_path


# ── Provider implementations ──────────────────────────────────────────────────

def _extract_anthropic(image_path: str, api_key: str, model: str) -> list:
    try:
        import anthropic
    except ImportError:
        raise ImportError(
            "anthropic package not installed. Run: pip install anthropic"
        )
    image_path = _to_supported_format(image_path)
    data, media_type = _encode_image(image_path)
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": data}
                },
                {"type": "text", "text": EXTRACTION_PROMPT},
            ]
        }]
    )
    return _parse_json_response(response.content[0].text)


def _extract_openai(image_path: str, api_key: str, model: str) -> list:
    try:
        import openai
    except ImportError:
        raise ImportError(
            "openai package not installed. Run: pip install openai"
        )
    image_path = _to_supported_format(image_path)
    data, media_type = _encode_image(image_path)
    client = openai.OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{media_type};base64,{data}"}
                },
                {"type": "text", "text": EXTRACTION_PROMPT},
            ]
        }]
    )
    return _parse_json_response(response.choices[0].message.content)


def _extract_gemini(image_path: str, api_key: str, model: str) -> list:
    try:
        import google.generativeai as genai
    except ImportError:
        raise ImportError(
            "google-generativeai package not installed. Run: pip install google-generativeai"
        )
    try:
        from PIL import Image as PILImage
    except ImportError:
        raise ImportError(
            "Pillow is required for Gemini support. Run: pip install Pillow"
        )
    genai.configure(api_key=api_key)
    gemini_model = genai.GenerativeModel(model)
    image = PILImage.open(image_path)
    response = gemini_model.generate_content([EXTRACTION_PROMPT, image])
    return _parse_json_response(response.text)


# ── Provider registry ─────────────────────────────────────────────────────────

PROVIDERS = {
    'anthropic': {
        'name':          'Claude (Anthropic)',
        'models':        ['claude-opus-4-6', 'claude-sonnet-4-6', 'claude-haiku-4-5'],
        'default_model': 'claude-opus-4-6',
        'install_hint':  'pip install anthropic',
        '_fn':           _extract_anthropic,
    },
    'openai': {
        'name':          'GPT-4o (OpenAI)',
        'models':        ['gpt-4o', 'gpt-4o-mini'],
        'default_model': 'gpt-4o',
        'install_hint':  'pip install openai',
        '_fn':           _extract_openai,
    },
    'gemini': {
        'name':          'Gemini (Google)',
        'models':        ['gemini-2.0-flash', 'gemini-1.5-pro', 'gemini-1.5-flash'],
        'default_model': 'gemini-2.0-flash',
        'install_hint':  'pip install google-generativeai Pillow',
        '_fn':           _extract_gemini,
    },
}


# ── Public API ────────────────────────────────────────────────────────────────

def extract_recipes_from_image(image_path, output_dir, provider, api_key, model=None, progress_cb=None):
    """
    Extract recipe(s) from an image file using an LLM, then render each as a PDF.

    image_path  : path to the image file
    output_dir  : folder where JSON and PDF files are saved
    provider    : 'anthropic', 'openai', or 'gemini'
    api_key     : API key for the chosen provider
    model       : model name (uses provider default if None)
    progress_cb : optional callable(str) for progress messages

    Returns a list of PDF paths created (one per recipe found in the image).
    Raises on API / import errors.
    """
    def log(msg):
        if progress_cb:
            progress_cb(msg)
        else:
            print(msg)

    if provider not in PROVIDERS:
        raise ValueError(
            f"Unknown provider '{provider}'. Choose from: {list(PROVIDERS)}"
        )
    p = PROVIDERS[provider]
    if not model:
        model = p['default_model']

    log(f"  Sending to {p['name']} ({model})...")
    recipes = p['_fn'](image_path, api_key, model)
    log(f"  Extracted {len(recipes)} recipe(s) from image")

    pdf_paths = []
    for recipe in recipes:
        name = recipe.get('name', 'Unknown Recipe')
        pdf_path = _recipe_to_pdf(recipe, output_dir)
        log(f"  Saved: {os.path.basename(pdf_path)}")
        pdf_paths.append(pdf_path)

    return pdf_paths
