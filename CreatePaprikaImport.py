"""
Create Paprika Import Package

This script:
1. Scans 'All Recipes' for PDF files that have no matching JSON file
2. Converts each unmatched PDF to JSON using PDFToJSONRecipe
3. Clears the 'Paprika Recipes to Import' folder
4. Copies the new JSON files (and their associated images) to that folder;
   if the JSON has no photo_data but a matching image exists, embeds the image
5. Gzips each JSON in the import folder and renames it to .paprikarecipe
6. Bundles all .paprikarecipe files into 'New Recipes.paprikarecipes' (a ZIP)
7. Cleans up: only image files and 'New Recipes.paprikarecipes' remain

PDF-to-JSON matching:
    "Recipe Name (X Stars).pdf"  →  "Recipe Name.json"
    The rating suffix is stripped from the PDF stem to produce the base name.

Image matching:
    Looks for files in 'All Recipes/Recipe Images/' whose filename starts with
    the sanitized recipe name (same sanitization used by download_recipe_image).
"""

import base64
import gzip
import json
import os
import re
import shutil
import sys
import zipfile
from pathlib import Path

# Fix encoding for Windows console
sys.stdout.reconfigure(encoding='utf-8')

# ── Configuration ─────────────────────────────────────────────────────────────
WORKSPACE_DIR = r"c:\Users\kippa\OneDrive\Documents\git-projects\cookbook-creator"
RECIPES_DIR   = "All Recipes"
IMAGES_SUBDIR = "Recipe Images"
IMPORT_DIR    = "Paprika Recipes to Import"
OUTPUT_NAME   = "New Recipes"

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sanitize_name(name):
    """Produce a safe filename stem from a recipe name (mirrors download_recipe_image)."""
    safe = "".join(c for c in name if c.isalnum() or c in (' ', '_', '-'))
    return safe.strip()


def _strip_rating_suffix(pdf_stem):
    """Remove ' (X Stars)' from a PDF filename stem to get the base recipe name."""
    return re.sub(r'\s*\(\d+\s*Stars?\)\s*$', '', pdf_stem, flags=re.IGNORECASE).strip()


def _find_matching_json(pdf_path, recipes_dir):
    """
    Given a PDF path, look for a JSON with the same base name in recipes_dir.
    Returns the JSON Path if found, else None.
    """
    base_name = _strip_rating_suffix(pdf_path.stem)
    candidate = recipes_dir / f'{base_name}.json'
    return candidate if candidate.exists() else None


def _find_associated_image(recipe_name, images_folder):
    """
    Search for an image file in images_folder whose stem starts with the
    sanitized recipe name.  Returns the first match Path, or None.
    """
    safe_name = _sanitize_name(recipe_name)
    if not images_folder.exists():
        return None
    for f in images_folder.iterdir():
        if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS:
            if f.stem.lower().startswith(safe_name.lower()):
                return f
    return None


def _embed_image_in_json(json_data, image_path):
    """
    Read an image file, base64-encode it, and store as photo_data in the
    JSON dict (in-place).  Does nothing if photo_data is already set.
    """
    if json_data.get('photo_data'):
        return
    try:
        with open(image_path, 'rb') as f:
            raw = f.read()
        json_data['photo_data'] = base64.b64encode(raw).decode('ascii')
        json_data['photo'] = image_path.name
        print(f'    Embedded image: {image_path.name}')
    except Exception as e:
        print(f'    Warning: could not embed image {image_path.name}: {e}')


def _gzip_json(json_path):
    """
    Gzip a JSON file in-place and rename it to .paprikarecipe.
    Returns the new Path.
    """
    gz_path = json_path.with_suffix('.paprikarecipe')
    with open(json_path, 'rb') as f_in:
        with gzip.open(str(gz_path), 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)
    json_path.unlink()
    return gz_path


def _bundle_paprikarecipes(import_dir, output_name):
    """
    Create a ZIP of all .paprikarecipe files in import_dir,
    named '<output_name>.paprikarecipes'.
    Returns the path to the created file.
    """
    paprika_files = list(import_dir.glob('*.paprikarecipe'))
    if not paprika_files:
        return None

    zip_path  = import_dir / f'{output_name}.zip'
    dest_path = import_dir / f'{output_name}.paprikarecipes'

    with zipfile.ZipFile(str(zip_path), 'w', zipfile.ZIP_DEFLATED) as zf:
        for pf in paprika_files:
            zf.write(str(pf), pf.name)

    zip_path.rename(dest_path)
    return dest_path


def _clean_import_folder(import_dir, bundle_name):
    """
    Remove everything from import_dir except:
      - image files (.jpg, .jpeg, .png, .gif, .webp)
      - the bundle file  '<bundle_name>.paprikarecipes'
    """
    keep_name = f'{bundle_name}.paprikarecipes'
    for f in import_dir.iterdir():
        if f.is_file():
            if f.name == keep_name or f.suffix.lower() in IMAGE_EXTENSIONS:
                continue
            f.unlink()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    os.chdir(WORKSPACE_DIR)

    recipes_dir  = Path(RECIPES_DIR)
    images_dir   = recipes_dir / IMAGES_SUBDIR
    import_dir   = Path(IMPORT_DIR)

    # ── Step 1: Find PDFs without matching JSONs ──────────────────────────────
    print('Step 1: Scanning for PDFs without matching JSON files')
    unmatched_pdfs = []
    for pdf in sorted(recipes_dir.glob('*.pdf')):
        if _find_matching_json(pdf, recipes_dir) is None:
            unmatched_pdfs.append(pdf)
            print(f'  No JSON: {pdf.name}')

    print(f'  Found {len(unmatched_pdfs)} unmatched PDF(s)')

    # ── Step 2: Convert unmatched PDFs → JSONs ────────────────────────────────
    print('\nStep 2: Converting PDFs to JSON')
    if not unmatched_pdfs:
        print('  No PDFs to convert.')

    # Import here so we only need the dependency when actually running
    from PDFToJSONRecipe import pdf_to_json

    new_json_paths = []
    for pdf in unmatched_pdfs:
        base_name = _strip_rating_suffix(pdf.stem)
        out_path  = recipes_dir / f'{base_name}.json'
        print(f'  Converting: {pdf.name}')
        try:
            recipe = pdf_to_json(str(pdf))
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(recipe, f, indent=2, ensure_ascii=False)
            new_json_paths.append(out_path)
            print(f'    Saved: {out_path.name}')
        except Exception as e:
            print(f'    Error: {e}')

    # ── Step 3: Early exit if nothing was created ─────────────────────────────
    if not new_json_paths:
        print('\nNo new JSON files were created. Nothing to import. Exiting.')
        return

    print(f'\n  Created {len(new_json_paths)} new JSON file(s)')

    # ── Step 4: Clear import folder ───────────────────────────────────────────
    print(f'\nStep 4: Clearing "{IMPORT_DIR}" folder')
    if import_dir.exists():
        for f in import_dir.iterdir():
            if f.is_file():
                f.unlink()
        print(f'  Cleared existing files')
    else:
        import_dir.mkdir(parents=True)
        print(f'  Created folder: {IMPORT_DIR}')

    # ── Step 5: Copy new JSONs + associated images to import folder ───────────
    print(f'\nStep 5: Copying files to "{IMPORT_DIR}"')
    for json_path in new_json_paths:
        # Load JSON so we can check/embed photo_data
        with open(json_path, encoding='utf-8') as f:
            recipe_data = json.load(f)

        recipe_name = recipe_data.get('name', json_path.stem)

        # Look for an associated image
        img_path = _find_associated_image(recipe_name, images_dir)
        if img_path:
            # Embed image into the JSON copy (only if photo_data is absent)
            _embed_image_in_json(recipe_data, img_path)
            # Copy the image file
            shutil.copy2(str(img_path), str(import_dir / img_path.name))
            print(f'  Copied image: {img_path.name}')

        # Write (possibly updated) JSON to import folder
        dest_json = import_dir / json_path.name
        with open(dest_json, 'w', encoding='utf-8') as f:
            json.dump(recipe_data, f, indent=2, ensure_ascii=False)
        print(f'  Copied JSON: {json_path.name}')

    # ── Step 6: Gzip each JSON → .paprikarecipe ───────────────────────────────
    print(f'\nStep 6: Compressing JSON files to .paprikarecipe format')
    for json_file in list(import_dir.glob('*.json')):
        gz_path = _gzip_json(json_file)
        print(f'  Compressed: {json_file.name} → {gz_path.name}')

    # ── Step 7: Bundle into .paprikarecipes ───────────────────────────────────
    print(f'\nStep 7: Bundling into {OUTPUT_NAME}.paprikarecipes')
    bundle_path = _bundle_paprikarecipes(import_dir, OUTPUT_NAME)
    if bundle_path:
        print(f'  Created: {bundle_path.name}')
    else:
        print('  No .paprikarecipe files to bundle.')

    # ── Step 8: Clean up import folder ───────────────────────────────────────
    print(f'\nStep 8: Cleaning up import folder')
    _clean_import_folder(import_dir, OUTPUT_NAME)
    remaining = [f.name for f in import_dir.iterdir() if f.is_file()]
    print(f'  Remaining files ({len(remaining)}):')
    for name in sorted(remaining):
        print(f'    {name}')

    print(f'\nComplete! Import package ready in: {IMPORT_DIR}/')


if __name__ == '__main__':
    main()
