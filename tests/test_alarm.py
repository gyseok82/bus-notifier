"""알림 규칙 저장소 + 규칙 기반 알림(시간대/요일/N정거장) 테스트."""

from __future__ import annotations

from datetime import datetime

import pytest

from app.config.settings import Settings
from app.models.bus import BusArrival
from app.repositories.alarm_repository import AlarmRepository
from app.repositories.dedup_repository import DedupRepository
from app.services.notify_service import _SEOUL, NotifyService, _hm

# 2026-07-16 은 목요일(weekday()=3)
THU_0800 = datetime(2026, 7, 16, 8, 0, tzinfo=_SEOUL)
THU_1000 = datetime(2026, 7, 16, 10, 0, tzinfo=_SEOUL)


class _FakeProvider:
    def __init__(self, arrivals):
        self._a = arrivals
        self.calls = 0

    async def get_arrivals(self, station_id):
        self.calls += 1
        return self._a


class _FakeKakao:
    def __init__(self):
        self.sent = []

    async def send_to_me(self, msg):
        self.sent.append(msg)


async def _alarm_repo():
    repo = AlarmRepository(":memory:")
    await repo.init()
    return repo


def _arrival(route_id="165000160", veh="인천70바1", remain=2, secs=180):
    return BusArrival(route_no=route_id, vehicle_id=veh, remaining_stations=remain, arrival_seconds=secs)


async def _svc(arrivals, alarm_repo):
    dedup = DedupRepository(":memory:", 1800)
    await dedup.init()
    kakao = _FakeKakao()
    svc = NotifyService(Settings(stops=[]), {"incheon": _FakeProvider(arrivals)}, kakao, dedup, alarm_repo=alarm_repo)
    return svc, kakao


def test_hm():
    assert _hm("07:30") == 450
    assert _hm(None) is None and _hm("bad") is None


@pytest.mark.asyncio
async def test_alarm_repo_crud_and_weekdays_roundtrip():
    repo = await _alarm_repo()
    created = await repo.add({
        "route_id": "R1", "route_no": "9100", "stop_id": "S1", "stop_name": "제물포역",
        "n_stations": 3, "start_time": "07:00", "end_time": "09:00", "weekdays": "0,1,2,3,4",
    })
    assert created["id"] == 1
    assert created["weekdays"] == [0, 1, 2, 3, 4]  # CSV → list
    assert created["enabled"] is True
    assert len(await repo.list("R1")) == 1
    assert await repo.list("nope") == []
    assert await repo.set_enabled(1, False)
    assert (await repo.get(1))["enabled"] is False
    assert await repo.delete(1)
    assert await repo.get(1) is None
    await repo.close()


@pytest.mark.asyncio
async def test_rule_fires_within_window_and_condition():
    repo = await _alarm_repo()
    await repo.add({"route_id": "165000160", "route_no": "9100", "stop_id": "S1",
                    "n_stations": 3, "start_time": "07:00", "end_time": "09:00", "weekdays": "3"})
    svc, kakao = await _svc([_arrival(remain=2)], repo)  # 남은 2 ≤ 3
    sent = await svc.check_alarm_rules(now=THU_0800)
    assert sent == 1 and len(kakao.sent) == 1
    assert "9100번" in kakao.sent[0]
    # 중복 방지: 같은 차량 재확인 시 발송 안 함
    assert await svc.check_alarm_rules(now=THU_0800) == 0


@pytest.mark.asyncio
async def test_rule_skipped_outside_time_window():
    repo = await _alarm_repo()
    await repo.add({"route_id": "165000160", "stop_id": "S1", "n_stations": 3,
                    "start_time": "07:00", "end_time": "09:00", "weekdays": "3"})
    svc, kakao = await _svc([_arrival(remain=1)], repo)
    assert await svc.check_alarm_rules(now=THU_1000) == 0  # 10시 = 창 밖
    assert kakao.sent == []


@pytest.mark.asyncio
async def test_rule_skipped_wrong_weekday_and_far_bus():
    repo = await _alarm_repo()
    await repo.add({"route_id": "165000160", "stop_id": "S1", "n_stations": 3, "weekdays": "0"})  # 월요일만
    svc, kakao = await _svc([_arrival(remain=2)], repo)
    assert await svc.check_alarm_rules(now=THU_0800) == 0  # 목요일 → skip
    # 요일 맞아도 조건 미달(남은 10 > 3)이면 발송 안 함
    repo2 = await _alarm_repo()
    await repo2.add({"route_id": "165000160", "stop_id": "S1", "n_stations": 3, "weekdays": "3"})
    svc2, kakao2 = await _svc([_arrival(remain=10)], repo2)
    assert await svc2.check_alarm_rules(now=THU_0800) == 0
