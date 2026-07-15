"""중복 알림 방지 저장소 (SQLite + TTL)."""

from __future__ import annotations

import time

import aiosqlite
from loguru import logger


class DedupRepository:
    """이미 알림을 보낸 (노선:차량) 키를 TTL 동안 기억한다."""

    def __init__(self, db_path: str, ttl_seconds: int = 1800) -> None:
        self._db_path = db_path
        self._ttl = ttl_seconds
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS notified (
                key        TEXT PRIMARY KEY,
                created_at REAL NOT NULL
            )
            """)
        await self._db.commit()
        logger.info("Dedup store ready at {} (ttl={}s)", self._db_path, self._ttl)

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    def _conn(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("DedupRepository.init() 가 호출되지 않았습니다.")
        return self._db

    async def is_notified(self, key: str, *, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        async with self._conn().execute(
            "SELECT created_at FROM notified WHERE key = ?", (key,)
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return False
        # TTL 만료된 항목은 없는 것으로 취급
        if now - row[0] > self._ttl:
            await self._conn().execute("DELETE FROM notified WHERE key = ?", (key,))
            await self._conn().commit()
            return False
        return True

    async def mark(self, key: str, *, now: float | None = None) -> None:
        now = time.time() if now is None else now
        await self._conn().execute(
            "INSERT OR REPLACE INTO notified (key, created_at) VALUES (?, ?)",
            (key, now),
        )
        await self._conn().commit()

    async def cleanup(self, *, now: float | None = None) -> int:
        """TTL 이 지난 항목을 정리하고 삭제된 개수를 반환한다."""
        now = time.time() if now is None else now
        cur = await self._conn().execute(
            "DELETE FROM notified WHERE created_at < ?", (now - self._ttl,)
        )
        await self._conn().commit()
        return cur.rowcount
