"""HTTP API 라우트."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.container import Container
from app.services.bus_service import BusApiError
from app.services.kakao_service import KakaoError

router = APIRouter()

_INDEX_HTML = (Path(__file__).resolve().parent.parent / "web" / "index.html").read_text(
    encoding="utf-8"
)


def get_container(request: Request) -> Container:
    return request.app.state.container


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index(container: Container = Depends(get_container)) -> str:
    """노선 검색 + 노선도 화면. 카카오맵 키가 있으면 SDK 를 주입한다."""
    key = container.settings.kakao.js_key or ""
    sdk = (
        f'<script src="https://dapi.kakao.com/v2/maps/sdk.js?appkey={key}&autoload=false"></script>'
        if key
        else ""
    )
    return _INDEX_HTML.replace("__KAKAO_SDK__", sdk)


@router.get("/api/routes")
async def search_routes(
    no: str, container: Container = Depends(get_container)
) -> list[dict]:
    """노선번호(부분일치)로 검색."""
    if not no.strip():
        return []
    try:
        return await container.route_service.search(no.strip())
    except BusApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/api/routes/{route_id}/stops")
async def route_stops(
    route_id: str, container: Container = Depends(get_container)
) -> dict:
    """노선의 경유 정류소(노선도)."""
    try:
        return await container.route_service.stops(route_id)
    except BusApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/api/routes/{route_id}/buses")
async def route_buses(
    route_id: str, container: Container = Depends(get_container)
) -> dict:
    """노선에서 현재 운행 중인 버스의 위치/차량번호."""
    try:
        return await container.route_service.buses(route_id)
    except BusApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/api/routes/{route_id}/track")
async def route_track(
    route_id: str, container: Container = Depends(get_container)
) -> dict:
    """실시간 GPS 누적으로 학습한 도로 경로({방향:{정류소순번:[[lat,lng]...]}})."""
    return await container.route_service.track(route_id)


class AlarmCreate(BaseModel):
    """화면에서 정류장 선택 후 만드는 알림 규칙."""

    route_id: str
    route_no: str = ""
    stop_id: str
    stop_name: str = ""
    dir: str = ""
    n_stations: int | None = None
    notify_minutes: int | None = None
    start_time: str | None = None  # "HH:MM"
    end_time: str | None = None
    weekdays: list[int] = []  # 월=0 ~ 일=6, 비우면 매일
    enabled: bool = True


@router.get("/api/alarms")
async def list_alarms(
    route_id: str | None = None, container: Container = Depends(get_container)
) -> list[dict]:
    """알림 규칙 목록(옵션: route_id 로 필터)."""
    return await container.alarm_repo.list(route_id)


@router.post("/api/alarms")
async def create_alarm(
    body: AlarmCreate, container: Container = Depends(get_container)
) -> dict:
    """알림 규칙 생성. n_stations/notify_minutes 중 최소 하나는 있어야 한다."""
    if body.n_stations is None and body.notify_minutes is None:
        raise HTTPException(
            status_code=400, detail="몇 정거장 전 또는 도착 N분 전 중 하나는 필요합니다."
        )
    rule = body.model_dump()
    rule["weekdays"] = ",".join(str(d) for d in sorted(set(body.weekdays)))
    return await container.alarm_repo.add(rule)


@router.delete("/api/alarms/{alarm_id}")
async def delete_alarm(
    alarm_id: int, container: Container = Depends(get_container)
) -> dict:
    ok = await container.alarm_repo.delete(alarm_id)
    if not ok:
        raise HTTPException(status_code=404, detail="알림 규칙을 찾을 수 없습니다.")
    return {"deleted": alarm_id}


@router.patch("/api/alarms/{alarm_id}")
async def toggle_alarm(
    alarm_id: int, enabled: bool, container: Container = Depends(get_container)
) -> dict:
    ok = await container.alarm_repo.set_enabled(alarm_id, enabled)
    if not ok:
        raise HTTPException(status_code=404, detail="알림 규칙을 찾을 수 없습니다.")
    return {"id": alarm_id, "enabled": enabled}


@router.post("/api/alarms/{alarm_id}/test")
async def test_alarm(
    alarm_id: int, container: Container = Depends(get_container)
) -> dict:
    """규칙을 즉시 테스트 발송한다(시간대 무시, 조건 미충족 시 미리보기)."""
    rule = await container.alarm_repo.get(alarm_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="알림 규칙을 찾을 수 없습니다.")
    try:
        return await container.notify_service.test_rule(rule)
    except BusApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


class ConfigUpdate(BaseModel):
    """런타임 설정 변경 요청. 지정한 필드만 반영된다."""

    check_interval: int | None = None
    notify_minutes: int | None = None
    notify_stations: int | None = None


class NotifyTestRequest(BaseModel):
    message: str | None = None


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.get("/stops")
async def stops(container: Container = Depends(get_container)) -> list[dict]:
    """설정된 감시 정류소 목록."""
    return [
        {
            "provider": s.provider,
            "station_id": s.station_id,
            "label": s.label,
            "routes": s.routes,
        }
        for s in container.settings.stops
    ]


@router.get("/arrival")
async def arrival(container: Container = Depends(get_container)) -> dict:
    """설정된 모든 정류소의 도착 예정 버스(노선 필터링 적용)를 정류소별로 반환."""
    result: dict = {}
    for stop in container.settings.stops:
        try:
            arrivals = await container.notify_service.get_arrivals(stop)
        except BusApiError as exc:
            result[stop.display_name()] = {"error": str(exc)}
            continue
        result[stop.display_name()] = [a.model_dump(exclude={"raw"}) for a in arrivals]
    return result


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
    return {
        "sent": True,
        "dry_run": container.settings.kakao.is_dry_run,
        "message": text,
    }


@router.post("/config")
async def update_config(
    body: ConfigUpdate,
    container: Container = Depends(get_container),
) -> dict:
    """런타임 설정을 변경한다. check_interval 변경 시 스케줄을 재조정한다."""
    settings = container.settings
    if body.notify_minutes is not None:
        settings.notify_minutes = body.notify_minutes
    if body.notify_stations is not None:
        settings.notify_stations = body.notify_stations
    if body.check_interval is not None and body.check_interval != settings.check_interval:
        settings.check_interval = body.check_interval
        container.scheduler.reschedule(body.check_interval)

    return {
        "check_interval": settings.check_interval,
        "notify_minutes": settings.notify_minutes,
        "notify_stations": settings.notify_stations,
    }
