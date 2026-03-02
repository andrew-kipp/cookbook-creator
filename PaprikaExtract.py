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
from pathlib import Path

# Configuration
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

def main():
    os.chdir(WORKSPACE_DIR)
    
    recipes_needing_review = []
    
    # Step 1: Convert .paprikarecipes to .zip and extract
    print(f"Step 1: Processing {SOURCE_FILE}")
    
    # Create temporary directory for first extraction
    if os.path.exists(TEMP_EXTRACT_DIR):
        shutil.rmtree(TEMP_EXTRACT_DIR)
    os.makedirs(TEMP_EXTRACT_DIR)
    
    # Copy file with .zip extension
    zip_file = os.path.join(TEMP_EXTRACT_DIR, "temp.zip")
    shutil.copy2(SOURCE_FILE, zip_file)
    print(f"  Copied to temporary .zip file")
    
    # Extract the zip file
    shutil.unpack_archive(zip_file, TEMP_EXTRACT_DIR)
    print(f"  Extracted .zip file")
    
    # Step 2: Find and process .paprikarecipe files
    print(f"\nStep 2: Processing .paprikarecipe files")
    
    # Check if output directory already exists
    output_dir_exists = os.path.exists(OUTPUT_DIR)
    if not output_dir_exists:
        os.makedirs(OUTPUT_DIR)
    
    paprikarecipe_files = list(Path(TEMP_EXTRACT_DIR).rglob("*.paprikarecipe"))
    print(f"  Found {len(paprikarecipe_files)} .paprikarecipe files")
    
    # Step 3: Convert to .gz and extract
    print(f"\nStep 3: Converting to .gz and extracting")
    
    for paprikarecipe_file in paprikarecipe_files:
        # Create gz filename
        gz_file = paprikarecipe_file.with_suffix(".gz")
        
        # Rename to .gz
        os.rename(str(paprikarecipe_file), str(gz_file))
        print(f"  Renamed: {paprikarecipe_file.name} -> {gz_file.name}")
        
        # Extract gz file to temporary location
        temp_extracted = os.path.join(OUTPUT_DIR, gz_file.stem)
        try:
            with gzip.open(str(gz_file), 'rb') as f_in:
                with open(temp_extracted, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            print(f"  Extracted: {gz_file.name}")
        except Exception as e:
            print(f"  Error extracting {gz_file.name}: {e}")
    
    # Step 4: Convert extracted files to JSON
    print(f"\nStep 4: Converting files to JSON format")

    import re as _re
    extracted_files = list(Path(OUTPUT_DIR).glob("*"))
    for extracted_file in extracted_files:
        if extracted_file.is_file() and not extracted_file.name.endswith('.json'):
            try:
                with open(extracted_file, 'r', encoding='utf-8') as f:
                    content = f.read()

                # Parse as XML or JSON
                try:
                    root = ET.fromstring(content)
                    json_data = {root.tag: xml_to_dict(root)}
                except ET.ParseError:
                    try:
                        json_data = json.loads(content)
                    except json.JSONDecodeError:
                        json_data = {"content": content}

                # Derive output filename from the recipe's 'name' field so that
                # special characters (accented letters, curly quotes, en-dashes)
                # in the recipe name are preserved correctly in the filename.
                # shutil.unpack_archive decodes zip entry names as CP437 when the
                # UTF-8 flag is absent, producing garbled stems like "Alb├│ndigas"
                # instead of "Albóndigas".  Using the parsed name avoids this.
                recipe_name = json_data.get('name', '').strip() if isinstance(json_data, dict) else ''
                if recipe_name:
                    # Strip characters that are illegal in Windows filenames
                    safe_name = _re.sub(r'[<>:"/\\|?*]', '', recipe_name).strip()
                    json_output = Path(OUTPUT_DIR) / (safe_name + '.json')
                else:
                    # Fallback: use the stem of the extracted file as before
                    json_output = extracted_file.with_suffix('.json')

                # Save with duplicate handling
                if save_json_recipe(json_data, str(json_output), recipes_needing_review):
                    print(f"  Converted: {extracted_file.name} -> {json_output.name}")
                else:
                    print(f"  Skipped (identical): {extracted_file.name}")

                # Remove the original extracted file
                os.remove(str(extracted_file))
            except Exception as e:
                print(f"  Error converting {extracted_file.name}: {e}")
    
    # Step 5: Cleanup
    print(f"\nStep 5: Cleaning up temporary files")
    shutil.rmtree(TEMP_EXTRACT_DIR)
    print(f"  Removed temporary directory")
    
    # Step 6: Create review list file
    print(f"\nStep 6: Creating review list")
    if recipes_needing_review:
        review_file_path = os.path.join(WORKSPACE_DIR, REVIEW_LIST_FILE)
        with open(review_file_path, 'w', encoding='utf-8') as f:
            f.write("Recipes Needing Review\n")
            f.write("=" * 50 + "\n\n")
            f.write("The following recipes have been identified as new or modified versions.\n")
            f.write("Please review them to determine if they should be kept or merged with existing recipes.\n\n")
            for recipe_name in recipes_needing_review:
                f.write(f"- {recipe_name}\n")
        print(f"  Created {REVIEW_LIST_FILE} with {len(recipes_needing_review)} recipe(s)")
    else:
        print(f"  No recipes require review")
    
    print(f"\nComplete!")

if __name__ == "__main__":
    main()