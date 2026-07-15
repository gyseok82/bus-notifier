"""노선 경로 학습 저장소 (실시간 버스 GPS 누적 → 도로 경로).

인천/노선 API 는 정류소 좌표만 제공하고 정류소 사이 도로 링크 좌표가 없다.
운행 중 버스의 실시간 GPS(TAGO)를 방향·정류소순번과 함께 격자 스냅으로 쌓아두면,
정류소를 앵커로 그 사이 곡선(도로)을 채운 노선도를 그릴 수 있다.
"""

from __future__ import annotations

import aiosqlite
from loguru import logger

# 격자 스냅 배율. 소수 4자리(≈11m) 로 반올림해 중복 좌표를 합치고 점 수를 제한한다.
_GRID = 10000


class RouteTrackRepository:
    """노선별 실시간 GPS 자취를 (방향, 정류소순번, 격자좌표) 로 누적한다."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS route_track (
                route_id TEXT    NOT NULL,
                dir      TEXT    NOT NULL,
                seq      INTEGER NOT NULL,
                gx       INTEGER NOT NULL,
                gy       INTEGER NOT NULL,
                lat      REAL    NOT NULL,
                lng      REAL    NOT NULL,
                PRIMARY KEY (route_id, dir, gx, gy)
            )
            """)
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_track_route ON route_track (route_id, dir, seq)"
        )
        await self._db.commit()
        logger.info("Route track store ready at {}", self._db_path)

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    def _conn(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("RouteTrackRepository.init() 가 호출되지 않았습니다.")
        return self._db

    async def record(self, route_id: str, buses: list[dict]) -> int:
        """버스들의 실시간 GPS 점을 누적한다. 저장(신규) 개수를 반환."""
        rows: list[tuple] = []
        for b in buses:
            lat, lng = b.get("lat"), b.get("lng")
            seq = b.get("stop_seq")
            if lat is None or lng is None or seq is None:
                continue
            rows.append(
                (route_id, str(b.get("dir", "0")), int(seq),
                 round(lng * _GRID), round(lat * _GRID), float(lat), float(lng))
            )
        if not rows:
            return 0
        cur = await self._conn().executemany(
            "INSERT OR IGNORE INTO route_track "
            "(route_id, dir, seq, gx, gy, lat, lng) VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        await self._conn().commit()
        return cur.rowcount or 0

    async def track(self, route_id: str) -> dict[str, dict[str, list[list[float]]]]:
        """누적 경로를 {방향: {정류소순번: [[lat, lng], ...]}} 로 반환."""
        out: dict[str, dict[str, list[list[float]]]] = {}
        async with self._conn().execute(
            "SELECT dir, seq, lat, lng FROM route_track WHERE route_id = ?",
            (route_id,),
        ) as cur:
            async for dir_, seq, lat, lng in cur:
                out.setdefault(str(dir_), {}).setdefault(str(seq), []).append([lat, lng])
        return out
