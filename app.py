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


# ── Cookbook generator ────────────────────────────────────────────────────────

def create_cookbook(recipes_dir, output_path, filter_mode="all", image_mode="none", progress_cb=None):
    """
    Generate a single multi-page PDF cookbook from JSON recipe files.

    recipes_dir  : folder containing .json recipe files (and a Recipe Images subfolder)
    output_path  : full path for the output PDF
    filter_mode  : "all" | "4_and_5_stars" | "5_stars"
    image_mode   : "grouped" | "adjacent" | "none"
    progress_cb  : optional callable(str)
    """
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, PageBreak
    from RecipeFormatter import (
        get_recipe_styles,
        format_recipe_first_page,
        format_recipe_second_page,
        LEFT_RIGHT_MARGIN,
        PAGE_TOP_MARGIN,
        PAGE_BOTTOM_MARGIN,
    )

    def log(msg):
        if progress_cb:
            progress_cb(msg)
        else:
            print(msg)

    import re as _re

    recipes_dir = Path(recipes_dir)
    images_dir  = recipes_dir / IMAGES_SUBDIR

    def _base_stem(stem):
        """Strip trailing '(N Stars)' from a filename stem."""
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
        return True  # "all"

    # Collect JSON recipes
    json_files = sorted(recipes_dir.glob("*.json"))
    json_stems = {jf.stem for jf in json_files}
    log(f"Found {len(json_files)} JSON file(s)")

    # Collect PDF-only recipes (no matching JSON)
    pdf_only = sorted(
        pdf for pdf in recipes_dir.glob("*.pdf")
        if _base_stem(pdf.stem) not in json_stems
    )
    if pdf_only:
        log(f"Found {len(pdf_only)} PDF-only recipe(s)")

    # Apply filter and build recipe list
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

    styles = get_recipe_styles()

    # Build the full story
    story = []
    include_image = image_mode in ("grouped", "adjacent")

    for idx, (jf, recipe_data) in enumerate(filtered):
        recipe_name = recipe_data.get('name', _base_stem(jf.stem))
        rating = recipe_data.get('rating', '')
        log(f"  Adding ({idx+1}/{len(filtered)}): {recipe_name}")

        # Find associated image
        image_path = None
        if include_image:
            safe_name = "".join(c for c in recipe_name if c.isalnum() or c in (' ', '_', '-')).strip()
            suffix_str = f" ({rating} stars)" if rating not in (None, '') else ""
            for ext in ('.jpg', '.jpeg', '.png', '.gif', '.webp'):
                candidate = images_dir / f"{safe_name}{suffix_str}{ext}"
                if candidate.exists():
                    image_path = str(candidate)
                    break
            if not image_path:
                # Prefix match fallback
                for f in images_dir.iterdir() if images_dir.exists() else []:
                    if f.is_file() and f.stem.lower().startswith(safe_name.lower()):
                        image_path = str(f)
                        break

            if not image_path:
                # Try to download from image_url in the JSON
                image_url = recipe_data.get('image_url', '')
                if image_url:
                    log(f"    No local image found; downloading from image_url...")
                    try:
                        from JSONToPDFRecipe import download_recipe_image
                        images_dir.mkdir(parents=True, exist_ok=True)
                        downloaded = download_recipe_image(
                            image_url, recipe_name, str(images_dir), rating or None
                        )
                        if downloaded:
                            image_path = downloaded
                            log(f"    Downloaded image: {os.path.basename(downloaded)}")
                        else:
                            log(f"    Could not download image for: {recipe_name}")
                    except Exception as e:
                        log(f"    Image download failed for {recipe_name}: {e}")

        first_page_elements, overflow_ingredients, overflow_right, overflow_directions_count = \
            format_recipe_first_page(recipe_data, styles)
        story.extend(first_page_elements)

        second_page_elements = format_recipe_second_page(
            recipe_data, image_path, styles,
            overflow_ingredients, overflow_right, overflow_directions_count,
            include_image=include_image,
        )
        story.extend(second_page_elements)

        # Add page break between recipes (not after the last one)
        if idx < len(filtered) - 1:
            story.append(PageBreak())

    # Build the PDF
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        leftMargin=LEFT_RIGHT_MARGIN,
        rightMargin=LEFT_RIGHT_MARGIN,
        topMargin=PAGE_TOP_MARGIN,
        bottomMargin=PAGE_BOTTOM_MARGIN,
    )
    doc.build(story)
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
