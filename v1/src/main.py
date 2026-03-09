#!/usr/bin/env python3
"""
Điểm vào chính của ứng dụng WiFi-DensePose API
"""

import sys
import os
import asyncio
import logging
import signal
from pathlib import Path
from typing import Optional

# Thêm src vào đường dẫn Python
sys.path.insert(0, str(Path(__file__).parent))

from src.config.settings import get_settings, validate_settings
from src.logger import setup_logging
from src.app import create_app
from src.services.orchestrator import ServiceOrchestrator
from src.cli import create_cli


def setup_signal_handlers(orchestrator: ServiceOrchestrator):
    """Thiết lập trình xử lý tín hiệu để tắt máy chủ một cách duyên dáng."""
    def signal_handler(signum, frame):
        logging.info(f"Đã nhận tín hiệu {signum}, đang bắt đầu tắt máy chủ duyên dáng...")
        asyncio.create_task(orchestrator.shutdown())
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


async def main():
    """Điểm vào chính của ứng dụng."""
    try:
        # Tải cài đặt
        settings = get_settings()

        # Thiết lập ghi log
        setup_logging(settings)
        logger = logging.getLogger(__name__)

        logger.info(f"Đang khởi động {settings.app_name} v{settings.version}")
        logger.info(f"Môi trường: {settings.environment}")

        # Xác thực cài đặt
        issues = validate_settings(settings)
        if issues:
            logger.error("Phát hiện các vấn đề cấu hình:")
            for issue in issues:
                logger.error(f"  - {issue}")
            if settings.is_production:
                sys.exit(1)
            else:
                logger.warning("Tiếp tục với các vấn đề cấu hình trong chế độ phát triển")

        # Tạo trình điều phối dịch vụ
        orchestrator = ServiceOrchestrator(settings)

        # Thiết lập trình xử lý tín hiệu
        setup_signal_handlers(orchestrator)

        # Khởi tạo các dịch vụ
        await orchestrator.initialize()

        # Tạo ứng dụng FastAPI
        app = create_app(settings, orchestrator)

        # Khởi động ứng dụng
        if len(sys.argv) > 1:
            # Chế độ CLI
            cli = create_cli(orchestrator)
            await cli.run(sys.argv[1:])
        else:
            # Chế độ máy chủ
            import uvicorn

            logger.info(f"Đang khởi động máy chủ tại {settings.host}:{settings.port}")

            config = uvicorn.Config(
                app,
                host=settings.host,
                port=settings.port,
                reload=settings.reload and settings.is_development,
                workers=settings.workers if not settings.reload else 1,
                log_level=settings.log_level.lower(),
                access_log=True,
                use_colors=True
            )

            server = uvicorn.Server(config)
            await server.serve()

    except KeyboardInterrupt:
        logger.info("Đã nhận tín hiệu ngắt từ bàn phím, đang tắt...")
    except Exception as e:
        logger.error(f"Ứng dụng không thể khởi động: {e}", exc_info=True)
        sys.exit(1)
    finally:
        # Dọn dẹp
        if 'orchestrator' in locals():
            await orchestrator.shutdown()
        logger.info("Ứng dụng đã tắt hoàn tất")


def run():
    """Điểm vào cho cài đặt gói."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
