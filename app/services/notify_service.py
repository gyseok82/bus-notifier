"""여러 정류소를 순회하며 도착 조건 판단 + 중복 방지 + 카카오 발송을 조율."""

from __future__ import annotations

from loguru import logger

from app.config.settings import Settings, StopConfig
from app.models.bus import BusArrival
from app.repositories.dedup_repository import DedupRepository
from app.services.bus_service import BusApiError, BusProvider
from app.services.kakao_service import KakaoError, KakaoService


class NotifyService:
    """설정된 각 정류소의 도착 정보를 확인하고 조건 충족 시 알림을 보낸다."""

    def __init__(
        self,
        settings: Settings,
        providers: dict[str, BusProvider],
        kakao_service: KakaoService,
        dedup_repo: DedupRepository,
    ) -> None:
        self._settings = settings
        self._providers = providers
        self._kakao = kakao_service
        self._dedup = dedup_repo

    async def check_and_notify(self) -> int:
        """모든 정류소를 1회 확인하고 조건에 맞는 버스에 알림을 보낸다."""
        total = 0
        for stop in self._settings.stops:
            total += await self._process_stop(stop)
        if total:
            logger.info("총 {}건 알림 발송", total)
        return total

    async def get_arrivals(self, stop: StopConfig) -> list[BusArrival]:
        """정류소 하나의 (노선 필터링된) 도착 정보를 조회한다."""
        provider = self._providers.get(stop.provider)
        if provider is None:
            raise BusApiError(f"provider 미설정: {stop.provider}")
        arrivals = await provider.get_arrivals(stop.station_id)
        return self._filter_routes(arrivals, stop)

    async def _process_stop(self, stop: StopConfig) -> int:
        try:
            arrivals = await self.get_arrivals(stop)
        except BusApiError as exc:
            logger.error("[{}] 도착 정보 조회 실패: {}", stop.display_name(), exc)
            return 0

        sent = 0
        for arrival in arrivals:
            if not self._meets_condition(arrival, stop):
                continue
            key = f"{stop.provider}:{stop.station_id}:{arrival.dedup_key()}"
            if await self._dedup.is_notified(key):
                logger.debug("이미 알림 보낸 차량, 건너뜀: {}", key)
                continue
            try:
                await self._kakao.send_to_me(self.format_message(arrival, stop))
            except KakaoError as exc:
                logger.error("알림 발송 실패({}): {}", key, exc)
                continue
            await self._dedup.mark(key)
            sent += 1

        if sent:
            logger.info("[{}] {}건 알림 발송", stop.display_name(), sent)
        return sent

    def _filter_routes(self, arrivals: list[BusArrival], stop: StopConfig) -> list[BusArrival]:
        if not stop.routes:
            return arrivals
        wanted = {r.strip() for r in stop.routes}
        return [a for a in arrivals if a.route_no.strip() in wanted]

    def _meets_condition(self, arrival: BusArrival, stop: StopConfig) -> bool:
        """도착 분/남은 정류장 조건 중 하나라도 충족하면 True (정류소별 오버라이드 반영)."""
        notify_minutes = (
            stop.notify_minutes
            if stop.notify_minutes is not None
            else self._settings.notify_minutes
        )
        notify_stations = (
            stop.notify_stations
            if stop.notify_stations is not None
            else self._settings.notify_stations
        )

        minutes = arrival.arrival_minutes
        if minutes is not None and minutes <= notify_minutes:
            return True
        if (
            notify_stations is not None
            and arrival.remaining_stations is not None
            and arrival.remaining_stations <= notify_stations
        ):
            return True
        return False

    def format_message(self, arrival: BusArrival, stop: StopConfig | None = None) -> str:
        """카카오 알림 메시지 포맷."""
        header = f"🚌 {arrival.route_no}번 버스"
        if stop and stop.label:
            header += f" ({stop.label})"
        lines = [header, ""]
        if arrival.arrival_minutes is not None:
            lines.append(f"도착 예정 : {arrival.arrival_minutes}분")
        if arrival.remaining_stations is not None:
            lines.append(f"남은 정류장 : {arrival.remaining_stations}개")
        lines.append("")
        lines.append("지금 출발하세요.")
        return "\n".join(lines)
