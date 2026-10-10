@echo off
rem Builds dist\ChoboPDF.exe (single file, no console window).
setlocal
cd /d "%~dp0"
.venv\Scripts\python -m pip install --quiet --disable-pip-version-check pyinstaller || exit /b 1
.venv\Scripts\python -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name ChoboPDF --paths . ^
    --collect-all pypdfium2_raw --collect-data pypdfium2 ^
    chobopdf\__main__.py || exit /b 1
echo.
echo Built dist\ChoboPDF.exe
