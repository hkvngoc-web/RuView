@echo off
chcp 65001 >nul 2>&1
:: Refresh PATH to pick up newly installed tools (Rust, etc.)
for /f "tokens=2*" %%A in ('reg query "HKCU\Environment" /v Path 2^>nul') do set "PATH=%%B;%PATH%"
title RuView - He Thong Cam Bien WiFi AI

color 0B

echo.
echo  ========================================================
echo    RUVIEW - He Thong Cam Bien WiFi AI
echo    Uoc Luong Tu The Con Nguoi Qua WiFi
echo    Phien ban: 1.2.0
echo  ========================================================
echo.

echo  [*] Dang kiem tra cac phu thuoc can thiet...
echo.

set "MISSING=0"

where node >nul 2>&1
if %errorlevel% neq 0 (
    echo  [X] Node.js         : CHUA CAI DAT
    echo      ^> Tai tai: https://nodejs.org/
    set "MISSING=1"
) else (
    echo  [OK] Node.js        : Da cai dat
)

where npm >nul 2>&1
if %errorlevel% neq 0 (
    echo  [X] npm             : CHUA CAI DAT
    set "MISSING=1"
) else (
    echo  [OK] npm            : Da cai dat
)

where rustc >nul 2>&1
if %errorlevel% neq 0 (
    echo  [X] Rust            : CHUA CAI DAT
    echo      ^> Tai tai: https://rustup.rs/
    set "MISSING=1"
) else (
    echo  [OK] Rust           : Da cai dat
)

where cargo >nul 2>&1
if %errorlevel% neq 0 (
    echo  [X] Cargo           : CHUA CAI DAT
    set "MISSING=1"
) else (
    echo  [OK] Cargo          : Da cai dat
)

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo  [~] Python          : Chua cai dat (tuy chon)
) else (
    echo  [OK] Python         : Da cai dat
)

echo.

if "%MISSING%"=="1" (
    echo  [CANH BAO] Mot so phu thuoc chua cai dat. Mot so chuc nang co the khong hoat dong.
    echo.
)

:MENU
echo  ========================================================
echo                      MENU CHINH
echo  ========================================================
echo.
echo   [1]  Khoi dong Web UI (trinh duyet)
echo        ^> Mo giao dien web tai localhost
echo.
echo   [2]  Khoi dong Ung Dung Di Dong (Expo)
echo        ^> Chay ung dung React Native/Expo
echo.
echo   [3]  Khoi dong May Chu Cam Bien (Rust)
echo        ^> Khoi chay may chu WiFi sensing
echo.
echo   [4]  Khoi dong Ung Dung May Tinh (Tauri)
echo        ^> Chay ung dung desktop Tauri
echo.
echo   [5]  Chay API Server (Python)
echo        ^> Khoi dong Python API backend
echo.
echo   [6]  Thoat
echo.
echo  ========================================================
echo.
set /p "CHOICE=  Nhap lua chon cua ban [1-6]: "

if "%CHOICE%"=="1" goto OPT_WEB
if "%CHOICE%"=="2" goto OPT_MOBILE
if "%CHOICE%"=="3" goto OPT_SERVER
if "%CHOICE%"=="4" goto OPT_DESKTOP
if "%CHOICE%"=="5" goto OPT_PYTHON
if "%CHOICE%"=="6" goto EXIT

echo.
echo  [X] Lua chon khong hop le. Vui long nhap so tu 1 den 6.
echo.
goto MENU

:: ============================================================
::  [1] WEB UI
:: ============================================================
:OPT_WEB
echo.
echo  --------------------------------------------------------
echo   Dang khoi dong Web UI...
echo  --------------------------------------------------------
echo.

cd /d "%~dp0ui"
if %errorlevel% neq 0 (
    echo  [X] LOI: Khong tim thay thu muc ui/
    echo.
    pause
    cd /d "%~dp0"
    goto MENU
)

echo  [*] Dang mo trinh duyet...
start "" "index.html"
echo  [OK] Da mo index.html trong trinh duyet.
echo.
cd /d "%~dp0"
pause
goto MENU

:: ============================================================
::  [2] EXPO MOBILE
:: ============================================================
:OPT_MOBILE
echo.
echo  --------------------------------------------------------
echo   Dang khoi dong Ung Dung Di Dong (Expo)...
echo  --------------------------------------------------------
echo.

where npx >nul 2>&1
if %errorlevel% neq 0 (
    echo  [X] LOI: Khong tim thay npx. Vui long cai dat Node.js truoc.
    echo      ^> https://nodejs.org/
    echo.
    pause
    goto MENU
)

cd /d "%~dp0ui\mobile"
if %errorlevel% neq 0 (
    echo  [X] LOI: Khong tim thay thu muc ui/mobile/
    echo.
    pause
    cd /d "%~dp0"
    goto MENU
)

if not exist "node_modules" (
    echo  [*] Lan dau chay — dang cai dat phu thuoc...
    call npm install
    if %errorlevel% neq 0 (
        echo  [X] LOI: Cai dat phu thuoc that bai.
        echo.
        pause
        cd /d "%~dp0"
        goto MENU
    )
)

echo  [*] Dang khoi chay Expo... (Nhan Ctrl+C de dung)
echo.
call npx expo start
echo.
echo  [*] Ung dung Expo da dung.
cd /d "%~dp0"
echo.
pause
goto MENU

:: ============================================================
::  [3] RUST SENSING SERVER
:: ============================================================
:OPT_SERVER
echo.
echo  --------------------------------------------------------
echo   Dang khoi dong May Chu Cam Bien WiFi...
echo  --------------------------------------------------------
echo.

where cargo >nul 2>&1
if %errorlevel% neq 0 (
    echo  [X] LOI: Khong tim thay Cargo. Vui long cai dat Rust truoc.
    echo      ^> https://rustup.rs/
    echo.
    pause
    goto MENU
)

cd /d "%~dp0rust-port\wifi-densepose-rs"
if %errorlevel% neq 0 (
    echo  [X] LOI: Khong tim thay thu muc du an Rust.
    echo.
    pause
    cd /d "%~dp0"
    goto MENU
)

echo  [*] Dang bien dich va khoi chay may chu cam bien...
echo  [*] Nhan Ctrl+C de dung may chu.
echo.
cargo run -p wifi-densepose-sensing-server --no-default-features
echo.
echo  [*] May chu da dung.
cd /d "%~dp0"
echo.
pause
goto MENU

:: ============================================================
::  [4] TAURI DESKTOP
:: ============================================================
:OPT_DESKTOP
echo.
echo  --------------------------------------------------------
echo   Dang khoi dong Ung Dung May Tinh (Tauri)...
echo  --------------------------------------------------------
echo.

where cargo >nul 2>&1
if %errorlevel% neq 0 (
    echo  [X] LOI: Khong tim thay Cargo. Vui long cai dat Rust truoc.
    echo      ^> https://rustup.rs/
    echo.
    pause
    goto MENU
)

cd /d "%~dp0rust-port\wifi-densepose-rs"
if %errorlevel% neq 0 (
    echo  [X] LOI: Khong tim thay thu muc du an Rust.
    echo.
    pause
    cd /d "%~dp0"
    goto MENU
)

echo  [*] Dang bien dich va khoi chay ung dung Tauri...
echo  [*] Lan dau co the mat vai phut de bien dich.
echo.
cargo tauri dev
echo.
echo  [*] Ung dung Tauri da dong.
cd /d "%~dp0"
echo.
pause
goto MENU

:: ============================================================
::  [5] PYTHON API SERVER
:: ============================================================
:OPT_PYTHON
echo.
echo  --------------------------------------------------------
echo   Dang khoi dong Python API Server...
echo  --------------------------------------------------------
echo.

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo  [X] LOI: Khong tim thay Python. Vui long cai dat Python truoc.
    echo      ^> https://www.python.org/downloads/
    echo.
    pause
    goto MENU
)

cd /d "%~dp0v1"
if %errorlevel% neq 0 (
    echo  [X] LOI: Khong tim thay thu muc v1/
    echo.
    pause
    cd /d "%~dp0"
    goto MENU
)

if not exist "venv" (
    echo  [*] Dang tao moi truong ao Python...
    python -m venv venv
    echo  [*] Dang cai dat phu thuoc...
    call venv\Scripts\activate.bat
    pip install -r requirements-lock.txt
) else (
    call venv\Scripts\activate.bat
)

echo  [*] Dang khoi chay API server... (Nhan Ctrl+C de dung)
echo.
python -m src.commands.start
echo.
echo  [*] API server da dung.
cd /d "%~dp0"
echo.
pause
goto MENU

:: ============================================================
::  THOAT
:: ============================================================
:EXIT
echo.
echo  ========================================================
echo   Cam on Dai Ca da su dung RuView!
echo   Hen gap lai.
echo  ========================================================
echo.
exit /b 0
