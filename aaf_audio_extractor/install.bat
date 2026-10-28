@echo off
rem ===========================================================================
rem  AAF Audio Extractor - one-step setup and build for Windows.
rem
rem  Double-click this file. It will:
rem    1. set up a private copy of Python 3.12 inside this folder (.python),
rem       downloaded once from the official python.org NuGet package and
rem       verified (SHA-256 + Python Software Foundation signature);
rem    2. create/refresh the local virtual environment in .venv from it;
rem    3. install the pinned dependencies from requirements-build.txt;
rem    4. verify the toolchain, run the automated tests and build
rem       "dist\AAF Audio Extractor\AAF Audio Extractor.exe" (via build.bat).
rem
rem  Nothing is installed into Windows: no registry entries, no PATH changes,
rem  no Start menu items, no "Programs and Features" entry. Python, packages and
rem  caches all live in this folder, so deleting the folder removes everything.
rem  An existing system Python is neither used nor touched.
rem
rem  Safe to run again at any time. Use "install.bat /yes" to skip the prompt.
rem ===========================================================================
setlocal EnableExtensions DisableDelayedExpansion

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
cd /d "%ROOT%" || goto :fail_root

set "PYDIR=%ROOT%\.python"
set "PYEXE=%PYDIR%\python.exe"
set "VENV=%ROOT%\.venv"
set "VPY=%VENV%\Scripts\python.exe"
set "CACHE=%ROOT%\.cache"
set "PY_VERSION=3.12.10"
set "PY_PACKAGE=python.%PY_VERSION%.nupkg"
set "PY_URL=https://www.nuget.org/api/v2/package/python/%PY_VERSION%"
set "PY_SHA256=0eb85c2dfccccf1b17352de4c397f69194035b7d37149eacc16f1147d93de3b8"
set "LOGDIR=%ROOT%\logs"
set "LOG=%LOGDIR%\install.log"
set "ASSUME_YES="
if /i "%~1"=="/yes" set "ASSUME_YES=1"

rem Keep every cache inside this folder and ignore per-user site-packages.
set "PIP_CACHE_DIR=%CACHE%\pip"
set "PYINSTALLER_CONFIG_DIR=%CACHE%\pyinstaller"
set "PIP_DISABLE_PIP_VERSION_CHECK=1"
set "PYTHONNOUSERSITE=1"
set "PYTHONHOME="
set "PYTHONPATH="

if not exist "%LOGDIR%" mkdir "%LOGDIR%"
if not exist "%CACHE%" mkdir "%CACHE%"
echo.
echo  AAF Audio Extractor - setup and build
echo  Project folder: "%ROOT%"
echo  Detailed output is written to "%LOG%"
echo.
echo ==== install.bat started %DATE% %TIME% ==== > "%LOG%"

rem ------------------------------------------------- 1. folder-local Python
echo [1/5] Checking the private Python in .python ...
call :check_local_python
if not errorlevel 1 goto :have_python

if exist "%PYDIR%" (
    echo        The existing .python folder is incomplete; it will be replaced.
)
echo.
echo  Setup will download the official Python %PY_VERSION% package (about 15 MB)
echo  from python.org's NuGet feed and unpack it into this folder only.
echo  Nothing is installed into Windows.
echo.
if defined ASSUME_YES goto :do_download
choice /C YN /M "Download Python %PY_VERSION% into this folder now"
if errorlevel 2 goto :fail_nopython
:do_download
call :fetch_python || goto :fail
call :check_local_python || goto :fail_python_broken

:have_python
for /f "delims=" %%V in ('call "%PYEXE%" -c "import sys; print(sys.version.split()[0])"') do set "PY_VER=%%V"
echo        Using private Python %PY_VER%: "%PYEXE%"
echo Using Python %PY_VER% at %PYEXE% >> "%LOG%"

rem ------------------------------------------------------- 2. virtual env
echo [2/5] Preparing virtual environment (.venv) ...
if not exist "%VPY%" goto :make_venv
rem Recreate the venv if it was made from another Python (e.g. a system install).
"%VPY%" -c "import os, sys; sys.exit(0 if os.path.normcase(os.path.realpath(sys.base_prefix)) == os.path.normcase(os.path.realpath(sys.argv[1])) else 1)" "%PYDIR%" >nul 2>&1
if not errorlevel 1 goto :venv_ready
echo        Existing .venv was not made from the private Python; recreating it.
rmdir /s /q "%VENV%"
:make_venv
"%PYEXE%" -m venv "%VENV%" >> "%LOG%" 2>&1 || goto :fail_venv
:venv_ready
"%VPY%" -m pip --version >nul 2>&1 || (
    "%VPY%" -m ensurepip --upgrade >> "%LOG%" 2>&1 || goto :fail_venv
)

rem ------------------------------------------------------- 3. dependencies
echo [3/5] Installing pinned dependencies (this can take a few minutes) ...
"%VPY%" -m pip install --upgrade pip >> "%LOG%" 2>&1 || goto :fail_pip
"%VPY%" -m pip install --only-binary=:all: -r "%ROOT%\requirements-build.txt" >> "%LOG%" 2>&1 || goto :fail_pip

rem ------------------------------------------------------- 4. verification
echo [4/5] Verifying build tools ...
"%VPY%" -c "import PySide6.QtWidgets, numpy, aaf2, PyInstaller, pytest; print('       PySide6', PySide6.__version__, '| numpy', numpy.__version__, '| pyaaf2 ok | PyInstaller', PyInstaller.__version__)" || goto :fail_verify

rem ------------------------------------------------------- 5. test and build
echo [5/5] Running tests and building the executable ...
call "%ROOT%\build.bat" /nopause
if errorlevel 1 goto :fail_build

echo.
echo  ============================================================
echo   SUCCESS. The application is ready:
echo   "%ROOT%\dist\AAF Audio Extractor\AAF Audio Extractor.exe"
echo.
echo   Copy the whole "dist\AAF Audio Extractor" folder to any
echo   Windows PC; Python is not needed there.
echo.
echo   To remove everything, just delete this folder.
echo  ============================================================
echo.
echo ==== install.bat finished OK %DATE% %TIME% ==== >> "%LOG%"
if not defined ASSUME_YES pause
exit /b 0


rem ===========================================================================
rem  Subroutines
rem ===========================================================================

:check_local_python
rem errorlevel 0 when .python holds a working 64-bit CPython 3.12 with venv and pip.
if not exist "%PYEXE%" exit /b 1
"%PYEXE%" -c "import sys, struct, venv, ensurepip; sys.exit(0 if sys.version_info[:2] == (3, 12) and struct.calcsize('P') == 8 else 1)" >nul 2>&1
exit /b %errorlevel%

:fetch_python
set "PKG=%CACHE%\%PY_PACKAGE%"
set "UNPACK=%CACHE%\python-unpack"
echo        Downloading %PY_URL%
if exist "%PKG%" del /f /q "%PKG%"
where curl.exe >nul 2>&1 && (
    curl.exe --fail --location --silent --show-error --output "%PKG%" "%PY_URL%"
) || (
    powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Uri '%PY_URL%' -OutFile '%PKG%'"
)
if not exist "%PKG%" (
    echo  ERROR: download failed. Check the internet connection and run install.bat again.
    exit /b 1
)
echo        Verifying SHA-256 checksum ...
set "GOTHASH="
for /f "delims=" %%H in ('powershell -NoProfile -Command "(Get-FileHash -Algorithm SHA256 -LiteralPath '%PKG%').Hash.ToLower()"') do set "GOTHASH=%%H"
if /i not "%GOTHASH%"=="%PY_SHA256%" (
    echo  ERROR: checksum mismatch for the downloaded package. It will not be used.
    echo         expected %PY_SHA256%
    echo         got      %GOTHASH%
    del /f /q "%PKG%"
    exit /b 1
)
echo        Unpacking into .python ...
if exist "%UNPACK%" rmdir /s /q "%UNPACK%"
mkdir "%UNPACK%"
rem The .nupkg is a zip archive; Windows 10/11 tar.exe reads zip files.
tar.exe -xf "%PKG%" -C "%UNPACK%" >> "%LOG%" 2>&1
if errorlevel 1 (
    copy /y "%PKG%" "%UNPACK%\package.zip" >nul
    powershell -NoProfile -Command "Expand-Archive -LiteralPath '%UNPACK%\package.zip' -DestinationPath '%UNPACK%' -Force" >> "%LOG%" 2>&1
)
if not exist "%UNPACK%\tools\python.exe" (
    echo  ERROR: the package could not be unpacked. See "%LOG%".
    exit /b 1
)
echo        Verifying digital signature of python.exe (Python Software Foundation) ...
powershell -NoProfile -Command "$s = Get-AuthenticodeSignature -LiteralPath '%UNPACK%\tools\python.exe'; if ($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject -notmatch 'Python Software Foundation') { Write-Host ('  signature: ' + $s.Status + ' ' + $s.SignerCertificate.Subject); exit 1 }"
if errorlevel 1 (
    echo  ERROR: python.exe is not validly signed by the Python Software Foundation. It will not be used.
    rmdir /s /q "%UNPACK%"
    exit /b 1
)
if exist "%PYDIR%" rmdir /s /q "%PYDIR%"
move "%UNPACK%\tools" "%PYDIR%" >nul || (
    echo  ERROR: could not move the unpacked Python into place.
    exit /b 1
)
rmdir /s /q "%UNPACK%"
del /f /q "%PKG%"
rem An old .venv belonged to a different Python; it is rebuilt in step 2.
exit /b 0


rem ===========================================================================
rem  Failure exits - keep the window open so the message can be read.
rem ===========================================================================

:fail_root
echo  ERROR: cannot change to the project folder.
goto :fail

:fail_nopython
echo.
echo  Setup was cancelled. Python is needed in this folder to build the application.
goto :fail

:fail_python_broken
echo  ERROR: the private Python in "%PYDIR%" does not work. Delete the .python folder and try again.
goto :fail

:fail_venv
echo  ERROR: could not create the virtual environment in "%VENV%". See "%LOG%".
goto :fail

:fail_pip
echo  ERROR: dependency installation failed. The last lines of the log:
powershell -NoProfile -Command "Get-Content -LiteralPath '%LOG%' -Tail 25"
goto :fail

:fail_verify
echo  ERROR: dependencies are installed but cannot be imported. See the message above.
goto :fail

:fail_build
echo  ERROR: tests or build failed. See the messages above.
goto :fail

:fail
echo.
echo  ============================================================
echo   BUILD FAILED - nothing was changed outside this folder.
echo   Fix the problem above and run install.bat again.
echo  ============================================================
echo ==== install.bat FAILED %DATE% %TIME% ==== >> "%LOG%"
echo.
if not defined ASSUME_YES pause
exit /b 1
