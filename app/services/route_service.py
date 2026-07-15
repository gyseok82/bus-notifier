"""인천 노선정보 서비스 (busRouteService): 노선번호 검색 + 경유 정류소(노선도)."""

from __future__ import annotations

import httpx
from loguru import logger

from app.repositories.track_repository import RouteTrackRepository
from app.services.bus_service import BusApiError, _parse_root, _to_int

# 인천 버스 API 의 POSX/POSY 는 EPSG:5174(중부원점, Bessel) 투영좌표.
# TAGO 실측 WGS84 와 대조 결과 5174 가 오차 ~15m 로 일치(5181 은 ~310m 남서 편향).
# 지도 표시를 위해 WGS84 위경도로 변환한다. pyproj 미설치 시 좌표는 None.
try:
    from pyproj import Transformer

    _TM = Transformer.from_crs("EPSG:5174", "EPSG:4326", always_xy=True)
except Exception:  # noqa: BLE001 - pyproj 없거나 PROJ 데이터 문제 시 좌표 생략
    _TM = None


def _to_lonlat(x: float | None, y: float | None) -> tuple[float | None, float | None]:
    if _TM is None or x is None or y is None:
        return (None, None)
    try:
        lon, lat = _TM.transform(x, y)
        return (round(lon, 6), round(lat, 6))
    except Exception:  # noqa: BLE001
        return (None, None)


class IncheonRouteService:
    """노선번호로 노선을 검색하고, 노선의 경유 정류소 목록을 조회한다."""

    def __init__(
        self,
        service_key: str,
        base_url: str,
        client: httpx.AsyncClient,
        location_base_url: str = "https://apis.data.go.kr/6280000/busLocationService",
        use_mock: bool = False,
        timeout: float = 10.0,
        tago_base_url: str = "https://apis.data.go.kr/1613000/BusLcInfoInqireService",
        tago_city_code: str = "23",
        tago_route_prefix: str = "ICB",
        tago_enabled: bool = True,
        track_repo: RouteTrackRepository | None = None,
        track_min_hits: int = 2,
    ) -> None:
        self._key = service_key
        self._base = base_url.rstrip("/")
        self._loc_base = location_base_url.rstrip("/")
        self._client = client
        self._use_mock = use_mock
        self._timeout = timeout
        # 국토부 TAGO 실시간 GPS(위경도) 보완. 인천 위치서비스는 정류소 스냅만 제공.
        self._tago_base = tago_base_url.rstrip("/")
        self._tago_city = tago_city_code
        self._tago_prefix = tago_route_prefix
        self._tago_enabled = tago_enabled
        # 실시간 GPS 자취를 쌓아 도로 경로(노선도)를 학습하는 저장소(선택).
        self._track_repo = track_repo
        self._track_min_hits = track_min_hits

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

    async def buses(self, route_id: str) -> dict:
        """노선에서 현재 운행 중인 버스의 위치/차량번호."""
        if self._use_mock:
            return {"route_id": route_id, "buses": _MOCK_BUSES}

        url = self._loc_base + "/getBusRouteLocation"
        params = {"serviceKey": self._key, "routeId": route_id, "numOfRows": "200", "pageNo": "1"}
        try:
            resp = await self._client.get(url, params=params, timeout=self._timeout)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise BusApiError(f"버스 위치 조회({route_id}) 실패: {exc}") from exc
        buses = parse_bus_locations_xml(resp.text)
        # 인천 위치서비스는 여석/혼잡도/정류소를 주지만 좌표(위경도)는 없다.
        # TAGO 실시간 GPS 를 차량번호(plate)로 병합해 지도에 실좌표를 얹는다.
        if self._tago_enabled and buses:
            await self._merge_tago_positions(route_id, buses)
        # 실좌표가 붙은 버스 자취를 누적해 도로 경로를 학습한다(실패해도 조용히 무시).
        if self._track_repo is not None:
            try:
                await self._track_repo.record(route_id, buses)
            except Exception as exc:  # noqa: BLE001 - 학습 실패가 조회를 막지 않도록
                logger.debug("경로 자취 저장({}) 실패: {}", route_id, exc)
        return {"route_id": route_id, "buses": buses}

    async def track(self, route_id: str) -> dict:
        """누적된 실시간 GPS 자취(도로 경로 학습 결과)를 반환한다."""
        if self._track_repo is None:
            return {"route_id": route_id, "track": {}}
        track = await self._track_repo.track(route_id, min_hits=self._track_min_hits)
        return {"route_id": route_id, "track": track}

    async def _merge_tago_positions(self, route_id: str, buses: list[dict]) -> None:
        """TAGO 위경도를 차량번호로 병합. 실패 시 조용히 스킵(정류소 스냅으로 폴백)."""
        url = self._tago_base + "/getRouteAcctoBusLcList"
        params = {
            "serviceKey": self._key,
            "cityCode": self._tago_city,
            "routeId": self._tago_prefix + route_id,
            "numOfRows": "200",
            "pageNo": "1",
            "_type": "json",
        }
        try:
            resp = await self._client.get(url, params=params, timeout=self._timeout)
            resp.raise_for_status()
            positions = parse_tago_positions(resp.json())
        except (httpx.HTTPError, ValueError) as exc:  # ValueError = JSON 파싱 실패
            logger.debug("TAGO GPS 조회({}) 생략: {}", route_id, exc)
            return
        logger.debug("TAGO GPS({}) {}대 좌표 병합", route_id, len(positions))
        if not positions:
            return
        by_tail: dict[str, tuple[float, float]] = {}
        for plate, pos in positions.items():
            by_tail.setdefault(_plate_tail(plate), pos)
        for b in buses:
            plate = str(b.get("plate", "")).replace(" ", "")
            pos = positions.get(plate) or by_tail.get(_plate_tail(plate))
            if pos:
                b["lat"], b["lng"] = pos[0], pos[1]

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
        x = _to_float(d.get("POSX"))
        y = _to_float(d.get("POSY"))
        lng, lat = _to_lonlat(x, y)
        stops.append(
            {
                "seq": _to_int(d.get("BSTOPSEQ")) or 0,
                "name": d.get("BSTOPNM", ""),
                "dir": d.get("DIRCD", "0"),
                "id": d.get("BSTOPID", ""),
                "admin": d.get("ADMINNM", ""),
                "x": x,
                "y": y,
                "lat": lat,
                "lng": lng,
            }
        )
    stops.sort(key=lambda s: s["seq"])
    return stops


def parse_tago_positions(data: dict) -> dict[str, tuple[float, float]]:
    """TAGO getRouteAcctoBusLcList(JSON) → {차량번호: (lat, lng)}. 실좌표만 담는다."""
    out: dict[str, tuple[float, float]] = {}
    try:
        items = data["response"]["body"]["items"]
    except (KeyError, TypeError):
        return out
    if not items:  # 운행 없음이면 items 는 "" 로 온다
        return out
    rows = items.get("item") if isinstance(items, dict) else None
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list):
        return out
    for d in rows:
        plate = str(d.get("vehicleno", "")).replace(" ", "")
        lat, lng = d.get("gpslati"), d.get("gpslong")
        if not plate or lat is None or lng is None:
            continue
        try:
            out[plate] = (float(lat), float(lng))
        except (TypeError, ValueError):
            continue
    return out


def _plate_tail(plate: str) -> str:
    """차량번호에서 끝 4자리 숫자(노선 내 식별용)."""
    digits = "".join(ch for ch in str(plate) if ch.isdigit())
    return digits[-4:]


def parse_bus_locations_xml(xml_text: str) -> list[dict]:
    root = _parse_root(xml_text)
    out: list[dict] = []
    for it in root.iter("itemList"):
        d = {c.tag: (c.text or "").strip() for c in it}
        if not d.get("BUSID"):
            continue
        seat = _to_int(d.get("REMAIND_SEAT"))
        out.append(
            {
                "bus_id": d.get("BUSID", ""),
                "plate": d.get("BUS_NUM_PLATE", ""),
                "dir": d.get("DIRCD", "0"),
                "stop_seq": _to_int(d.get("LATEST_STOPSEQ")),
                "stop_id": d.get("LATEST_STOP_ID", ""),
                "stop_name": d.get("LATEST_STOP_NAME", ""),
                # 255 등은 정보없음으로 간주
                "seat": seat if (seat is not None and 0 <= seat <= 200) else None,
                "low_floor": d.get("LOW_TP_CD") == "1",
                "last": d.get("LASTBUSYN") == "1",
            }
        )
    return out


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
_MOCK_BUSES = [
    {"bus_id": "7331664", "plate": "인천73아1664", "dir": "0", "stop_seq": 2,
     "stop_id": "164000123", "stop_name": "송도역", "seat": 40, "low_floor": False, "last": False},
]
