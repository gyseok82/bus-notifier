"""노선 검색/노선도 XML 파서 테스트."""

from __future__ import annotations

from app.services.route_service import (
    parse_bus_locations_xml,
    parse_route_search_xml,
    parse_route_stops_xml,
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
