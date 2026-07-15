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
async def test_grid_snap_dedups_and_counts_hits():
    repo = await _repo()
    pt = {"dir": "0", "stop_seq": 1, "lat": 37.400000, "lng": 126.700000}
    near = {"dir": "0", "stop_seq": 1, "lat": 37.400001, "lng": 126.700001}  # 같은 격자(≈11m)
    await repo.record("R1", [pt])
    await repo.record("R1", [near])
    # 격자가 합쳐져 점은 1개
    assert len((await repo.track("R1"))["0"]["1"]) == 1
    # 2회 관측 → min_hits=2 로도 조회됨(1회였다면 걸러짐)
    assert len((await repo.track("R1", min_hits=2))["0"]["1"]) == 1
    await repo.close()


@pytest.mark.asyncio
async def test_min_hits_filters_one_off_glitches():
    repo = await _repo()
    # 도로 위 점은 반복 관측(3회), 글리치는 1회만.
    for _ in range(3):
        await repo.record("R1", [{"dir": "0", "stop_seq": 1, "lat": 37.40, "lng": 126.70}])
    await repo.record("R1", [{"dir": "0", "stop_seq": 1, "lat": 37.50, "lng": 126.90}])  # 튐
    only_solid = await repo.track("R1", min_hits=2)
    assert only_solid["0"]["1"] == [[37.40, 126.70]]  # 글리치 제외
    # 기본(min_hits=1)은 둘 다 포함
    assert len((await repo.track("R1"))["0"]["1"]) == 2
    await repo.close()


@pytest.mark.asyncio
async def test_empty_and_missing_route():
    repo = await _repo()
    assert await repo.record("R1", []) == 0
    assert await repo.track("없는노선") == {}
    await repo.close()
