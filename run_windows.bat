@echo off
:: wig-photo-pipeline — run_windows.bat
:: Runs the bg-removal pipeline on Windows using Google Drive for Desktop local paths.
::
:: One-time setup:
::   1. pip install "rembg[cpu]" pillow pillow-heif
::   2. Copy config.example.json -> config.json and set your Drive paths, e.g.:
::        "source": "G:\\My Drive\\ΔΑΜΩΝ\\iphone_photos"
::        "dest":   "H:\\My Drive\\My products"

cd /d "%~dp0"

if not exist config.json (
    echo ERROR: config.json not found.
    echo Copy config.example.json to config.json and set your Google Drive paths.
    pause
    exit /b 1
)

python process_wigs.py
if errorlevel 1 (
    echo.
    echo Something went wrong. See error above.
    pause
    exit /b 1
)

echo.
pause
