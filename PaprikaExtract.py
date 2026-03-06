"""
Paprika Recipe File Extraction Script

This script:
1. Renames the .paprikarecipes file to .zip
2. Extracts all files to a folder called 'All Recipes'
3. Renames individual .paprikarecipe files to .gz
4. Extracts the gzipped files to the 'All Recipes' folder
5. Converts extracted files to JSON format
6. Handles duplicate detection and saves review list
"""

import os
import shutil
import gzip
import json
import xml.etree.ElementTree as ET
import hashlib
import re as _re
from pathlib import Path

# Configuration (used by CLI main() only)
WORKSPACE_DIR = r"c:\Users\kippa\OneDrive\Documents\git-projects\cookbook-creator"
SOURCE_FILE = "Export 2026-03-02 12.59.08 All Recipes.paprikarecipes"
OUTPUT_DIR = "All Recipes"
TEMP_EXTRACT_DIR = "temp_extract"
REVIEW_LIST_FILE = "recipes_needing_review.txt"

def get_file_hash(file_path):
    """Calculate SHA256 hash of a file"""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def files_are_identical(file1, file2):
    """Compare two files by their hash"""
    if not os.path.exists(file1) or not os.path.exists(file2):
        return False
    return get_file_hash(file1) == get_file_hash(file2)

def find_next_filename(base_path):
    """Find next available filename with (2), (3), etc. suffix"""
    base_dir = os.path.dirname(base_path)
    base_name = os.path.basename(base_path)
    name_parts = os.path.splitext(base_name)

    counter = 2
    while True:
        new_name = f"{name_parts[0]} ({counter}){name_parts[1]}"
        new_path = os.path.join(base_dir, new_name)
        if not os.path.exists(new_path):
            return new_path
        counter += 1

def xml_to_dict(element):
    """Convert XML element to dictionary"""
    result = {}

    # Add attributes
    if element.attrib:
        result['@attributes'] = element.attrib

    # Add text content
    if element.text and element.text.strip():
        result['#text'] = element.text.strip()

    # Add child elements
    children = {}
    for child in element:
        child_data = xml_to_dict(child)
        if child.tag in children:
            if not isinstance(children[child.tag], list):
                children[child.tag] = [children[child.tag]]
            children[child.tag].append(child_data)
        else:
            children[child.tag] = child_data

    result.update(children)

    # If only text content, return just the text
    if not children and not element.attrib and element.text:
        return element.text.strip()

    return result if result else None

def parse_and_convert_to_json(input_file, output_file):
    """Parse file content and convert to JSON"""
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Try to parse as XML
        try:
            root = ET.fromstring(content)
            data = {root.tag: xml_to_dict(root)}
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except ET.ParseError:
            # If not XML, try to parse as JSON already
            try:
                data = json.loads(content)
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                return True
            except json.JSONDecodeError:
                # If not JSON either, store as plain text in JSON structure
                data = {"content": content}
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                return True
    except Exception as e:
        print(f"  Error converting {input_file}: {e}")
        return False

def save_json_recipe(json_content, output_file, recipes_needing_review):
    """Save JSON recipe, handling duplicates"""
    if os.path.exists(output_file):
        # File exists, check if content is identical
        try:
            with open(output_file, 'r', encoding='utf-8') as f:
                existing_content = json.load(f)

            if existing_content == json_content:
                # Identical content, skip
                return False
            else:
                # Different content, save with (2) suffix
                new_path = find_next_filename(output_file)
                with open(new_path, 'w', encoding='utf-8') as f:
                    json.dump(json_content, f, indent=2, ensure_ascii=False)

                recipe_name = os.path.basename(new_path)
                recipes_needing_review.append(recipe_name)
                print(f"  Saved new version: {recipe_name}")
                return True
        except Exception as e:
            print(f"  Error comparing files: {e}")
            # On error, save with (2) suffix
            new_path = find_next_filename(output_file)
            with open(new_path, 'w', encoding='utf-8') as f:
                json.dump(json_content, f, indent=2, ensure_ascii=False)
            recipe_name = os.path.basename(new_path)
            recipes_needing_review.append(recipe_name)
            return True
    else:
        # File doesn't exist, save normally
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(json_content, f, indent=2, ensure_ascii=False)
        return True

def save_recipe_image(image_path, output_folder, recipes_needing_review):
    """Save recipe image, handling duplicates"""
    filename = os.path.basename(image_path)
    output_path = os.path.join(output_folder, filename)

    if os.path.exists(output_path):
        # File exists, check if content is identical
        if files_are_identical(image_path, output_path):
            # Identical, skip
            return False
        else:
            # Different, save with (2) suffix
            name_parts = os.path.splitext(filename)
            new_filename = f"{name_parts[0]} (2){name_parts[1]}"
            new_path = os.path.join(output_folder, new_filename)
            counter = 2
            while os.path.exists(new_path):
                counter += 1
                new_filename = f"{name_parts[0]} ({counter}){name_parts[1]}"
                new_path = os.path.join(output_folder, new_filename)

            shutil.copy2(image_path, new_path)
            recipes_needing_review.append(new_filename)
            print(f"  Saved new image version: {new_filename}")
            return True
    else:
        # File doesn't exist, copy normally
        shutil.copy2(image_path, output_path)
        return True


def _process_single_paprikarecipe(paprikarecipe_path, output_dir, recipes_needing_review, log):
    """
    Extract a single .paprikarecipe (gzipped JSON) file into output_dir.
    paprikarecipe_path: absolute path string to a .paprikarecipe file
    """
    import tempfile
    p = Path(paprikarecipe_path)
    # Decompress to a temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix='') as tmp:
        tmp_path = tmp.name
    try:
        with gzip.open(str(p), 'rb') as f_in:
            with open(tmp_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)

        # Parse to JSON
        with open(tmp_path, 'r', encoding='utf-8') as f:
            content = f.read()
        try:
            json_data = json.loads(content)
        except json.JSONDecodeError:
            try:
                root = ET.fromstring(content)
                json_data = {root.tag: xml_to_dict(root)}
            except ET.ParseError:
                json_data = {"content": content}

        recipe_name = json_data.get('name', '').strip() if isinstance(json_data, dict) else ''
        if recipe_name:
            safe_name = _re.sub(r'[<>:"/\\|?*]', '', recipe_name).strip()
            json_output = Path(output_dir) / (safe_name + '.json')
        else:
            json_output = Path(output_dir) / (p.stem + '.json')

        if save_json_recipe(json_data, str(json_output), recipes_needing_review):
            log(f"  Extracted: {p.name} -> {json_output.name}")
        else:
            log(f"  Skipped (identical): {p.name}")
    except Exception as e:
        log(f"  Error extracting {p.name}: {e}")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def extract_paprika_files(input_files, output_dir, progress_cb=None):
    """
    Extract Paprika recipe files to output_dir.

    input_files : list of absolute path strings; may be a mix of
                  .paprikarecipes (batch zip) and .paprikarecipe (single gz) files.
    output_dir  : absolute path to the folder where JSON files will be saved.
    progress_cb : optional callable(message: str) for progress reporting.
    """
    def log(msg):
        if progress_cb:
            progress_cb(msg)
        else:
            print(msg)

    recipes_needing_review = []
    output_dir = str(output_dir)

    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)

    for input_file in input_files:
        ext = Path(input_file).suffix.lower()

        if ext == '.paprikarecipes':
            # ── Batch file: unzip → process each .paprikarecipe inside ──────
            log(f"Processing batch file: {Path(input_file).name}")
            temp_dir = os.path.join(output_dir, "_temp_extract")
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            os.makedirs(temp_dir)

            try:
                zip_file = os.path.join(temp_dir, "temp.zip")
                shutil.copy2(input_file, zip_file)
                shutil.unpack_archive(zip_file, temp_dir)
                log("  Extracted batch zip")

                inner_files = list(Path(temp_dir).rglob("*.paprikarecipe"))
                log(f"  Found {len(inner_files)} recipe(s) inside")

                for inner in inner_files:
                    _process_single_paprikarecipe(str(inner), output_dir, recipes_needing_review, log)
            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)

        elif ext == '.paprikarecipe':
            # ── Single recipe file ────────────────────────────────────────
            log(f"Processing single recipe: {Path(input_file).name}")
            _process_single_paprikarecipe(input_file, output_dir, recipes_needing_review, log)

        else:
            log(f"Skipped unsupported file type: {Path(input_file).name}")

    # Write review list
    if recipes_needing_review:
        review_file = os.path.join(output_dir, REVIEW_LIST_FILE)
        with open(review_file, 'w', encoding='utf-8') as f:
            f.write("Recipes Needing Review\n")
            f.write("=" * 50 + "\n\n")
            f.write("The following recipes have been identified as new or modified versions.\n")
            f.write("Please review them to determine if they should be kept or merged.\n\n")
            for name in recipes_needing_review:
                f.write(f"- {name}\n")
        log(f"Created {REVIEW_LIST_FILE} with {len(recipes_needing_review)} recipe(s) needing review")
    else:
        log("No recipes require review")

    log("Complete!")


def main():
    source_path = os.path.join(WORKSPACE_DIR, SOURCE_FILE)
    output_path = os.path.join(WORKSPACE_DIR, OUTPUT_DIR)
    extract_paprika_files([source_path], output_path)

if __name__ == "__main__":
    main()
