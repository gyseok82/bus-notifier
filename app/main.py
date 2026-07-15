"""FastAPI 애플리케이션 진입점."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from app.api import router
from app.config.settings import load_settings
from app.container import Container
from app.utils.logging import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    setup_logging(settings.log_level)
    stop_names = [s.display_name() for s in settings.stops]
    logger.info("bus-notifier 시작 (정류소 {}곳: {})", len(stop_names), ", ".join(stop_names))

    container = await Container.create(settings)
    app.state.container = container
    container.scheduler.start()
    try:
        yield
    finally:
        await container.aclose()
        logger.info("bus-notifier 종료")


app = FastAPI(title="Incheon Bus Notifier", version="0.1.0", lifespan=lifespan)
app.include_router(router)
