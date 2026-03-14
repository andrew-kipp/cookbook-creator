@echo off
REM ─────────────────────────────────────────────────────────────────────────
REM  Build script for Recipe and Cookbook Creator
REM  Produces: dist\RecipeAndCookbookCreator.exe
REM ─────────────────────────────────────────────────────────────────────────

echo Installing / updating dependencies...
pip install tkinterdnd2 reportlab requests PyMuPDF pyinstaller anthropic openai google-generativeai Pillow --quiet

echo.
echo Building executable...
pyinstaller cookbook_creator.spec --clean --noconfirm

echo.
if exist "dist\RecipeAndCookbookCreator.exe" (
    echo SUCCESS: dist\RecipeAndCookbookCreator.exe is ready.
) else (
    echo FAILED: dist\RecipeAndCookbookCreator.exe was not created.
    exit /b 1
)
