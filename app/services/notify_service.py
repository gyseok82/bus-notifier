"""도착 조건 판단 + 중복 방지 + 카카오 발송을 조율하는 서비스."""

from __future__ import annotations

from loguru import logger

from app.config.settings import Settings
from app.models.bus import BusArrival
from app.repositories.dedup_repository import DedupRepository
from app.services.bus_service import BusApiError, BusService
from app.services.kakao_service import KakaoError, KakaoService


class NotifyService:
    """버스 도착 정보를 확인하고 조건 충족 시 알림을 보낸다."""

    def __init__(
        self,
        settings: Settings,
        bus_service: BusService,
        kakao_service: KakaoService,
        dedup_repo: DedupRepository,
    ) -> None:
        self._settings = settings
        self._bus = bus_service
        self._kakao = kakao_service
        self._dedup = dedup_repo

    async def check_and_notify(self) -> int:
        """1회 조회 후 조건에 맞는 버스에 알림을 보낸다. 발송 건수를 반환한다."""
        try:
            arrivals = await self._bus.get_arrivals(self._settings.station_id)
        except BusApiError as exc:
            logger.error("도착 정보 조회 실패: {}", exc)
            return 0

        sent = 0
        for arrival in self.filter_routes(arrivals):
            if not self._meets_condition(arrival):
                continue
            key = arrival.dedup_key()
            if await self._dedup.is_notified(key):
                logger.debug("이미 알림 보낸 차량, 건너뜀: {}", key)
                continue
            try:
                await self._kakao.send_to_me(self.format_message(arrival))
            except KakaoError as exc:
                logger.error("알림 발송 실패({}): {}", key, exc)
                continue
            await self._dedup.mark(key)
            sent += 1

        if sent:
            logger.info("{}건 알림 발송", sent)
        return sent

    def filter_routes(self, arrivals: list[BusArrival]) -> list[BusArrival]:
        if not self._settings.routes:
            return arrivals
        wanted = {r.strip() for r in self._settings.routes}
        return [a for a in arrivals if a.route_no.strip() in wanted]

    def _meets_condition(self, arrival: BusArrival) -> bool:
        """도착 분/남은 정류장 조건 중 하나라도 충족하면 True."""
        minutes = arrival.arrival_minutes
        if minutes is not None and minutes <= self._settings.notify_minutes:
            return True
        if (
            self._settings.notify_stations is not None
            and arrival.remaining_stations is not None
            and arrival.remaining_stations <= self._settings.notify_stations
        ):
            return True
        return False

    def format_message(self, arrival: BusArrival) -> str:
        """카카오 알림 메시지 포맷."""
        lines = [f"🚌 {arrival.route_no}번 버스", ""]
        if arrival.arrival_minutes is not None:
            lines.append(f"도착 예정 : {arrival.arrival_minutes}분")
        if arrival.remaining_stations is not None:
            lines.append(f"남은 정류장 : {arrival.remaining_stations}개")
        lines.append("")
        lines.append("지금 출발하세요.")
        return "\n".join(lines)
