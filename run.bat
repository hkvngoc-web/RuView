@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
title RuView - Hệ Thống Cảm Biến WiFi

color 0B

:: ============================================================
::  ██████╗ ██╗   ██╗██╗   ██╗██╗███████╗██╗    ██╗
::  ██╔══██╗██║   ██║██║   ██║██║██╔════╝██║    ██║
::  ██████╔╝██║   ██║██║   ██║██║█████╗  ██║ █╗ ██║
::  ██╔══██╗██║   ██║╚██╗ ██╔╝██║██╔══╝  ██║███╗██║
::  ██║  ██║╚██████╔╝ ╚████╔╝ ██║███████╗╚███╔███╔╝
::  ╚═╝  ╚═╝ ╚═════╝   ╚═══╝  ╚═╝╚══════╝ ╚══╝╚══╝
:: ============================================================
::  Hệ Thống Ước Lượng Tư Thế Con Người Qua WiFi
::  Sử dụng Thông Tin Trạng Thái Kênh (CSI)
:: ============================================================

echo.
echo  ╔══════════════════════════════════════════════════════════╗
echo  ║                                                          ║
echo  ║   ██████╗ ██╗   ██╗██╗   ██╗██╗███████╗██╗    ██╗       ║
echo  ║   ██╔══██╗██║   ██║██║   ██║██║██╔════╝██║    ██║       ║
echo  ║   ██████╔╝██║   ██║██║   ██║██║█████╗  ██║ █╗ ██║       ║
echo  ║   ██╔══██╗██║   ██║╚██╗ ██╔╝██║██╔══╝  ██║███╗██║       ║
echo  ║   ██║  ██║╚██████╔╝ ╚████╔╝ ██║███████╗╚███╔███╔╝       ║
echo  ║   ╚═╝  ╚═╝ ╚═════╝   ╚═══╝  ╚═╝╚══════╝ ╚══╝╚══╝       ║
echo  ║                                                          ║
echo  ║   Hệ Thống Cảm Biến WiFi - Ước Lượng Tư Thế            ║
echo  ║   Phiên bản: 1.2.0                                      ║
echo  ║                                                          ║
echo  ╚══════════════════════════════════════════════════════════╝
echo.

:: ============================================================
::  KIỂM TRA PHỤ THUỘC
:: ============================================================
echo  [*] Đang kiểm tra các phụ thuộc cần thiết...
echo.

set "MISSING=0"

:: Kiểm tra Node.js
where node >nul 2>&1
if %errorlevel% neq 0 (
    echo  [✗] Node.js         : CHƯA CÀI ĐẶT
    echo      ^> Tải tại: https://nodejs.org/
    set "MISSING=1"
) else (
    for /f "tokens=*" %%v in ('node --version 2^>nul') do set "NODE_VER=%%v"
    echo  [✓] Node.js         : !NODE_VER!
)

:: Kiểm tra npm
where npm >nul 2>&1
if %errorlevel% neq 0 (
    echo  [✗] npm             : CHƯA CÀI ĐẶT
    echo      ^> Đi kèm với Node.js
    set "MISSING=1"
) else (
    for /f "tokens=*" %%v in ('npm --version 2^>nul') do set "NPM_VER=%%v"
    echo  [✓] npm             : !NPM_VER!
)

:: Kiểm tra Rust
where rustc >nul 2>&1
if %errorlevel% neq 0 (
    echo  [✗] Rust ^(rustc^)    : CHƯA CÀI ĐẶT
    echo      ^> Tải tại: https://rustup.rs/
    set "MISSING=1"
) else (
    for /f "tokens=*" %%v in ('rustc --version 2^>nul') do set "RUST_VER=%%v"
    echo  [✓] Rust            : !RUST_VER!
)

:: Kiểm tra Cargo
where cargo >nul 2>&1
if %errorlevel% neq 0 (
    echo  [✗] Cargo           : CHƯA CÀI ĐẶT
    echo      ^> Đi kèm với Rust
    set "MISSING=1"
) else (
    for /f "tokens=*" %%v in ('cargo --version 2^>nul') do set "CARGO_VER=%%v"
    echo  [✓] Cargo           : !CARGO_VER!
)

:: Kiểm tra Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    where python3 >nul 2>&1
    if %errorlevel% neq 0 (
        echo  [~] Python          : CHƯA CÀI ĐẶT ^(tùy chọn^)
    ) else (
        for /f "tokens=*" %%v in ('python3 --version 2^>nul') do set "PY_VER=%%v"
        echo  [✓] Python          : !PY_VER!
    )
) else (
    for /f "tokens=*" %%v in ('python --version 2^>nul') do set "PY_VER=%%v"
    echo  [✓] Python          : !PY_VER!
)

echo.

if "%MISSING%"=="1" (
    echo  ╔══════════════════════════════════════════════════════════╗
    echo  ║  [!] CẢNH BÁO: Một số phụ thuộc chưa được cài đặt.     ║
    echo  ║      Một số tùy chọn có thể không hoạt động.            ║
    echo  ╚══════════════════════════════════════════════════════════╝
    echo.
)

:: ============================================================
::  MENU CHÍNH
:: ============================================================
:MENU
echo  ╔══════════════════════════════════════════════════════════╗
echo  ║                    MENU CHÍNH                            ║
echo  ╠══════════════════════════════════════════════════════════╣
echo  ║                                                          ║
echo  ║   [1]  Khởi động Máy Chủ Cảm Biến                      ║
echo  ║        ^> Khởi chạy máy chủ WiFi sensing Rust            ║
echo  ║                                                          ║
echo  ║   [2]  Khởi động Ứng Dụng Di Động ^(Expo^)                ║
echo  ║        ^> Chạy ứng dụng React Native/Expo                ║
echo  ║                                                          ║
echo  ║   [3]  Khởi động Ứng Dụng Máy Tính ^(Tauri^)             ║
echo  ║        ^> Chạy ứng dụng desktop Tauri                    ║
echo  ║                                                          ║
echo  ║   [4]  Chạy Bộ Kiểm Thử Rust                           ║
echo  ║        ^> cargo test --workspace --no-default-features    ║
echo  ║                                                          ║
echo  ║   [5]  Thoát                                            ║
echo  ║                                                          ║
echo  ╚══════════════════════════════════════════════════════════╝
echo.
set /p "CHOICE=  Nhập lựa chọn của bạn [1-5]: "

if "%CHOICE%"=="1" goto OPT_SERVER
if "%CHOICE%"=="2" goto OPT_MOBILE
if "%CHOICE%"=="3" goto OPT_DESKTOP
if "%CHOICE%"=="4" goto OPT_TEST
if "%CHOICE%"=="5" goto EXIT

echo.
echo  [✗] Lựa chọn không hợp lệ. Vui lòng nhập số từ 1 đến 5.
echo.
goto MENU

:: ============================================================
::  [1] KHỞI ĐỘNG MÁY CHỦ CẢM BIẾN
:: ============================================================
:OPT_SERVER
echo.
echo  ────────────────────────────────────────────────────────
echo   Đang khởi động Máy Chủ Cảm Biến WiFi...
echo  ────────────────────────────────────────────────────────
echo.

where cargo >nul 2>&1
if %errorlevel% neq 0 (
    echo  [✗] LỖI: Không tìm thấy Cargo. Vui lòng cài đặt Rust trước.
    echo      ^> https://rustup.rs/
    echo.
    pause
    goto MENU
)

cd /d "%~dp0rust-port\wifi-densepose-rs"
if %errorlevel% neq 0 (
    echo  [✗] LỖI: Không tìm thấy thư mục dự án Rust.
    echo.
    pause
    cd /d "%~dp0"
    goto MENU
)

echo  [*] Đang biên dịch và khởi chạy máy chủ cảm biến...
echo  [*] Nhấn Ctrl+C để dừng máy chủ.
echo.
cargo run -p wifi-densepose-sensing-server --no-default-features
echo.
echo  [*] Máy chủ đã dừng.
cd /d "%~dp0"
echo.
pause
goto MENU

:: ============================================================
::  [2] KHỞI ĐỘNG ỨNG DỤNG DI ĐỘNG (EXPO)
:: ============================================================
:OPT_MOBILE
echo.
echo  ────────────────────────────────────────────────────────
echo   Đang khởi động Ứng Dụng Di Động (Expo)...
echo  ────────────────────────────────────────────────────────
echo.

where npx >nul 2>&1
if %errorlevel% neq 0 (
    echo  [✗] LỖI: Không tìm thấy npx. Vui lòng cài đặt Node.js trước.
    echo      ^> https://nodejs.org/
    echo.
    pause
    goto MENU
)

cd /d "%~dp0ui\mobile"
if %errorlevel% neq 0 (
    echo  [✗] LỖI: Không tìm thấy thư mục ứng dụng di động.
    echo.
    pause
    cd /d "%~dp0"
    goto MENU
)

if not exist "node_modules" (
    echo  [*] Lần đầu chạy — đang cài đặt phụ thuộc...
    call npm install
    if %errorlevel% neq 0 (
        echo  [✗] LỖI: Cài đặt phụ thuộc thất bại.
        echo.
        pause
        cd /d "%~dp0"
        goto MENU
    )
)

echo  [*] Đang khởi chạy Expo... (Nhấn Ctrl+C để dừng)
echo.
call npx expo start
echo.
echo  [*] Ứng dụng Expo đã dừng.
cd /d "%~dp0"
echo.
pause
goto MENU

:: ============================================================
::  [3] KHỞI ĐỘNG ỨNG DỤNG MÁY TÍNH (TAURI)
:: ============================================================
:OPT_DESKTOP
echo.
echo  ────────────────────────────────────────────────────────
echo   Đang khởi động Ứng Dụng Máy Tính (Tauri)...
echo  ────────────────────────────────────────────────────────
echo.

where cargo >nul 2>&1
if %errorlevel% neq 0 (
    echo  [✗] LỖI: Không tìm thấy Cargo. Vui lòng cài đặt Rust trước.
    echo      ^> https://rustup.rs/
    echo.
    pause
    goto MENU
)

cd /d "%~dp0rust-port\wifi-densepose-rs"
if %errorlevel% neq 0 (
    echo  [✗] LỖI: Không tìm thấy thư mục dự án Rust.
    echo.
    pause
    cd /d "%~dp0"
    goto MENU
)

echo  [*] Đang biên dịch và khởi chạy ứng dụng Tauri...
echo  [*] Lần đầu có thể mất vài phút để biên dịch.
echo.
cargo tauri dev
echo.
echo  [*] Ứng dụng Tauri đã đóng.
cd /d "%~dp0"
echo.
pause
goto MENU

:: ============================================================
::  [4] CHẠY BỘ KIỂM THỬ RUST
:: ============================================================
:OPT_TEST
echo.
echo  ────────────────────────────────────────────────────────
echo   Đang chạy Bộ Kiểm Thử Rust...
echo  ────────────────────────────────────────────────────────
echo.

where cargo >nul 2>&1
if %errorlevel% neq 0 (
    echo  [✗] LỖI: Không tìm thấy Cargo. Vui lòng cài đặt Rust trước.
    echo      ^> https://rustup.rs/
    echo.
    pause
    goto MENU
)

cd /d "%~dp0rust-port\wifi-densepose-rs"
if %errorlevel% neq 0 (
    echo  [✗] LỖI: Không tìm thấy thư mục dự án Rust.
    echo.
    pause
    cd /d "%~dp0"
    goto MENU
)

echo  [*] Đang biên dịch và chạy toàn bộ bộ kiểm thử...
echo  [*] Mục tiêu: 1.031+ bài kiểm thử đều pass.
echo.
cargo test --workspace --no-default-features
set "TEST_RESULT=%errorlevel%"
echo.

if "%TEST_RESULT%"=="0" (
    echo  ╔══════════════════════════════════════════════════════════╗
    echo  ║  [✓] TẤT CẢ BÀI KIỂM THỬ ĐÃ PASS!                    ║
    echo  ╚══════════════════════════════════════════════════════════╝
) else (
    echo  ╔══════════════════════════════════════════════════════════╗
    echo  ║  [✗] MỘT SỐ BÀI KIỂM THỬ THẤT BẠI.                   ║
    echo  ║      Kiểm tra log ở trên để biết chi tiết.             ║
    echo  ╚══════════════════════════════════════════════════════════╝
)
cd /d "%~dp0"
echo.
pause
goto MENU

:: ============================================================
::  THOÁT
:: ============================================================
:EXIT
echo.
echo  ╔══════════════════════════════════════════════════════════╗
echo  ║                                                          ║
echo  ║   Cảm ơn Đại Ca đã sử dụng RuView!                     ║
echo  ║   Hẹn gặp lại.                                          ║
echo  ║                                                          ║
echo  ╚══════════════════════════════════════════════════════════╝
echo.
endlocal
exit /b 0
