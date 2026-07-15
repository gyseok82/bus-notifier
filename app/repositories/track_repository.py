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
                hits     INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (route_id, dir, gx, gy)
            )
            """)
        # 구버전 테이블 마이그레이션: hits 컬럼이 없으면 추가.
        async with self._db.execute("PRAGMA table_info(route_track)") as cur:
            cols = [row[1] for row in await cur.fetchall()]
        if "hits" not in cols:
            await self._db.execute(
                "ALTER TABLE route_track ADD COLUMN hits INTEGER NOT NULL DEFAULT 1"
            )
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
        """버스들의 실시간 GPS 점을 누적한다. 같은 격자면 관측 횟수(hits)만 +1.

        처리한 점(행) 개수를 반환한다.
        """
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
        # 반복 관측되는 격자(실제 도로)는 hits 가 쌓이고, 일회성 GPS 오차는 낮게 남는다.
        await self._conn().executemany(
            "INSERT INTO route_track (route_id, dir, seq, gx, gy, lat, lng) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(route_id, dir, gx, gy) DO UPDATE SET hits = hits + 1",
            rows,
        )
        await self._conn().commit()
        return len(rows)

    async def track(
        self, route_id: str, min_hits: int = 1
    ) -> dict[str, dict[str, list[list[float]]]]:
        """누적 경로를 {방향: {정류소순번: [[lat, lng], ...]}} 로 반환.

        min_hits 이상 관측된 점만 포함해 일회성 GPS 오차(글리치)를 걸러낸다.
        """
        out: dict[str, dict[str, list[list[float]]]] = {}
        async with self._conn().execute(
            "SELECT dir, seq, lat, lng FROM route_track WHERE route_id = ? AND hits >= ?",
            (route_id, min_hits),
        ) as cur:
            async for dir_, seq, lat, lng in cur:
                out.setdefault(str(dir_), {}).setdefault(str(seq), []).append([lat, lng])
        return out
