"""지역별 버스 도착 정보 provider (인천/서울, XML 응답)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Protocol

import httpx
from loguru import logger

from app.config.settings import ApiSettings, ProviderName, Settings
from app.models.bus import BusArrival

# 정상 응답 코드
_OK_CODES = {"0", "00", "000", "00000"}
# "결과가 없습니다" 등 데이터 없음(정상이지만 빈 응답) 코드 — 에러로 취급하지 않는다.
_NO_DATA_CODES = {"4", "04", "3", "03"}


class BusApiError(RuntimeError):
    """버스 API 호출/파싱 실패."""


class BusProvider(Protocol):
    """정류소 도착 정보를 반환하는 provider 인터페이스."""

    async def get_arrivals(self, station_id: str) -> list[BusArrival]: ...


# --------------------------------------------------------------------------- #
# 공통 헬퍼
# --------------------------------------------------------------------------- #
def _text(elem: ET.Element, keys: tuple[str, ...]) -> str | None:
    """요소에서 후보 태그명 중 하나의 텍스트를 대소문자 무시로 찾는다."""
    lookup = {child.tag.lower(): (child.text or "").strip() for child in elem}
    for key in keys:
        val = lookup.get(key.lower())
        if val:
            return val
    return None


def _to_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _parse_root(xml_text: str) -> ET.Element:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise BusApiError(f"XML 파싱 실패: {exc}\n응답: {xml_text[:500]}") from exc

    # data.go.kr / 서울 TOPIS 공통 오류 헤더 검증
    for code_tag, msg_tags in (
        ("resultCode", ("resultMsg",)),
        ("returnReasonCode", ("returnAuthMsg",)),
        ("headerCd", ("headerMsg",)),
    ):
        code_elem = root.find(f".//{code_tag}")
        if code_elem is None:
            continue
        code = (code_elem.text or "").strip()
        if code in _OK_CODES or code in _NO_DATA_CODES:
            return root  # 정상 또는 결과 없음(빈 응답)
        msg = ""
        for mt in msg_tags:
            me = root.find(f".//{mt}")
            if me is not None and me.text:
                msg = me.text
                break
        raise BusApiError(f"API 오류 (code={code}): {msg or '알 수 없는 오류'}")
    return root


# --------------------------------------------------------------------------- #
# 인천 (data.go.kr 6280000 busArrivalService)
# --------------------------------------------------------------------------- #
# 도착정보는 노선을 ROUTEID(내부 고유번호)로 식별한다.
_INC_ROUTE_KEYS = ("ROUTEID", "ROUTENO", "ROUTENM", "routeId")
_INC_VEHICLE_KEYS = ("BUSID", "BUS_NUM_PLATE", "VEHICLEID", "PLATENO")
_INC_ARRIVAL_SEC_KEYS = ("ARRIVALESTIMATETIME", "ARRIVALTIME", "PREDICTTIME")
_INC_REMAIN_STATION_KEYS = ("REST_STOP_COUNT", "STATIONORD", "REMAINSTATION")
_INC_CONGESTION_KEYS = ("CONGESTION", "REMAIND_SEAT", "REMAINSEATCNT")


class IncheonBusProvider:
    """인천 busArrivalService/getAllRouteBusArrivalList 연동."""

    def __init__(self, settings: ApiSettings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client

    async def get_arrivals(self, station_id: str) -> list[BusArrival]:
        if self._settings.use_mock:
            return _mock_incheon()

        url = self._settings.base_url.rstrip("/") + "/" + self._settings.endpoint.lstrip("/")
        params = {
            "serviceKey": self._settings.service_key,
            "bstopId": station_id,
            "numOfRows": "100",
            "pageNo": "1",
        }
        try:
            resp = await self._client.get(url, params=params, timeout=self._settings.timeout)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise BusApiError(f"인천 버스 API 호출 실패: {exc}") from exc

        arrivals = parse_incheon_xml(resp.text)
        logger.debug("[인천] 정류장 {} 도착 버스 {}건", station_id, len(arrivals))
        return arrivals


def parse_incheon_xml(xml_text: str) -> list[BusArrival]:
    root = _parse_root(xml_text)
    arrivals: list[BusArrival] = []
    # 실제 응답은 <msgBody><itemList>...; 일부 문서 예시는 <item> → 둘 다 대응
    items = list(root.iter("itemList")) or list(root.iter("item"))
    for item in items:
        route_no = _text(item, _INC_ROUTE_KEYS)
        if not route_no:
            continue
        vehicle_id = _text(item, _INC_VEHICLE_KEYS)
        arrivals.append(
            BusArrival(
                route_no=route_no,
                vehicle_id=vehicle_id or f"{route_no}-unknown",
                arrival_seconds=_to_int(_text(item, _INC_ARRIVAL_SEC_KEYS)),
                remaining_stations=_to_int(_text(item, _INC_REMAIN_STATION_KEYS)),
                congestion=_text(item, _INC_CONGESTION_KEYS),
                raw={child.tag: child.text for child in item},
            )
        )
    return arrivals


# --------------------------------------------------------------------------- #
# 서울 (TOPIS ws.bus.go.kr 버스도착정보조회)
# --------------------------------------------------------------------------- #
# 서울은 노선명(rtNm)이 사람이 읽는 번호("1300")이고, 한 itemList 에 첫차/둘째차 정보가
# traTime1/vehId1/plainNo1, traTime2/vehId2/plainNo2 로 나뉘어 들어온다.
# NOTE: 실제 키 활성화 후 응답으로 필드명을 최종 보정할 것.


class SeoulBusProvider:
    """서울 TOPIS 버스도착정보 연동 (정류소 stId 기준)."""

    def __init__(self, settings: ApiSettings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client

    async def get_arrivals(self, station_id: str) -> list[BusArrival]:
        if self._settings.use_mock:
            return _mock_seoul()

        url = self._settings.base_url.rstrip("/") + "/" + self._settings.endpoint.lstrip("/")
        params = {"serviceKey": self._settings.service_key, "stId": station_id}
        try:
            resp = await self._client.get(url, params=params, timeout=self._settings.timeout)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise BusApiError(f"서울 버스 API 호출 실패: {exc}") from exc

        arrivals = parse_seoul_xml(resp.text)
        logger.debug("[서울] 정류장 {} 도착 버스 {}건", station_id, len(arrivals))
        return arrivals


def _seoul_bus(item: ET.Element, idx: str) -> BusArrival | None:
    """itemList 요소에서 idx('1'|'2')번째 버스를 뽑는다. 정보 없으면 None."""
    lookup = {child.tag.lower(): (child.text or "").strip() for child in item}
    tra = lookup.get(f"tratime{idx}")
    arrmsg = lookup.get(f"arrmsg{idx}")
    if not tra and not arrmsg:
        return None
    route_no = lookup.get("rtnm") or lookup.get("busrouteid") or ""
    if not route_no:
        return None
    vehicle = lookup.get(f"plainno{idx}") or lookup.get(f"vehid{idx}") or f"{route_no}-{idx}"
    return BusArrival(
        route_no=route_no,
        vehicle_id=vehicle,
        arrival_seconds=_to_int(tra),
        remaining_stations=None,  # 서울 응답엔 남은 정류장 수 직접 필드가 없음
        congestion=lookup.get(f"congetion{idx}") or lookup.get(f"congestion{idx}"),
        raw={"arrmsg": arrmsg or "", **{k: v for k, v in lookup.items()}},
    )


def parse_seoul_xml(xml_text: str) -> list[BusArrival]:
    root = _parse_root(xml_text)
    arrivals: list[BusArrival] = []
    # 서울 응답 항목 태그는 itemList (일부 오퍼레이션은 item)
    items = list(root.iter("itemList")) or list(root.iter("item"))
    for item in items:
        for idx in ("1", "2"):
            bus = _seoul_bus(item, idx)
            if bus is not None:
                arrivals.append(bus)
    return arrivals


# --------------------------------------------------------------------------- #
# Provider 팩토리
# --------------------------------------------------------------------------- #
def build_provider(
    provider: ProviderName, settings: Settings, client: httpx.AsyncClient
) -> BusProvider:
    api = settings.api_for(provider)
    if provider == "seoul":
        return SeoulBusProvider(api, client)
    return IncheonBusProvider(api, client)


def build_providers(settings: Settings, client: httpx.AsyncClient) -> dict[str, BusProvider]:
    """설정에 등장하는 provider 들을 모두 생성한다."""
    names = {stop.provider for stop in settings.stops} or {"incheon"}
    return {name: build_provider(name, settings, client) for name in names}


# --------------------------------------------------------------------------- #
# 목업 데이터
# --------------------------------------------------------------------------- #
def _mock_incheon() -> list[BusArrival]:
    return [
        BusArrival(
            route_no="165000017",
            vehicle_id="INC-1234",
            arrival_seconds=7 * 60,
            remaining_stations=4,
            congestion="보통",
        ),
        BusArrival(
            route_no="165000043",
            vehicle_id="INC-5678",
            arrival_seconds=15 * 60,
            remaining_stations=9,
            congestion="여유",
        ),
    ]


def _mock_seoul() -> list[BusArrival]:
    return [
        BusArrival(route_no="1300", vehicle_id="서울70사1234", arrival_seconds=6 * 60),
        BusArrival(route_no="9100", vehicle_id="서울70사5678", arrival_seconds=12 * 60),
    ]
