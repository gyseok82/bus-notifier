"""인천 버스 Open API 연동 서비스 (XML 응답)."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import httpx
from loguru import logger

from app.config.settings import BusApiSettings
from app.models.bus import BusArrival

# 인천(6280000) busArrivalService/getAllRouteBusArrivalList 실제 응답 필드명.
# 서비스별 편차 및 항목/목록 조회 차이에 대비해 후보군을 둔다.
# 주의: 도착정보 응답은 노선을 ROUTEID(내부 고유번호)로 식별한다. 사람이 읽는
# 노선번호("17")로 필터링하려면 busRouteService 로 ROUTEID 를 매핑해야 한다.
_ROUTE_KEYS = ("ROUTEID", "ROUTENO", "ROUTENM", "routeId", "ROUTE_NO")
_VEHICLE_KEYS = ("BUSID", "BUS_NUM_PLATE", "VEHICLEID", "PLATENO", "busId")
_ARRIVAL_SEC_KEYS = ("ARRIVALESTIMATETIME", "ARRIVALTIME", "arrivalTime", "PREDICTTIME")
_REMAIN_STATION_KEYS = ("REST_STOP_COUNT", "STATIONORD", "REMAINSTATION", "stationSeq")
_CONGESTION_KEYS = ("CONGESTION", "REMAIND_SEAT", "REMAINSEATCNT", "congestion")

# 정상 응답 코드
_OK_CODES = {"0", "00", "00000"}


class BusApiError(RuntimeError):
    """버스 API 호출/파싱 실패."""


class BusService:
    """정류장의 실시간 버스 도착 정보를 조회한다."""

    def __init__(self, settings: BusApiSettings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client

    async def get_arrivals(self, station_id: str) -> list[BusArrival]:
        """정류장의 모든 도착 예정 버스를 반환한다."""
        if self._settings.use_mock:
            return _mock_arrivals()

        url = self._settings.base_url.rstrip("/") + "/" + self._settings.endpoint.lstrip("/")
        params = {
            "serviceKey": self._settings.service_key,
            "bstopId": station_id,  # 인천 도착정보 API 의 정류소 파라미터명
            "numOfRows": "100",
            "pageNo": "1",
        }
        try:
            resp = await self._client.get(url, params=params, timeout=self._settings.timeout)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise BusApiError(f"버스 API 호출 실패: {exc}") from exc

        arrivals = _parse_xml(resp.text)
        logger.debug("정류장 {} 도착 버스 {}건 조회", station_id, len(arrivals))
        return arrivals


def _text(elem: ET.Element, keys: tuple[str, ...]) -> str | None:
    """item 요소에서 후보 태그명 중 하나의 텍스트를 대소문자 무시로 찾는다."""
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


def _parse_xml(xml_text: str) -> list[BusArrival]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise BusApiError(f"XML 파싱 실패: {exc}\n응답: {xml_text[:500]}") from exc

    # 헤더 결과 코드 검증
    code_elem = root.find(".//resultCode")
    if code_elem is None:
        code_elem = root.find(".//returnReasonCode")
    if code_elem is not None and (code_elem.text or "").strip() not in _OK_CODES:
        msg_elem = root.find(".//resultMsg")
        if msg_elem is None:
            msg_elem = root.find(".//returnAuthMsg")
        msg = (msg_elem.text if msg_elem is not None else "") or "알 수 없는 오류"
        raise BusApiError(f"API 오류 (code={code_elem.text}): {msg}")

    arrivals: list[BusArrival] = []
    for item in root.iter("item"):
        route_no = _text(item, _ROUTE_KEYS)
        vehicle_id = _text(item, _VEHICLE_KEYS)
        if not route_no:
            continue
        arrivals.append(
            BusArrival(
                route_no=route_no,
                vehicle_id=vehicle_id or f"{route_no}-unknown",
                arrival_seconds=_to_int(_text(item, _ARRIVAL_SEC_KEYS)),
                remaining_stations=_to_int(_text(item, _REMAIN_STATION_KEYS)),
                congestion=_text(item, _CONGESTION_KEYS),
                raw={child.tag: child.text for child in item},
            )
        )
    return arrivals


def _mock_arrivals() -> list[BusArrival]:
    """목업 모드용 샘플 데이터."""
    return [
        BusArrival(
            route_no="17",
            vehicle_id="INC-1234",
            arrival_seconds=7 * 60,
            remaining_stations=4,
            congestion="보통",
        ),
        BusArrival(
            route_no="43",
            vehicle_id="INC-5678",
            arrival_seconds=15 * 60,
            remaining_stations=9,
            congestion="여유",
        ),
    ]
