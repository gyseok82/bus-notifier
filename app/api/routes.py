"""HTTP API 라우트."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.container import Container
from app.models.bus import BusArrival
from app.services.bus_service import BusApiError
from app.services.kakao_service import KakaoError

router = APIRouter()


def get_container(request: Request) -> Container:
    return request.app.state.container


class ConfigUpdate(BaseModel):
    """런타임 설정 변경 요청. 지정한 필드만 반영된다."""

    routes: list[str] | None = None
    check_interval: int | None = None
    notify_minutes: int | None = None
    notify_stations: int | None = None


class NotifyTestRequest(BaseModel):
    message: str | None = None


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.get("/arrival", response_model=list[BusArrival])
async def arrival(container: Container = Depends(get_container)) -> list[BusArrival]:
    """현재 정류장의 도착 예정 버스(설정된 노선만) 조회."""
    try:
        arrivals = await container.bus_service.get_arrivals(container.settings.station_id)
    except BusApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return container.notify_service.filter_routes(arrivals)


@router.post("/notify/test")
async def notify_test(
    body: NotifyTestRequest | None = None,
    container: Container = Depends(get_container),
) -> dict:
    """테스트 알림을 카카오로 발송한다."""
    text = (body.message if body else None) or "🚌 버스 알림 테스트 메시지입니다."
    try:
        await container.kakao_service.send_to_me(text)
    except KakaoError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    dry = container.settings.kakao.is_dry_run
    return {"sent": True, "dry_run": dry, "message": text}


@router.post("/config")
async def update_config(
    body: ConfigUpdate,
    container: Container = Depends(get_container),
) -> dict:
    """런타임 설정을 변경한다. check_interval 변경 시 스케줄을 재조정한다."""
    settings = container.settings
    if body.routes is not None:
        settings.routes = body.routes
    if body.notify_minutes is not None:
        settings.notify_minutes = body.notify_minutes
    if body.notify_stations is not None:
        settings.notify_stations = body.notify_stations
    if body.check_interval is not None and body.check_interval != settings.check_interval:
        settings.check_interval = body.check_interval
        container.scheduler.reschedule(body.check_interval)

    return {
        "routes": settings.routes,
        "check_interval": settings.check_interval,
        "notify_minutes": settings.notify_minutes,
        "notify_stations": settings.notify_stations,
    }
