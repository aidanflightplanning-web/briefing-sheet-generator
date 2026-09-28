@echo off
rem Builds "Briefing Sheet Generator.exe" into .\dist - it runs on PCs without Python.
rem Needs PyInstaller (py -m pip install pyinstaller). Build files go to %TEMP% and are removed.
setlocal
cd /d "%~dp0"
set "WORK=%TEMP%\BriefingSheetGenerator_build"

py -m PyInstaller --noconfirm --onefile --windowed --name "Briefing Sheet Generator" ^
    --icon "%~dp0briefsheet\assets\icon.ico" ^
    --add-data "%~dp0briefsheet\assets;briefsheet\assets" ^
    --distpath "%~dp0dist" --workpath "%WORK%" --specpath "%WORK%" ^
    --exclude-module numpy --exclude-module pandas --exclude-module matplotlib --exclude-module scipy ^
    --exclude-module PyQt6 --exclude-module streamlit --exclude-module pyarrow --exclude-module sklearn ^
    --exclude-module statsmodels --exclude-module pdfplumber --exclude-module IPython ^
    "%~dp0Briefing Sheet Generator.pyw"
if errorlevel 1 (
    echo.
    echo Build FAILED - see the messages above.
    exit /b 1
)

rmdir /s /q "%WORK%" 2>nul
echo.
echo Built: %~dp0dist\Briefing Sheet Generator.exe
