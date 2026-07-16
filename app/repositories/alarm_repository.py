"""사용자 알림 규칙 저장소 (SQLite).

화면에서 노선·정류장을 선택해 만든 규칙을 저장한다.
규칙 = (노선 ROUTEID, 정류장, 조건: N정거장 전 / 도착 N분 전, 시간대, 요일).
"""

from __future__ import annotations

import time

import aiosqlite
from loguru import logger


class AlarmRepository:
    """알림 규칙 CRUD."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS alarm (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                provider      TEXT    NOT NULL DEFAULT 'incheon',
                route_id      TEXT    NOT NULL,
                route_no      TEXT    NOT NULL DEFAULT '',
                stop_id       TEXT    NOT NULL,
                stop_name     TEXT    NOT NULL DEFAULT '',
                dir           TEXT    NOT NULL DEFAULT '',
                n_stations    INTEGER,
                notify_minutes INTEGER,
                start_time    TEXT,
                end_time      TEXT,
                weekdays      TEXT    NOT NULL DEFAULT '',
                enabled       INTEGER NOT NULL DEFAULT 1,
                created_at    REAL    NOT NULL
            )
            """)
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_alarm_route ON alarm (route_id)"
        )
        await self._db.commit()
        logger.info("Alarm store ready at {}", self._db_path)

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    def _conn(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("AlarmRepository.init() 가 호출되지 않았습니다.")
        return self._db

    async def add(self, rule: dict) -> dict:
        cur = await self._conn().execute(
            "INSERT INTO alarm (provider, route_id, route_no, stop_id, stop_name, dir, "
            "n_stations, notify_minutes, start_time, end_time, weekdays, enabled, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                rule.get("provider", "incheon"), rule["route_id"], rule.get("route_no", ""),
                rule["stop_id"], rule.get("stop_name", ""), rule.get("dir", ""),
                rule.get("n_stations"), rule.get("notify_minutes"),
                rule.get("start_time"), rule.get("end_time"),
                rule.get("weekdays", ""), 1 if rule.get("enabled", True) else 0, time.time(),
            ),
        )
        await self._conn().commit()
        return await self.get(cur.lastrowid)

    async def get(self, alarm_id: int) -> dict | None:
        async with self._conn().execute("SELECT * FROM alarm WHERE id = ?", (alarm_id,)) as cur:
            row = await cur.fetchone()
        return _row_to_dict(row) if row else None

    async def list(self, route_id: str | None = None) -> list[dict]:
        if route_id:
            sql, args = "SELECT * FROM alarm WHERE route_id = ? ORDER BY id", (route_id,)
        else:
            sql, args = "SELECT * FROM alarm ORDER BY id", ()
        async with self._conn().execute(sql, args) as cur:
            return [_row_to_dict(r) for r in await cur.fetchall()]

    async def enabled(self) -> list[dict]:
        async with self._conn().execute("SELECT * FROM alarm WHERE enabled = 1") as cur:
            return [_row_to_dict(r) for r in await cur.fetchall()]

    async def delete(self, alarm_id: int) -> bool:
        cur = await self._conn().execute("DELETE FROM alarm WHERE id = ?", (alarm_id,))
        await self._conn().commit()
        return (cur.rowcount or 0) > 0

    async def set_enabled(self, alarm_id: int, enabled: bool) -> bool:
        cur = await self._conn().execute(
            "UPDATE alarm SET enabled = ? WHERE id = ?", (1 if enabled else 0, alarm_id)
        )
        await self._conn().commit()
        return (cur.rowcount or 0) > 0


def _row_to_dict(row: aiosqlite.Row) -> dict:
    d = dict(row)
    d["enabled"] = bool(d["enabled"])
    # weekdays "0,1,2" → [0,1,2]
    d["weekdays"] = [int(x) for x in str(d.get("weekdays") or "").split(",") if x != ""]
    return d
