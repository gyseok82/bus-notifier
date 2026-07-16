"""노선 검색/노선도 XML 파서 테스트."""

from __future__ import annotations

import httpx
import pytest

from app.services.bus_service import BusApiError
from app.services.route_service import (
    IncheonRouteService,
    _plate_tail,
    parse_bus_locations_xml,
    parse_route_search_xml,
    parse_route_stops_xml,
    parse_tago_positions,
)

_BUSES_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<ServiceResult><comMsgHeader/>
  <msgHeader><resultCode>0</resultCode><resultMsg>정상</resultMsg><totalCount>2</totalCount></msgHeader>
  <msgBody>
    <itemList><BUSID>7331664</BUSID><BUS_NUM_PLATE>인천73아1664</BUS_NUM_PLATE><DIRCD>0</DIRCD>
      <LATEST_STOPSEQ>13</LATEST_STOPSEQ><LATEST_STOP_ID>120000674</LATEST_STOP_ID>
      <LATEST_STOP_NAME>구로디지털단지역</LATEST_STOP_NAME><REMAIND_SEAT>40</REMAIND_SEAT><LOW_TP_CD>0</LOW_TP_CD></itemList>
    <itemList><BUSID>7331680</BUSID><BUS_NUM_PLATE>인천73아1680</BUS_NUM_PLATE><DIRCD>1</DIRCD>
      <LATEST_STOPSEQ>8</LATEST_STOPSEQ><LATEST_STOP_ID>168001438</LATEST_STOP_ID>
      <LATEST_STOP_NAME>이음대로</LATEST_STOP_NAME><REMAIND_SEAT>255</REMAIND_SEAT><LOW_TP_CD>1</LOW_TP_CD></itemList>
  </msgBody>
</ServiceResult>"""

_SEARCH_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<ServiceResult><comMsgHeader/>
  <msgHeader><resultCode>0</resultCode><resultMsg>정상</resultMsg><totalCount>1</totalCount></msgHeader>
  <msgBody>
    <itemList>
      <ROUTEID>165000149</ROUTEID><ROUTENO>1300</ROUTENO><ROUTETPCD>4</ROUTETPCD>
      <ORIGIN_BSTOPNM>힐스테이트레이크송도4차</ORIGIN_BSTOPNM>
      <DEST_BSTOPNM>동교동삼거리</DEST_BSTOPNM><TURN_BSTOPNM>동교동삼거리</TURN_BSTOPNM>
    </itemList>
  </msgBody>
</ServiceResult>"""

_STOPS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<ServiceResult><comMsgHeader/>
  <msgHeader><resultCode>0</resultCode><resultMsg>정상</resultMsg><totalCount>3</totalCount></msgHeader>
  <msgBody>
    <itemList><BSTOPSEQ>2</BSTOPSEQ><BSTOPNM>송도역</BSTOPNM><DIRCD>0</DIRCD>
      <BSTOPID>164000123</BSTOPID><ADMINNM>연수구</ADMINNM><POSX>166500.0</POSX><POSY>433000.0</POSY></itemList>
    <itemList><BSTOPSEQ>1</BSTOPSEQ><BSTOPNM>송도4차</BSTOPNM><DIRCD>0</DIRCD>
      <BSTOPID>164000786</BSTOPID><ADMINNM>연수구</ADMINNM><POSX>165797.7</POSX><POSY>431896.4</POSY></itemList>
    <itemList><BSTOPSEQ>3</BSTOPSEQ><BSTOPNM>동교동</BSTOPNM><DIRCD>1</DIRCD>
      <BSTOPID>100000999</BSTOPID><ADMINNM>마포구</ADMINNM><POSX>180000.0</POSX><POSY>450000.0</POSY></itemList>
  </msgBody>
</ServiceResult>"""


def test_parse_route_search():
    out = parse_route_search_xml(_SEARCH_XML)
    assert len(out) == 1
    r = out[0]
    assert r["no"] == "1300"
    assert r["id"] == "165000149"
    assert r["tp"] == "4"
    assert r["origin"] == "힐스테이트레이크송도4차"
    assert r["dest"] == "동교동삼거리"


def test_parse_route_stops_sorted_and_typed():
    stops = parse_route_stops_xml(_STOPS_XML)
    assert len(stops) == 3
    # seq 로 정렬됨
    assert [s["seq"] for s in stops] == [1, 2, 3]
    assert stops[0]["name"] == "송도4차"
    assert stops[0]["dir"] == "0"
    assert stops[0]["x"] == 165797.7
    assert stops[2]["dir"] == "1"
    # EPSG:5181 → WGS84 변환 (송도 ≈ 126.61, 37.38)
    assert stops[0]["lat"] is not None
    assert 37.3 < stops[0]["lat"] < 37.5
    assert 126.5 < stops[0]["lng"] < 126.7


def test_parse_bus_locations():
    buses = parse_bus_locations_xml(_BUSES_XML)
    assert len(buses) == 2
    b = buses[0]
    assert b["plate"] == "인천73아1664"
    assert b["dir"] == "0"
    assert b["stop_seq"] == 13
    assert b["stop_name"] == "구로디지털단지역"
    assert b["seat"] == 40
    # REMAIND_SEAT=255 는 정보없음 → None
    assert buses[1]["seat"] is None
    assert buses[1]["low_floor"] is True


def test_parse_tago_positions():
    data = {
        "response": {"body": {"items": {"item": [
            {"vehicleno": "인천73아1664", "gpslati": 37.4, "gpslong": 126.7, "nodenm": "A"},
            {"vehicleno": "인천73아1680", "gpslati": None, "gpslong": 126.9},  # 좌표 없음 → 제외
        ]}}}
    }
    pos = parse_tago_positions(data)
    assert pos == {"인천73아1664": (37.4, 126.7)}


def test_parse_tago_positions_edge_cases():
    # 운행 없음(items="") / 단일 item(dict) / 깨진 응답 모두 안전하게 처리
    assert parse_tago_positions({"response": {"body": {"items": ""}}}) == {}
    single = {"response": {"body": {"items": {"item": {"vehicleno": "인천70바1", "gpslati": 37.5, "gpslong": 127.0}}}}}
    assert parse_tago_positions(single) == {"인천70바1": (37.5, 127.0)}
    assert parse_tago_positions({"nope": 1}) == {}


def test_plate_tail():
    assert _plate_tail("인천73아1664") == "1664"
    assert _plate_tail("인천70바6116") == "6116"


class _FakeResp:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        pass


class _FakeClient:
    """호출 횟수를 세고, fail_after 호출 이후엔 HTTP 오류를 던지는 가짜 클라이언트."""

    def __init__(self, text: str, fail_after: int | None = None) -> None:
        self._text = text
        self.calls = 0
        self._fail_after = fail_after

    async def get(self, url, params=None, timeout=None):  # noqa: ANN001
        self.calls += 1
        if self._fail_after is not None and self.calls > self._fail_after:
            raise httpx.ConnectError("boom")
        return _FakeResp(self._text)


def _svc(client, ttl: float):
    return IncheonRouteService(
        "k", "http://b", client, tago_enabled=False, buses_cache_ttl=ttl
    )


@pytest.mark.asyncio
async def test_buses_cache_reduces_upstream_calls():
    client = _FakeClient(_BUSES_XML)
    svc = _svc(client, ttl=100)
    r1 = await svc.buses("R1")
    r2 = await svc.buses("R1")
    assert client.calls == 1  # 두 번째는 캐시
    assert r1 == r2 and len(r1["buses"]) == 2


@pytest.mark.asyncio
async def test_buses_falls_back_to_stale_cache_on_error():
    client = _FakeClient(_BUSES_XML, fail_after=1)  # 1회 성공 후 오류
    svc = _svc(client, ttl=0)  # 매번 상류 재시도
    ok = await svc.buses("R1")
    stale = await svc.buses("R1")  # 재시도 실패 → 마지막 캐시
    assert stale == ok
    assert client.calls == 2


@pytest.mark.asyncio
async def test_buses_error_without_cache_raises():
    client = _FakeClient(_BUSES_XML, fail_after=0)  # 처음부터 오류
    svc = _svc(client, ttl=0)
    with pytest.raises(BusApiError):
        await svc.buses("R1")
