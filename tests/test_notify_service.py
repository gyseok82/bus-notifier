"""NotifyService 조건 판단 / 포맷 / 중복 방지 테스트."""

from __future__ import annotations

import pytest

from app.config.settings import BusApiSettings, KakaoSettings, Settings
from app.models.bus import BusArrival
from app.repositories.dedup_repository import DedupRepository
from app.services.bus_service import BusService
from app.services.kakao_service import KakaoService
from app.services.notify_service import NotifyService


class _FakeBusService(BusService):
    def __init__(self, arrivals: list[BusArrival]) -> None:
        self._arrivals = arrivals

    async def get_arrivals(self, station_id: str) -> list[BusArrival]:  # noqa: ARG002
        return self._arrivals


class _RecordingKakao(KakaoService):
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_to_me(self, text: str, link_url: str = "") -> None:  # noqa: ARG002
        self.sent.append(text)


def _settings(**overrides) -> Settings:
    base = dict(
        station_id="123456",
        routes=["17"],
        notify_minutes=10,
        notify_stations=None,
        bus_api=BusApiSettings(use_mock=True),
        kakao=KakaoSettings(dry_run=True),
        database_path=":memory:",
    )
    base.update(overrides)
    return Settings(**base)


async def _make_repo() -> DedupRepository:
    repo = DedupRepository(":memory:", ttl_seconds=1800)
    await repo.init()
    return repo


@pytest.mark.asyncio
async def test_notifies_when_within_minutes():
    arrivals = [BusArrival(route_no="17", vehicle_id="A1", arrival_seconds=7 * 60)]
    kakao = _RecordingKakao()
    repo = await _make_repo()
    svc = NotifyService(_settings(), _FakeBusService(arrivals), kakao, repo)

    sent = await svc.check_and_notify()

    assert sent == 1
    assert "17번 버스" in kakao.sent[0]
    assert "도착 예정 : 7분" in kakao.sent[0]


@pytest.mark.asyncio
async def test_skips_when_too_far():
    arrivals = [BusArrival(route_no="17", vehicle_id="A1", arrival_seconds=20 * 60)]
    kakao = _RecordingKakao()
    repo = await _make_repo()
    svc = NotifyService(_settings(), _FakeBusService(arrivals), kakao, repo)

    assert await svc.check_and_notify() == 0
    assert kakao.sent == []


@pytest.mark.asyncio
async def test_filters_other_routes():
    arrivals = [BusArrival(route_no="99", vehicle_id="A1", arrival_seconds=5 * 60)]
    kakao = _RecordingKakao()
    repo = await _make_repo()
    svc = NotifyService(_settings(routes=["17"]), _FakeBusService(arrivals), kakao, repo)

    assert await svc.check_and_notify() == 0


@pytest.mark.asyncio
async def test_dedup_prevents_second_notification():
    arrivals = [BusArrival(route_no="17", vehicle_id="A1", arrival_seconds=5 * 60)]
    kakao = _RecordingKakao()
    repo = await _make_repo()
    svc = NotifyService(_settings(), _FakeBusService(arrivals), kakao, repo)

    assert await svc.check_and_notify() == 1
    assert await svc.check_and_notify() == 0  # 같은 차량 재알림 없음
    assert len(kakao.sent) == 1


@pytest.mark.asyncio
async def test_notifies_by_remaining_stations():
    arrivals = [BusArrival(route_no="17", vehicle_id="A1", remaining_stations=2)]
    kakao = _RecordingKakao()
    repo = await _make_repo()
    svc = NotifyService(_settings(notify_stations=3), _FakeBusService(arrivals), kakao, repo)

    assert await svc.check_and_notify() == 1
    assert "남은 정류장 : 2개" in kakao.sent[0]
