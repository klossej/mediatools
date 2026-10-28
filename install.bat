@echo off
rem ===========================================================================
rem  AAF Audio Extractor - one-step setup and build for Windows.
rem
rem  Double-click this file. It will:
rem    1. find Python 3.12 or 3.13 (64-bit), or offer to install Python 3.12
rem       from python.org for the current user (no administrator rights);
rem    2. create/refresh the local virtual environment in .venv;
rem    3. install the pinned dependencies from requirements-build.txt;
rem    4. verify the toolchain, run the automated tests and build
rem       "dist\AAF Audio Extractor\AAF Audio Extractor.exe" (via build.bat).
rem
rem  Safe to run again at any time. It never touches the application's saved
rem  settings (stored per user by Windows) and never runs downloaded scripts.
rem ===========================================================================
setlocal EnableExtensions DisableDelayedExpansion

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
cd /d "%ROOT%" || goto :fail_root

set "VENV=%ROOT%\.venv"
set "VPY=%VENV%\Scripts\python.exe"
set "PY_VERSION=3.12.10"
set "PY_INSTALLER=python-%PY_VERSION%-amd64.exe"
set "PY_URL=https://www.python.org/ftp/python/%PY_VERSION%/%PY_INSTALLER%"
set "PY_SHA256=67b5635e80ea51072b87941312d00ec8927c4db9ba18938f7ad2d27b328b95fb"
set "LOGDIR=%ROOT%\logs"
set "LOG=%LOGDIR%\install.log"

if not exist "%LOGDIR%" mkdir "%LOGDIR%"
echo.
echo  AAF Audio Extractor - setup and build
echo  Project folder: "%ROOT%"
echo  Detailed output is written to "%LOG%"
echo.
echo ==== install.bat started %DATE% %TIME% ==== > "%LOG%"

rem ---------------------------------------------------------------- 1. Python
echo [1/5] Looking for Python 3.12 or 3.13 (64-bit)...
set "BASEPY="
call :find_python
if defined BASEPY goto :have_python

echo.
echo  No compatible Python was found on this computer.
echo  Setup can download the official Python %PY_VERSION% installer from python.org,
echo  verify its digital signature and checksum, and install it for your user
echo  account only (no administrator rights needed).
echo.
choice /C YN /M "Download and install Python %PY_VERSION% now"
if errorlevel 2 goto :fail_nopython
call :install_python || goto :fail
call :find_python
if not defined BASEPY goto :fail_nopython

:have_python
for /f "delims=" %%V in ('call "%BASEPY%" -c "import sys; print(sys.version.split()[0])"') do set "BASEPY_VER=%%V"
echo        Using Python %BASEPY_VER%: "%BASEPY%"
echo Using Python %BASEPY_VER% at %BASEPY% >> "%LOG%"

rem ------------------------------------------------------- 2. virtual env
echo [2/5] Preparing virtual environment (.venv)...
if exist "%VPY%" (
    "%VPY%" -c "import sys; assert sys.version_info[:2] in ((3,12),(3,13))" >nul 2>&1 || (
        echo        Existing .venv is unusable or uses an unsupported Python; recreating it.
        rmdir /s /q "%VENV%"
    )
)
if not exist "%VPY%" (
    "%BASEPY%" -m venv "%VENV%" >> "%LOG%" 2>&1 || goto :fail_venv
)
"%VPY%" -m pip --version >nul 2>&1 || (
    "%VPY%" -m ensurepip --upgrade >> "%LOG%" 2>&1 || goto :fail_venv
)

rem ------------------------------------------------------- 3. dependencies
echo [3/5] Installing pinned dependencies (this can take a few minutes)...
"%VPY%" -m pip install --disable-pip-version-check --upgrade pip >> "%LOG%" 2>&1 || goto :fail_pip
"%VPY%" -m pip install --disable-pip-version-check --only-binary=:all: -r "%ROOT%\requirements-build.txt" >> "%LOG%" 2>&1 || goto :fail_pip

rem ------------------------------------------------------- 4. verification
echo [4/5] Verifying build tools...
"%VPY%" -c "import PySide6.QtWidgets, numpy, aaf2, PyInstaller, pytest; print('PySide6', PySide6.__version__, '| numpy', numpy.__version__, '| pyaaf2 ok | PyInstaller', PyInstaller.__version__)" || goto :fail_verify

rem ------------------------------------------------------- 5. test and build
echo [5/5] Running tests and building the executable...
call "%ROOT%\build.bat" /nopause
if errorlevel 1 goto :fail_build

echo.
echo  ============================================================
echo   SUCCESS. The application is ready:
echo   "%ROOT%\dist\AAF Audio Extractor\AAF Audio Extractor.exe"
echo.
echo   Copy the whole "dist\AAF Audio Extractor" folder to any
echo   Windows PC; Python is not needed there.
echo  ============================================================
echo.
echo ==== install.bat finished OK %DATE% %TIME% ==== >> "%LOG%"
pause
exit /b 0


rem ===========================================================================
rem  Subroutines
rem ===========================================================================

:find_python
rem Sets BASEPY to the full path of a 64-bit CPython 3.12/3.13, preferring 3.12.
set "BASEPY="
for %%T in (3.12 3.13) do (
    if not defined BASEPY call :try_launcher %%T
)
if not defined BASEPY call :try_exe "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined BASEPY call :try_exe "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined BASEPY call :try_exe "%ProgramFiles%\Python312\python.exe"
if not defined BASEPY call :try_exe "%ProgramFiles%\Python313\python.exe"
if not defined BASEPY (
    for /f "delims=" %%P in ('where python 2^>nul') do (
        if not defined BASEPY call :try_exe "%%P"
    )
)
exit /b 0

:try_launcher
where py >nul 2>&1 || exit /b 0
for /f "delims=" %%E in ('py -%1 -c "import sys; print(sys.executable)" 2^>nul') do call :try_exe "%%E"
exit /b 0

:try_exe
if not exist "%~1" exit /b 0
rem The Microsoft Store alias in WindowsApps is not a real interpreter.
echo %~1 | find /i "\WindowsApps\" >nul && exit /b 0
"%~1" -c "import sys, struct; sys.exit(0 if sys.version_info[:2] in ((3,12),(3,13)) and struct.calcsize('P') == 8 and sys.implementation.name == 'cpython' else 1)" >nul 2>&1
if errorlevel 1 exit /b 0
set "BASEPY=%~1"
exit /b 0

:install_python
set "DL=%TEMP%\aaf-extractor-setup"
if not exist "%DL%" mkdir "%DL%"
set "PYEXE=%DL%\%PY_INSTALLER%"
echo        Downloading %PY_URL%
if exist "%PYEXE%" del /f /q "%PYEXE%"
where curl.exe >nul 2>&1 && (
    curl.exe --fail --location --silent --show-error --output "%PYEXE%" "%PY_URL%"
) || (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Uri '%PY_URL%' -OutFile '%PYEXE%'"
)
if not exist "%PYEXE%" (
    echo  ERROR: download failed. Check the internet connection or install Python %PY_VERSION% manually from python.org.
    exit /b 1
)
echo        Verifying SHA-256 checksum...
set "GOTHASH="
for /f "delims=" %%H in ('powershell -NoProfile -Command "(Get-FileHash -Algorithm SHA256 -LiteralPath '%PYEXE%').Hash.ToLower()"') do set "GOTHASH=%%H"
if /i not "%GOTHASH%"=="%PY_SHA256%" (
    echo  ERROR: checksum mismatch for the downloaded installer. It will not be run.
    echo         expected %PY_SHA256%
    echo         got      %GOTHASH%
    del /f /q "%PYEXE%"
    exit /b 1
)
echo        Verifying digital signature (Python Software Foundation)...
powershell -NoProfile -Command "$s = Get-AuthenticodeSignature -LiteralPath '%PYEXE%'; if ($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject -notmatch 'Python Software Foundation') { Write-Host ('  signature: ' + $s.Status + ' ' + $s.SignerCertificate.Subject); exit 1 }"
if errorlevel 1 (
    echo  ERROR: the installer's signature could not be verified. It will not be run.
    del /f /q "%PYEXE%"
    exit /b 1
)
echo        Installing Python %PY_VERSION% for the current user...
"%PYEXE%" /passive InstallAllUsers=0 PrependPath=0 Include_launcher=1 InstallLauncherAllUsers=0 Include_test=0 Include_doc=0 Shortcuts=0
if errorlevel 1 (
    echo  ERROR: the Python installer reported a failure.
    exit /b 1
)
del /f /q "%PYEXE%" >nul 2>&1
exit /b 0


rem ===========================================================================
rem  Failure exits - keep the window open so the message can be read.
rem ===========================================================================

:fail_root
echo  ERROR: cannot change to the project folder.
goto :fail

:fail_nopython
echo.
echo  ERROR: Python 3.12 or 3.13 (64-bit) is required to build the application.
echo         Install it from https://www.python.org/downloads/windows/ and run install.bat again.
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
pause
exit /b 1
