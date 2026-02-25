"""
JSON Recipe to PDF Converter

This script:
1. Reads JSON recipe files from the 'All Recipes' folder
2. Creates a formatted PDF recipe for each JSON file using RecipeFormatter
3. Downloads recipe images from 'image_url' if available
4. Saves images to a 'Recipe Images' subfolder with the recipe name
5. Skips processing if recipes_needing_review.txt exists
6. Skips JSON files that haven't been modified since their PDF was created

This script will:

Create Recipe Images subfolder - Creates a subfolder within 'All Recipes' to store downloaded images
Read JSON files - Processes each JSON recipe file in the 'All Recipes' folder
Download images - Downloads images from the image_url field if available
Create formatted PDFs - Generates professional PDF recipes with:
    Recipe title
    Recipe image (if available)
    Servings, prep time, cook time, total time
    Source information
    Formatted ingredients list
    Step-by-step directions
    Nutritional information
    Notes
Organize files - Saves PDFs in 'All Recipes' and images in 'All Recipes/Recipe Images'

You'll need to install the reportlab library for PDF generation:
pip install reportlab requests
"""

import json
import os
from pathlib import Path
import requests
import time
import re
import sys
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

# Configuration
WORKSPACE_DIR = r"c:\Users\kippa\OneDrive\Documents\git-projects\cookbook-creator"
RECIPES_DIR = "All Recipes"
IMAGES_SUBDIR = "Recipe Images"
REVIEW_LIST_FILE = "recipes_needing_review.txt"

# Fix encoding for Windows console
sys.stdout.reconfigure(encoding='utf-8')

def search_google_images(recipe_title):
    """
    Search Google Images for the recipe title and return the first image URL
    """
    # Clean and shorten the title
    cleaned_title = re.sub(r'[^\w\s]', '', recipe_title).strip()
    query = cleaned_title.replace(' ', '+')[:50]
    url = f"https://www.google.com/search?q={query}&tbm=isch"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Referer': 'https://www.google.com/'
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        # Find image URLs using regex
        img_urls = re.findall(r'"ou\\":\\"([^"]+)"', response.text)
        if not img_urls:
            img_urls = re.findall(r'"ou":"([^"]+)"', response.text)
        if not img_urls:
            # Fallback to img src thumbnails
            img_urls = re.findall(r'src="([^"]+)"', response.text)
            img_urls = [u for u in img_urls if u.startswith('http') and not u.startswith('data:')]
        if img_urls:
            return img_urls[0]
        else:
            print(f"  No image URLs found in Google search for '{cleaned_title}'")
    except Exception as e:
        print(f"  Failed to search Google Images for '{cleaned_title}': {e}")
    return None

def check_review_list_exists():
    """Check if recipes_needing_review.txt exists and alert user"""
    review_file_path = os.path.join(WORKSPACE_DIR, REVIEW_LIST_FILE)
    if os.path.exists(review_file_path):
        print(f"ERROR: {REVIEW_LIST_FILE} exists in the workspace.")
        print("This indicates there are recipes that need to be reviewed from a previous extraction.")
        print("Please resolve the conflicts in that file before running this script again.")
        print(f"\nLocation: {review_file_path}")
        return True
    return False

def json_is_newer_than_pdf(json_file, pdf_file):
    """
    Check if JSON file is newer than PDF file
    Returns True if JSON is newer or if PDF doesn't exist
    """
    if not os.path.exists(pdf_file):
        return True
    
    json_mtime = os.path.getmtime(json_file)
    pdf_mtime = os.path.getmtime(pdf_file)
    
    # Consider them the same if modification times are within 10 minutes
    # (accounting for potential rounding differences)
    if abs(json_mtime - pdf_mtime) <= 600:  # 600 seconds = 10 minutes
        return False
    
    return json_mtime > pdf_mtime

def create_images_folder():
    """Create Recipe Images subfolder if it doesn't exist"""
    images_path = os.path.join(WORKSPACE_DIR, RECIPES_DIR, IMAGES_SUBDIR)
    if not os.path.exists(images_path):
        os.makedirs(images_path)
        print(f"  Created subfolder: {IMAGES_SUBDIR}")
    return images_path

def download_recipe_image(image_url, recipe_name, images_folder, rating=None):
    """
    Download image from URL and save with recipe name
    Includes retries for 403/Connection aborted and fallback to Google Images for 404
    Returns the local path to the image if successful, None otherwise
    """
    if not image_url or not image_url.strip():
        return None
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    # Create a safe filename from recipe name
    safe_name = "".join(c for c in recipe_name if c.isalnum() or c in (' ', '_', '-'))
    safe_name = safe_name.strip()
    
    # Append rating in parentheses if provided: e.g., " (5 stars)"
    suffix = f" ({rating} stars)" if rating not in (None, '') else ""
    
    def save_image(response, url):
        # Determine image extension from content-type or URL
        content_type = response.headers.get('content-type', '')
        if 'jpeg' in content_type or 'jpg' in content_type or url.endswith('.jpg'):
            extension = '.jpg'
        elif 'png' in content_type or url.endswith('.png'):
            extension = '.png'
        else:
            extension = '.jpg'  # Default to jpg
        
        # Save image
        image_path = os.path.join(images_folder, f"{safe_name}{suffix}{extension}")
        with open(image_path, 'wb') as f:
            f.write(response.content)
        
        print(f"  Downloaded image: {os.path.basename(image_path)}")
        return image_path
    
    # Try initial download
    try:
        response = requests.get(image_url, headers=headers, timeout=10)
        response.raise_for_status()
        if 'image' not in response.headers.get('content-type', '').lower():
            print(f"  URL does not point to an image: {image_url}")
            return None
        return save_image(response, image_url)
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 403:
            print(f"  403 Forbidden for {image_url}, retrying...")
            # Retry up to 3 times with delay
            for attempt in range(3):
                try:
                    time.sleep(2)  # Wait 2 seconds
                    response = requests.get(image_url, headers=headers, timeout=10)
                    response.raise_for_status()
                    if 'image' not in response.headers.get('content-type', '').lower():
                        print(f"  URL does not point to an image: {image_url}")
                        continue
                    return save_image(response, image_url)
                except Exception:
                    continue
            # If retries fail, fallback to Google Images
            print(f"  Retries failed for {image_url}, searching Google Images...")
            alt_url = search_google_images(recipe_name)
            if alt_url:
                try:
                    response = requests.get(alt_url, headers=headers, timeout=10)
                    response.raise_for_status()
                    if 'image' not in response.headers.get('content-type', '').lower():
                        print(f"  Google result is not an image: {alt_url}")
                        return None
                    return save_image(response, alt_url)
                except Exception as e2:
                    print(f"  Failed to download from Google Images: {e2}")
            return None
        elif e.response.status_code == 404:
            print(f"  404 Not Found for {image_url}, searching Google Images...")
            alt_url = search_google_images(recipe_name)
            if alt_url:
                try:
                    response = requests.get(alt_url, headers=headers, timeout=10)
                    response.raise_for_status()
                    if 'image' not in response.headers.get('content-type', '').lower():
                        print(f"  Google result is not an image: {alt_url}")
                        return None
                    return save_image(response, alt_url)
                except Exception as e2:
                    print(f"  Failed to download from Google Images: {e2}")
            return None
        else:
            print(f"  HTTP Error for {image_url}: {e}")
            return None
    except requests.exceptions.ConnectionError as e:
        if 'Connection aborted' in str(e):
            print(f"  Connection aborted for {image_url}, retrying...")
            # Retry up to 3 times
            for attempt in range(3):
                try:
                    time.sleep(2)
                    response = requests.get(image_url, headers=headers, timeout=10)
                    response.raise_for_status()
                    if 'image' not in response.headers.get('content-type', '').lower():
                        print(f"  URL does not point to an image: {image_url}")
                        continue
                    return save_image(response, image_url)
                except Exception:
                    continue
            # If retries fail, fallback to Google Images
            print(f"  Retries failed for {image_url}, searching Google Images...")
            alt_url = search_google_images(recipe_name)
            if alt_url:
                try:
                    response = requests.get(alt_url, headers=headers, timeout=10)
                    response.raise_for_status()
                    if 'image' not in response.headers.get('content-type', '').lower():
                        print(f"  Google result is not an image: {alt_url}")
                        return None
                    return save_image(response, alt_url)
                except Exception as e2:
                    print(f"  Failed to download from Google Images: {e2}")
            return None
        else:
            print(f"  Connection Error for {image_url}: {e}")
            return None
    except requests.exceptions.SSLError as e:
        print(f"  SSL Error for {image_url}: {e}")
        # Fallback to Google Images
        alt_url = search_google_images(recipe_name)
        if alt_url:
            try:
                response = requests.get(alt_url, headers=headers, timeout=10)
                response.raise_for_status()
                if 'image' not in response.headers.get('content-type', '').lower():
                    print(f"  Google result is not an image: {alt_url}")
                    return None
                return save_image(response, alt_url)
            except Exception as e2:
                print(f"  Failed to download from Google Images: {e2}")
        return None
    except Exception as e:
        print(f"  Failed to download image from {image_url}: {e}")
        return None

def create_pdf_recipe(json_file, recipes_folder, images_folder):
    """Create a PDF recipe from a JSON file using RecipeFormatter"""
    try:
        # Read JSON file
        with open(json_file, 'r', encoding='utf-8') as f:
            recipe_data = json.load(f)
        
        recipe_name = recipe_data.get('name', 'Recipe')
        rating = recipe_data.get('rating', '')
        rating_suffix = f" ({rating} Stars)" if rating != '' and rating is not None else ""

        # Create PDF filename with rating suffix
        pdf_basename = f"{recipe_name}{rating_suffix}"
        pdf_filename = f"{pdf_basename}.pdf"
        pdf_path = os.path.join(recipes_folder, pdf_filename)
        
        # Check if JSON is newer than PDF
        if not json_is_newer_than_pdf(json_file, pdf_path):
            print(f"  Skipped (not modified): {os.path.basename(json_file)}")
            return None
        
        # Create PDF document with reduced top/bottom margins
        doc = SimpleDocTemplate(
            pdf_path,
            pagesize=letter,
            leftMargin=LEFT_RIGHT_MARGIN,
            rightMargin=LEFT_RIGHT_MARGIN,
            topMargin=PAGE_TOP_MARGIN,
            bottomMargin=PAGE_BOTTOM_MARGIN,
        )
        
        # Get styles
        styles = get_recipe_styles()
        
        # Build story
        story = []
        
        # First page: Recipe info, ingredients, and directions
        first_page_result = format_recipe_first_page(recipe_data, styles)
        # format_recipe_first_page may return (elements, overflow_ingredients)
        if isinstance(first_page_result, tuple):
            first_page_elements, overflow_ingredients = first_page_result
        else:
            first_page_elements = first_page_result
            overflow_ingredients = []
        story.extend(first_page_elements)
        
        # Try to download image for second page (use same naming scheme with rating suffix)
        image_url = recipe_data.get('image_url', '')
        image_path = None
        if image_url:
            image_path = download_recipe_image(image_url, recipe_name, images_folder, rating)
        
        # Second page: include any overflow ingredients then image, nutritional info, and notes
        story.extend(format_recipe_second_page(recipe_data, image_path, styles, overflow_ingredients))
        
        # Build PDF
        doc.build(story)
        print(f"  Created PDF: {pdf_filename}")
        return True
    
    except Exception as e:
        print(f"  Error processing {os.path.basename(json_file)}: {e}")
        return False

def main():
    os.chdir(WORKSPACE_DIR)
    
    # Check if review list exists
    print("Step 1: Checking for pending recipe reviews")
    if check_review_list_exists():
        print("\nScript execution halted.")
        return
    print("  No pending reviews - proceeding with PDF generation\n")
    
    print("Step 2: Creating Recipe Images subfolder")
    images_folder = create_images_folder()
    
    print(f"\nStep 3: Processing JSON recipe files")
    recipes_folder = RECIPES_DIR
    
    # Find all JSON files
    json_files = list(Path(recipes_folder).glob("*.json"))
    print(f"  Found {len(json_files)} JSON recipe files")
    
    print(f"\nStep 4: Converting JSON to PDF and downloading images")
    success_count = 0
    skipped_count = 0
    for json_file in json_files:
        result = create_pdf_recipe(str(json_file), recipes_folder, images_folder)
        if result is True:
            success_count += 1
        elif result is None:
            skipped_count += 1
    
    print(f"\nStep 5: Summary")
    print(f"  Successfully converted: {success_count}/{len(json_files)} recipes")
    print(f"  Skipped (not modified): {skipped_count}/{len(json_files)} recipes")
    print(f"  PDFs saved in: {recipes_folder}")
    print(f"  Images saved in: {os.path.join(recipes_folder, IMAGES_SUBDIR)}")
    print(f"\nComplete!")

if __name__ == "__main__":
    main()