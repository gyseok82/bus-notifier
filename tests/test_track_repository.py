"""노선 경로 학습 저장소(실시간 GPS 누적) 테스트."""

from __future__ import annotations

import pytest

from app.repositories.track_repository import RouteTrackRepository


async def _repo() -> RouteTrackRepository:
    repo = RouteTrackRepository(":memory:")
    await repo.init()
    return repo


@pytest.mark.asyncio
async def test_record_and_track_grouping():
    repo = await _repo()
    buses = [
        {"dir": "0", "stop_seq": 3, "lat": 37.46, "lng": 126.65},
        {"dir": "0", "stop_seq": 3, "lat": 37.47, "lng": 126.66},  # 같은 방향·seq 다른 좌표
        {"dir": "1", "stop_seq": 8, "lat": 37.50, "lng": 127.01},
        {"dir": "0", "stop_seq": 5, "lat": None, "lng": 126.7},    # 좌표 없음 → 제외
    ]
    saved = await repo.record("R1", buses)
    assert saved == 3
    track = await repo.track("R1")
    assert set(track) == {"0", "1"}
    assert len(track["0"]["3"]) == 2
    assert track["1"]["8"] == [[37.50, 127.01]]
    await repo.close()


@pytest.mark.asyncio
async def test_grid_snap_dedups_nearby_points():
    repo = await _repo()
    # 격자(≈11m) 안에서 미세하게 다른 좌표는 하나로 합쳐진다.
    first = await repo.record("R1", [{"dir": "0", "stop_seq": 1, "lat": 37.400000, "lng": 126.700000}])
    dup = await repo.record("R1", [{"dir": "0", "stop_seq": 1, "lat": 37.400001, "lng": 126.700001}])
    assert first == 1
    assert dup == 0  # 같은 격자 → INSERT OR IGNORE
    track = await repo.track("R1")
    assert len(track["0"]["1"]) == 1
    await repo.close()


@pytest.mark.asyncio
async def test_empty_and_missing_route():
    repo = await _repo()
    assert await repo.record("R1", []) == 0
    assert await repo.track("없는노선") == {}
    await repo.close()
