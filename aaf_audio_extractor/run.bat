@echo off
rem Launch AAF Audio Extractor from the development environment (.venv).
rem Any .aaf files or folders given as arguments are added to the queue.
setlocal EnableExtensions
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "PYTHONNOUSERSITE=1"
set "PYTHONHOME="
set "PYTHONPATH="
if not exist "%ROOT%\.venv\Scripts\python.exe" (
    echo .venv not found. Run install.bat first.
    pause
    exit /b 1
)
"%ROOT%\.venv\Scripts\python.exe" "%ROOT%\launcher.py" %*
if errorlevel 1 (
    echo.
    echo The application exited with an error. See the messages above.
    pause
)
