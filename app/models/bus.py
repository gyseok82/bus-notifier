"""버스 도착 정보 도메인 모델."""

from __future__ import annotations

from pydantic import BaseModel, Field


class BusArrival(BaseModel):
    """정류장에 도착 예정인 버스 한 대의 정보."""

    route_no: str = Field(description="노선 번호 (예: '17')")
    vehicle_id: str = Field(description="차량 ID (중복 알림 방지 기준)")
    arrival_seconds: int | None = Field(default=None, description="도착까지 남은 시간(초)")
    remaining_stations: int | None = Field(default=None, description="남은 정류장 수")
    congestion: str | None = Field(default=None, description="혼잡도")
    raw: dict = Field(default_factory=dict, description="원본 응답(디버그용)")

    @property
    def arrival_minutes(self) -> int | None:
        """도착까지 남은 분. 초 정보가 없으면 None."""
        if self.arrival_seconds is None:
            return None
        return max(0, round(self.arrival_seconds / 60))

    def dedup_key(self) -> str:
        """중복 알림 방지 키 (노선 + 차량)."""
        return f"{route_key(self.route_no)}:{self.vehicle_id}"


def route_key(route_no: str) -> str:
    return route_no.strip()
