"""XML 파서 테스트."""

from __future__ import annotations

import pytest

from app.services.bus_service import BusApiError, _parse_xml

# 인천 busArrivalService/getAllRouteBusArrivalList 실제 응답 스키마 기준
_OK_XML = """<?xml version="1.0" encoding="UTF-8"?>
<response>
  <header><resultCode>0</resultCode><resultMsg>NORMAL</resultMsg></header>
  <body>
    <items>
      <item>
        <ROUTEID>165000017</ROUTEID>
        <BUSID>INC-1234</BUSID>
        <BUS_NUM_PLATE>인천70바1234</BUS_NUM_PLATE>
        <ARRIVALESTIMATETIME>420</ARRIVALESTIMATETIME>
        <REST_STOP_COUNT>4</REST_STOP_COUNT>
        <CONGESTION>보통</CONGESTION>
      </item>
      <item>
        <ROUTEID>165000043</ROUTEID>
        <BUSID>INC-5678</BUSID>
        <ARRIVALESTIMATETIME>900</ARRIVALESTIMATETIME>
        <REST_STOP_COUNT>9</REST_STOP_COUNT>
      </item>
    </items>
  </body>
</response>"""

_ERROR_XML = """<?xml version="1.0" encoding="UTF-8"?>
<OpenAPI_ServiceResponse>
  <cmmMsgHeader>
    <returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</returnAuthMsg>
    <returnReasonCode>30</returnReasonCode>
  </cmmMsgHeader>
</OpenAPI_ServiceResponse>"""


def test_parse_ok():
    arrivals = _parse_xml(_OK_XML)
    assert len(arrivals) == 2
    first = arrivals[0]
    assert first.route_no == "165000017"
    assert first.vehicle_id == "INC-1234"
    assert first.arrival_seconds == 420
    assert first.arrival_minutes == 7
    assert first.remaining_stations == 4
    assert first.congestion == "보통"


def test_parse_error_code_raises():
    with pytest.raises(BusApiError):
        _parse_xml(_ERROR_XML)


def test_parse_bad_xml_raises():
    with pytest.raises(BusApiError):
        _parse_xml("this is not xml <")
