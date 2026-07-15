"""APScheduler 기반 주기 조회 스케줄러."""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from app.services.notify_service import NotifyService

_JOB_ID = "bus-arrival-check"


class BusScheduler:
    """일정 주기로 NotifyService.check_and_notify 를 실행한다."""

    def __init__(self, notify_service: NotifyService, interval_seconds: int) -> None:
        self._notify = notify_service
        self._interval = interval_seconds
        self._scheduler = AsyncIOScheduler()

    def start(self) -> None:
        self._scheduler.add_job(
            self._run,
            trigger="interval",
            seconds=self._interval,
            id=_JOB_ID,
            max_instances=1,
            coalesce=True,
            next_run_time=None,
        )
        self._scheduler.start()
        logger.info("스케줄러 시작 (주기 {}초)", self._interval)

    async def _run(self) -> None:
        try:
            await self._notify.check_and_notify()
        except Exception:  # noqa: BLE001 - 스케줄러 잡은 예외로 죽지 않아야 함
            logger.exception("주기 작업 실행 중 오류")

    def reschedule(self, interval_seconds: int) -> None:
        self._interval = interval_seconds
        self._scheduler.reschedule_job(_JOB_ID, trigger="interval", seconds=interval_seconds)
        logger.info("스케줄 주기 변경: {}초", interval_seconds)

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("스케줄러 종료")
