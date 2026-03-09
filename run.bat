@echo off
chcp 65001 >nul 2>&1
title RuView - Hệ thống cảm biến WiFi AI
color 0A

echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║                                                      ║
echo  ║   ██████╗ ██╗   ██╗██╗   ██╗██╗███████╗██╗    ██╗   ║
echo  ║   ██╔══██╗██║   ██║██║   ██║██║██╔════╝██║    ██║   ║
echo  ║   ██████╔╝██║   ██║██║   ██║██║█████╗  ██║ █╗ ██║   ║
echo  ║   ██╔══██╗██║   ██║╚██╗ ██╔╝██║██╔══╝  ██║███╗██║   ║
echo  ║   ██║  ██║╚██████╔╝ ╚████╔╝ ██║███████╗╚███╔███╔╝   ║
echo  ║   ╚═╝  ╚═╝ ╚═════╝   ╚═══╝  ╚═╝╚══════╝ ╚══╝╚══╝   ║
echo  ║                                                      ║
echo  ║   Hệ thống Cảm biến WiFi AI - Nhìn xuyên tường      ║
echo  ║   Phiên bản 1.2.0                                    ║
echo  ║                                                      ║
echo  ╚══════════════════════════════════════════════════════╝
echo.

:: Kiểm tra môi trường
echo  [*] Đang kiểm tra môi trường...
echo.

where python >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo  [✓] Python đã cài đặt
) else (
    echo  [✗] Python chưa cài đặt - cần cài để chạy API Server
)

where node >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo  [✓] Node.js đã cài đặt
) else (
    echo  [✗] Node.js chưa cài đặt
)

where cargo >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo  [✓] Rust/Cargo đã cài đặt
) else (
    echo  [✗] Rust chưa cài đặt - cần cài để chạy Sensing Server
)

echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║                    MENU CHÍNH                        ║
echo  ╠══════════════════════════════════════════════════════╣
echo  ║                                                      ║
echo  ║   1. Mở Giao diện Web (trình duyệt)                 ║
echo  ║   2. Chạy Python API Server                          ║
echo  ║   3. Chạy Rust Sensing Server                        ║
echo  ║   4. Chạy cả hai (Python + Rust)                     ║
echo  ║   5. Chạy kiểm tra (Trust Kill Switch)               ║
echo  ║   6. Thoát                                           ║
echo  ║                                                      ║
echo  ╚══════════════════════════════════════════════════════╝
echo.
set /p choice="  Chọn mục (1-6): "

if "%choice%"=="1" goto web_ui
if "%choice%"=="2" goto python_api
if "%choice%"=="3" goto rust_server
if "%choice%"=="4" goto both_servers
if "%choice%"=="5" goto verify
if "%choice%"=="6" goto exit_app
echo  [!] Lựa chọn không hợp lệ. Vui lòng chọn từ 1 đến 6.
pause
goto :eof

:web_ui
echo.
echo  [*] Đang mở giao diện Web...
start "" "ui\index.html"
echo  [✓] Đã mở trình duyệt!
echo  [i] Giao diện sẽ hoạt động ở chế độ demo nếu không có server.
pause
goto :eof

:python_api
echo.
echo  [*] Đang khởi động Python API Server...
echo  [i] Server sẽ chạy tại http://localhost:8765
echo  [i] Nhấn Ctrl+C để dừng server
echo.
cd v1
python -m uvicorn src.api.main:app --host 0.0.0.0 --port 8765 --reload
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo  [✗] Lỗi khởi động server! Kiểm tra:
    echo      - Python đã cài đặt chưa?
    echo      - Đã chạy "pip install -r requirements.txt" chưa?
    echo      - File .env đã cấu hình chưa?
)
cd ..
pause
goto :eof

:rust_server
echo.
echo  [*] Đang biên dịch và khởi động Rust Sensing Server...
echo  [i] Server sẽ chạy tại http://localhost:3000
echo  [i] Nhấn Ctrl+C để dừng server
echo.
cd rust-port\wifi-densepose-rs
cargo run -p wifi-densepose-sensing-server --no-default-features
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo  [✗] Lỗi biên dịch hoặc khởi động! Kiểm tra:
    echo      - Rust/Cargo đã cài đặt chưa?
    echo      - Chạy "rustup update" để cập nhật
)
cd ..\..
pause
goto :eof

:both_servers
echo.
echo  [*] Đang khởi động cả hai server...
echo  [i] Python API: http://localhost:8765
echo  [i] Rust Sensing: http://localhost:3000
echo.
start "RuView Python API" cmd /c "cd v1 && python -m uvicorn src.api.main:app --host 0.0.0.0 --port 8765 --reload"
echo  [✓] Python API Server đã khởi động (cửa sổ mới)
timeout /t 3 /nobreak >nul
start "RuView Rust Sensing" cmd /c "cd rust-port\wifi-densepose-rs && cargo run -p wifi-densepose-sensing-server --no-default-features"
echo  [✓] Rust Sensing Server đang biên dịch (cửa sổ mới)
echo.
echo  [i] Đang mở giao diện Web...
timeout /t 2 /nobreak >nul
start "" "ui\index.html"
echo  [✓] Tất cả đã khởi động! Đóng cửa sổ này để tiếp tục.
pause
goto :eof

:verify
echo.
echo  [*] Đang chạy kiểm tra Trust Kill Switch...
echo  [i] Xác minh tính toàn vẹn pipeline xử lý tín hiệu
echo.
python v1\data\proof\verify.py
echo.
pause
goto :eof

:exit_app
echo.
echo  Tạm biệt! Hẹn gặp lại Đại Ca!
echo.
exit /b 0
