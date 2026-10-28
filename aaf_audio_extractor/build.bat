@echo off
rem ===========================================================================
rem  AAF Audio Extractor - run tests and build the Windows executable.
rem  Requires the .venv created by install.bat. Run install.bat first.
rem  Usage: build.bat [/nopause] [/skiptests]
rem ===========================================================================
setlocal EnableExtensions DisableDelayedExpansion

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
cd /d "%ROOT%" || goto :fail

set "VPY=%ROOT%\.venv\Scripts\python.exe"
set "APPDIR=%ROOT%\dist\AAF Audio Extractor"
set "APPEXE=%APPDIR%\AAF Audio Extractor.exe"
set "PAUSE_AT_END=1"
set "RUN_TESTS=1"
:args
if "%~1"=="" goto :args_done
if /i "%~1"=="/nopause" set "PAUSE_AT_END="
if /i "%~1"=="/skiptests" set "RUN_TESTS="
shift
goto :args
:args_done

if not exist "%VPY%" (
    echo  ERROR: .venv not found. Run install.bat first.
    goto :fail
)

if not defined RUN_TESTS goto :build
echo        Running automated tests...
"%VPY%" -m pytest -q -p no:cacheprovider "%ROOT%\tests"
if errorlevel 1 (
    echo  ERROR: automated tests failed; the executable was not built.
    goto :fail
)

:build
echo        Building with PyInstaller...
"%VPY%" -m PyInstaller --noconfirm --clean --log-level WARN --distpath "%ROOT%\dist" --workpath "%ROOT%\build" "%ROOT%\aaf_audio_extractor.spec"
if errorlevel 1 (
    echo  ERROR: PyInstaller failed.
    goto :fail
)
if not exist "%APPEXE%" (
    echo  ERROR: the build finished but the executable is missing.
    goto :fail
)
if not exist "%APPDIR%\_internal\resources\fonts\Inter-Regular.ttf" (
    echo  ERROR: bundled resources are missing from the build.
    goto :fail
)
copy /y "%ROOT%\README.md" "%APPDIR%\README.md" >nul
copy /y "%ROOT%\docs\OPERATOR_GUIDE.md" "%APPDIR%\OPERATOR_GUIDE.md" >nul
echo        Built: "%APPEXE%"
if defined PAUSE_AT_END pause
exit /b 0

:fail
if defined PAUSE_AT_END pause
exit /b 1
