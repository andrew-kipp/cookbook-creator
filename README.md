# Recipe and Cookbook Creator

> **Work in progress** — features and documentation will continue to evolve.

A Python-based toolkit for converting, formatting, and managing cooking recipes. It can read recipe exports from [Paprika Recipe Manager 3](https://www.paprikaapp.com/), convert them to formatted PDF files, and compile them into a single cookbook PDF. A GUI application ties everything together for everyday use.

---

## Features

- **Extract Paprika exports** — unpack `.paprikarecipes` / `.paprikarecipe` files into individual JSON recipe files
- **Generate recipe PDFs** — convert JSON recipe files into consistently formatted, print-ready PDFs
- **Reverse PDF to JSON** — extract recipe data back out of a formatted PDF into a JSON file
- **Create Paprika import packages** — bundle PDF-only recipes back into a `.paprikarecipes` file that can be imported into Paprika
- **Compile a cookbook** — combine any selection of recipes into a single multi-page PDF, with optional star-rating filters

---

## Requirements

Python 3.10+ and the following packages (install with `pip`):

```
pip install reportlab requests PyMuPDF tkinterdnd2 pyinstaller
```

---

## Files Overview

| File | Purpose |
|------|---------|
| `app.py` | Main GUI application — run this to launch the desktop tool |
| `PaprikaExtract.py` | Extracts `.paprikarecipes` / `.paprikarecipe` files into JSON |
| `JSONToPDFRecipe.py` | Converts JSON recipe files into formatted PDFs |
| `PDFToJSONRecipe.py` | Extracts recipe data from a formatted PDF back into JSON |
| `RecipeFormatter.py` | ReportLab layout and styling used by the PDF scripts |
| `CreatePaprikaImport.py` | Builds a `.paprikarecipes` import package from PDF-only recipes |
| `cookbook_creator.spec` | PyInstaller spec for building a standalone `.exe` |
| `build.bat` | Convenience script — installs dependencies and builds the `.exe` |

---

## Running the GUI

```bash
python app.py
```

The window is titled **Recipe and Cookbook Creator**. It has four sections:

1. **Files** — Drag and drop files onto the target zone, or click **Browse Files...** to select them. Supported types: `.paprikarecipes`, `.paprikarecipe`, `.pdf`, `.json`. Click **Clear Files** to reset the list.

2. **Output Folder** — Select the folder where output files (JSON, PDF) should be saved.

3. **Actions** — Three buttons trigger the main conversion tasks:
   - **Create Recipe PDFs** — generates PDFs from JSON files in the output folder (or from specific JSON files added to the file list)
   - **Create JSON Recipe Files** — extracts Paprika files to JSON, or converts selected PDFs to JSON
   - **Create Paprikarecipes File** — packages PDF-only recipes into a Paprika-importable bundle

4. **Cookbook Creator** — Compiles recipes from the output folder into a single PDF:
   - **Filter**: All Recipes / 4 & 5 Stars / 5 Stars
   - **Format**: Grouped Images / Image Adjacent to Recipe / No Images
   - Click **Create Cookbook** to generate `Cookbook.pdf` in the output folder

Progress and errors are shown in the **Status Log** at the bottom.

---

## Running Scripts from the Command Line

Each script can also be run directly. Edit the `WORKSPACE_DIR` constant near the top of each file to point to your working folder before running.

```bash
# Extract a Paprika export to JSON
python PaprikaExtract.py

# Convert JSON recipes to PDFs
python JSONToPDFRecipe.py

# Convert a single PDF back to JSON
python PDFToJSONRecipe.py "All Recipes/My Recipe (3 Stars).pdf"

# Build a Paprika import package from PDF-only recipes
python CreatePaprikaImport.py
```

---

## Folder Structure

After running the scripts the working folder typically looks like this:

```
cookbook-creator/
├── All Recipes/                  ← JSON and PDF recipe files
│   ├── Recipe Name.json
│   ├── Recipe Name (3 Stars).pdf
│   └── Recipe Images/            ← Downloaded recipe images
│       └── Recipe Name (3 stars).jpg
├── Paprika Recipes to Import/    ← Output from CreatePaprikaImport
│   └── New Recipes.paprikarecipes
├── app.py
├── build.bat
└── ...
```

---

## Building the Standalone .exe

To produce a single `RecipeAndCookbookCreator.exe` that runs on any Windows machine without Python installed:

```bat
build.bat
```

The finished executable is placed in `dist\RecipeAndCookbookCreator.exe`.

---

## Recipe File Naming Conventions

| Type | Pattern | Example |
|------|---------|---------|
| JSON | `Recipe Name.json` | `Apple Walnut Salad.json` |
| PDF | `Recipe Name (X Stars).pdf` | `Apple Walnut Salad (5 Stars).pdf` |
| Image | `Recipe Name (X stars).jpg` | `Apple Walnut Salad (5 stars).jpg` |
