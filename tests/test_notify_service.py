"""NotifyService 조건 판단 / 포맷 / 중복 방지 테스트."""

from __future__ import annotations

import pytest

from app.config.settings import KakaoSettings, Settings, StopConfig
from app.models.bus import BusArrival
from app.repositories.dedup_repository import DedupRepository
from app.services.kakao_service import KakaoService
from app.services.notify_service import NotifyService


class _FakeProvider:
    def __init__(self, arrivals: list[BusArrival]) -> None:
        self._arrivals = arrivals

    async def get_arrivals(self, station_id: str) -> list[BusArrival]:  # noqa: ARG002
        return self._arrivals


class _RecordingKakao(KakaoService):
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_to_me(self, text: str, link_url: str = "") -> None:  # noqa: ARG002
        self.sent.append(text)


def _settings(stop: StopConfig, **overrides) -> Settings:
    base = dict(
        stops=[stop],
        notify_minutes=10,
        notify_stations=None,
        kakao=KakaoSettings(dry_run=True),
        database_path=":memory:",
    )
    base.update(overrides)
    return Settings(**base)


async def _svc(arrivals, stop, **overrides):
    kakao = _RecordingKakao()
    repo = DedupRepository(":memory:", ttl_seconds=1800)
    await repo.init()
    settings = _settings(stop, **overrides)
    svc = NotifyService(settings, {stop.provider: _FakeProvider(arrivals)}, kakao, repo)
    return svc, kakao


@pytest.mark.asyncio
async def test_notifies_when_within_minutes():
    stop = StopConfig(provider="incheon", station_id="123", label="출근", routes=["17"])
    arrivals = [BusArrival(route_no="17", vehicle_id="A1", arrival_seconds=7 * 60)]
    svc, kakao = await _svc(arrivals, stop)

    assert await svc.check_and_notify() == 1
    assert "17번 버스" in kakao.sent[0]
    assert "출근" in kakao.sent[0]
    assert "도착 예정 : 7분" in kakao.sent[0]


@pytest.mark.asyncio
async def test_skips_when_too_far():
    stop = StopConfig(provider="incheon", station_id="123", routes=["17"])
    arrivals = [BusArrival(route_no="17", vehicle_id="A1", arrival_seconds=20 * 60)]
    svc, kakao = await _svc(arrivals, stop)

    assert await svc.check_and_notify() == 0
    assert kakao.sent == []


@pytest.mark.asyncio
async def test_filters_other_routes():
    stop = StopConfig(provider="incheon", station_id="123", routes=["17"])
    arrivals = [BusArrival(route_no="99", vehicle_id="A1", arrival_seconds=5 * 60)]
    svc, kakao = await _svc(arrivals, stop)

    assert await svc.check_and_notify() == 0


@pytest.mark.asyncio
async def test_dedup_prevents_second_notification():
    stop = StopConfig(provider="incheon", station_id="123", routes=["17"])
    arrivals = [BusArrival(route_no="17", vehicle_id="A1", arrival_seconds=5 * 60)]
    svc, kakao = await _svc(arrivals, stop)

    assert await svc.check_and_notify() == 1
    assert await svc.check_and_notify() == 0
    assert len(kakao.sent) == 1


@pytest.mark.asyncio
async def test_per_stop_override_notify_stations():
    stop = StopConfig(provider="seoul", station_id="s1", routes=[], notify_stations=3)
    arrivals = [BusArrival(route_no="1300", vehicle_id="A1", remaining_stations=2)]
    svc, kakao = await _svc(arrivals, stop)

    assert await svc.check_and_notify() == 1
    assert "남은 정류장 : 2개" in kakao.sent[0]
