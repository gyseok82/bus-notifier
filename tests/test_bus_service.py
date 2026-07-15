"""XML 파서 테스트 (인천/서울)."""

from __future__ import annotations

import pytest

from app.services.bus_service import BusApiError, parse_incheon_xml, parse_seoul_xml

# 인천 busArrivalService 실제 응답 스키마(ServiceResult/msgHeader/msgBody/itemList) 기준
_INC_OK_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<ServiceResult>
  <comMsgHeader/>
  <msgHeader><resultCode>0</resultCode><resultMsg>정상</resultMsg><totalCount>1</totalCount></msgHeader>
  <msgBody>
    <itemList>
      <ROUTEID>165000017</ROUTEID>
      <BUSID>INC-1234</BUSID>
      <ARRIVALESTIMATETIME>420</ARRIVALESTIMATETIME>
      <REST_STOP_COUNT>4</REST_STOP_COUNT>
      <CONGESTION>보통</CONGESTION>
    </itemList>
  </msgBody>
</ServiceResult>"""

# resultCode=4 = 결과 없음 → 에러가 아니라 빈 리스트여야 함
_INC_NO_DATA_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<ServiceResult>
  <comMsgHeader/>
  <msgHeader><resultCode>4</resultCode><resultMsg>결과가 없습니다.</resultMsg></msgHeader>
  <msgBody/>
</ServiceResult>"""

# 서울 TOPIS getLowArrInfoByStId 응답: itemList 하나에 첫차/둘째차
_SEOUL_OK_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<ServiceResult>
  <msgHeader><headerCd>0</headerCd><headerMsg>정상</headerMsg></msgHeader>
  <msgBody>
    <itemList>
      <rtNm>1300</rtNm>
      <arsId>01001</arsId>
      <vehId1>111</vehId1>
      <plainNo1>서울70사1234</plainNo1>
      <traTime1>360</traTime1>
      <arrmsg1>6분후[3번째 전]</arrmsg1>
      <vehId2>222</vehId2>
      <plainNo2>서울70사5678</plainNo2>
      <traTime2>780</traTime2>
      <arrmsg2>13분후[7번째 전]</arrmsg2>
    </itemList>
  </msgBody>
</ServiceResult>"""

_INC_ERROR_XML = """<?xml version="1.0" encoding="UTF-8"?>
<OpenAPI_ServiceResponse>
  <cmmMsgHeader>
    <returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</returnAuthMsg>
    <returnReasonCode>30</returnReasonCode>
  </cmmMsgHeader>
</OpenAPI_ServiceResponse>"""


def test_parse_incheon_ok():
    arrivals = parse_incheon_xml(_INC_OK_XML)
    assert len(arrivals) == 1
    a = arrivals[0]
    assert a.route_no == "165000017"
    assert a.vehicle_id == "INC-1234"
    assert a.arrival_seconds == 420
    assert a.arrival_minutes == 7
    assert a.remaining_stations == 4
    assert a.congestion == "보통"


def test_parse_seoul_ok():
    arrivals = parse_seoul_xml(_SEOUL_OK_XML)
    assert len(arrivals) == 2  # 첫차 + 둘째차
    first, second = arrivals
    assert first.route_no == "1300"
    assert first.vehicle_id == "서울70사1234"
    assert first.arrival_seconds == 360
    assert first.arrival_minutes == 6
    assert second.arrival_seconds == 780


def test_parse_incheon_no_data_returns_empty():
    assert parse_incheon_xml(_INC_NO_DATA_XML) == []


def test_parse_incheon_error_raises():
    with pytest.raises(BusApiError):
        parse_incheon_xml(_INC_ERROR_XML)


def test_parse_bad_xml_raises():
    with pytest.raises(BusApiError):
        parse_incheon_xml("this is not xml <")
