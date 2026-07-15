"""인천 노선정보 서비스 (busRouteService): 노선번호 검색 + 경유 정류소(노선도)."""

from __future__ import annotations

import httpx
from loguru import logger

from app.services.bus_service import BusApiError, _parse_root, _to_int


class IncheonRouteService:
    """노선번호로 노선을 검색하고, 노선의 경유 정류소 목록을 조회한다."""

    def __init__(
        self,
        service_key: str,
        base_url: str,
        client: httpx.AsyncClient,
        use_mock: bool = False,
        timeout: float = 10.0,
    ) -> None:
        self._key = service_key
        self._base = base_url.rstrip("/")
        self._client = client
        self._use_mock = use_mock
        self._timeout = timeout

    async def search(self, route_no: str) -> list[dict]:
        """노선번호(부분일치)로 검색. ROUTEID/기점/종점 등을 반환."""
        if self._use_mock:
            return [r for r in _MOCK_ROUTES if route_no in r["no"]]

        text = await self._get(
            "/getBusRouteNo",
            {"routeNo": route_no, "numOfRows": "200", "pageNo": "1"},
            f"노선 검색({route_no})",
        )
        return parse_route_search_xml(text)

    async def stops(self, route_id: str) -> dict:
        """노선의 경유 정류소 목록(노선도). 방향(DIRCD)별로 순서가 들어있다."""
        if self._use_mock:
            return {"route_id": route_id, "stops": _MOCK_STOPS}

        text = await self._get(
            "/getBusRouteSectionList",
            {"routeId": route_id, "numOfRows": "500", "pageNo": "1"},
            f"노선도 조회({route_id})",
        )
        return {"route_id": route_id, "stops": parse_route_stops_xml(text)}

    async def _get(self, path: str, params: dict, what: str) -> str:
        url = self._base + path
        params = {"serviceKey": self._key, **params}
        try:
            resp = await self._client.get(url, params=params, timeout=self._timeout)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise BusApiError(f"{what} 실패: {exc}") from exc
        logger.debug("{} 응답 {}바이트", what, len(resp.text))
        return resp.text


def parse_route_search_xml(xml_text: str) -> list[dict]:
    root = _parse_root(xml_text)
    out: list[dict] = []
    for it in root.iter("itemList"):
        d = {c.tag: (c.text or "").strip() for c in it}
        if not d.get("ROUTEID"):
            continue
        out.append(
            {
                "no": d.get("ROUTENO", ""),
                "id": d.get("ROUTEID", ""),
                "tp": d.get("ROUTETPCD", ""),
                "origin": d.get("ORIGIN_BSTOPNM", ""),
                "dest": d.get("DEST_BSTOPNM", ""),
                "turn": d.get("TURN_BSTOPNM", ""),
            }
        )
    return out


def parse_route_stops_xml(xml_text: str) -> list[dict]:
    root = _parse_root(xml_text)
    stops: list[dict] = []
    for it in root.iter("itemList"):
        d = {c.tag: (c.text or "").strip() for c in it}
        if not d.get("BSTOPNM"):
            continue
        stops.append(
            {
                "seq": _to_int(d.get("BSTOPSEQ")) or 0,
                "name": d.get("BSTOPNM", ""),
                "dir": d.get("DIRCD", "0"),
                "id": d.get("BSTOPID", ""),
                "admin": d.get("ADMINNM", ""),
                "x": _to_float(d.get("POSX")),
                "y": _to_float(d.get("POSY")),
            }
        )
    stops.sort(key=lambda s: s["seq"])
    return stops


def _to_float(v: str | None) -> float | None:
    try:
        return float(v) if v else None
    except (TypeError, ValueError):
        return None


# 목업 (오프라인/테스트용)
_MOCK_ROUTES = [
    {"no": "1300", "id": "165000149", "tp": "4",
     "origin": "힐스테이트레이크송도4차", "dest": "동교동삼거리", "turn": "동교동삼거리"},
    {"no": "9100", "id": "165000160", "tp": "4",
     "origin": "숭의역(1번출구)", "dest": "강남역서초현대타워앞", "turn": "강남역서초현대타워앞"},
]
_MOCK_STOPS = [
    {"seq": 1, "name": "힐스테이트레이크송도4차", "dir": "0", "id": "164000786",
     "admin": "연수구", "x": 165797.7, "y": 431896.4},
    {"seq": 2, "name": "송도역", "dir": "0", "id": "164000123",
     "admin": "연수구", "x": 166500.0, "y": 433000.0},
    {"seq": 3, "name": "동교동삼거리", "dir": "0", "id": "100000999",
     "admin": "마포구", "x": 180000.0, "y": 450000.0},
    {"seq": 4, "name": "동교동삼거리", "dir": "1", "id": "100000999",
     "admin": "마포구", "x": 180000.0, "y": 450000.0},
    {"seq": 5, "name": "힐스테이트레이크송도4차", "dir": "1", "id": "164000786",
     "admin": "연수구", "x": 165797.7, "y": 431896.4},
]
