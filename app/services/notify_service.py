"""여러 정류소를 순회하며 도착 조건 판단 + 중복 방지 + 카카오 발송을 조율."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from loguru import logger

from app.config.settings import Settings, StopConfig
from app.models.bus import BusArrival
from app.repositories.alarm_repository import AlarmRepository
from app.repositories.dedup_repository import DedupRepository
from app.services.bus_service import BusApiError, BusProvider
from app.services.kakao_service import KakaoError, KakaoService

_SEOUL = ZoneInfo("Asia/Seoul")


class NotifyService:
    """설정된 각 정류소의 도착 정보를 확인하고 조건 충족 시 알림을 보낸다."""

    def __init__(
        self,
        settings: Settings,
        providers: dict[str, BusProvider],
        kakao_service: KakaoService,
        dedup_repo: DedupRepository,
        alarm_repo: AlarmRepository | None = None,
    ) -> None:
        self._settings = settings
        self._providers = providers
        self._kakao = kakao_service
        self._dedup = dedup_repo
        self._alarm = alarm_repo

    async def check_and_notify(self, *, now: datetime | None = None) -> int:
        """config 정류소 + 사용자 알림 규칙을 1회 확인하고 조건 충족 시 알림을 보낸다."""
        total = 0
        for stop in self._settings.stops:
            total += await self._process_stop(stop)
        total += await self.check_alarm_rules(now=now)
        if total:
            logger.info("총 {}건 알림 발송", total)
        return total

    # ------------------------------------------------------------------ #
    # 화면에서 만든 사용자 알림 규칙 처리
    # ------------------------------------------------------------------ #
    async def check_alarm_rules(self, *, now: datetime | None = None) -> int:
        """DB 알림 규칙을 확인한다. 시간대·요일이 맞고 N정거장/도착분 조건 충족 시 발송."""
        if self._alarm is None:
            return 0
        rules = await self._alarm.enabled()
        if not rules:
            return 0
        now = now or datetime.now(_SEOUL)
        # 같은 정류장은 한 번만 조회하도록 규칙을 정류장별로 묶는다.
        by_stop: dict[tuple[str, str], list[dict]] = {}
        for rule in rules:
            if not self._within_window(rule, now):
                continue
            by_stop.setdefault((rule.get("provider", "incheon"), rule["stop_id"]), []).append(rule)

        sent = 0
        for (provider_name, stop_id), stop_rules in by_stop.items():
            provider = self._providers.get(provider_name)
            if provider is None:
                logger.error("알림 규칙 provider 미설정: {}", provider_name)
                continue
            try:
                arrivals = await provider.get_arrivals(stop_id)
            except BusApiError as exc:
                logger.error("[알림] 정류장 {} 도착 조회 실패: {}", stop_id, exc)
                continue
            for rule in stop_rules:
                for arrival in arrivals:
                    if arrival.route_no.strip() != str(rule["route_id"]).strip():
                        continue
                    if not self._alarm_condition_met(arrival, rule):
                        continue
                    key = f"alarm:{rule['id']}:{arrival.dedup_key()}"
                    if await self._dedup.is_notified(key):
                        continue
                    try:
                        await self._kakao.send_to_me(self.format_alarm_message(arrival, rule))
                    except KakaoError as exc:
                        logger.error("알림 발송 실패({}): {}", key, exc)
                        continue
                    await self._dedup.mark(key)
                    sent += 1
        if sent:
            logger.info("[알림 규칙] {}건 발송", sent)
        return sent

    async def test_rule(self, rule: dict) -> dict:
        """규칙을 즉시 테스트한다(시간대 무시). 조건 맞는 버스가 있으면 실제 문구를,
        없으면 미리보기 문구를 '나에게 보내기'로 발송하고 결과를 반환한다."""
        provider = self._providers.get(rule.get("provider", "incheon"))
        if provider is None:
            raise BusApiError(f"provider 미설정: {rule.get('provider')}")
        # 도착정보 조회가 실패(할당량/일시장애)해도 테스트는 미리보기로 계속 진행한다.
        try:
            arrivals = await provider.get_arrivals(rule["stop_id"])
        except BusApiError as exc:
            logger.warning("[알림 테스트] 도착 조회 실패, 미리보기로 진행: {}", exc)
            arrivals = []
        matched = next(
            (a for a in arrivals
             if a.route_no.strip() == str(rule["route_id"]).strip()
             and self._alarm_condition_met(a, rule)),
            None,
        )
        message = self.format_alarm_message(matched, rule) if matched else self._preview_message(rule)
        if self._kakao.is_dry_run:
            logger.info("[알림 테스트 dry-run]\n{}", message)
            return {"matched": matched is not None, "sent": False, "dry_run": True, "message": message}
        try:
            await self._kakao.send_to_me(message)
        except KakaoError as exc:
            return {"matched": matched is not None, "sent": False, "dry_run": False,
                    "error": str(exc), "message": message}
        return {"matched": matched is not None, "sent": True, "dry_run": False, "message": message}

    def _preview_message(self, rule: dict) -> str:
        no = rule.get("route_no") or rule["route_id"]
        cond = []
        if rule.get("n_stations") is not None:
            cond.append(f"{rule['n_stations']}정거장 전")
        if rule.get("notify_minutes") is not None:
            cond.append(f"{rule['notify_minutes']}분 전")
        return "\n".join([
            f"🔔 [테스트] {no}번 버스 알림", f"📍 {rule.get('stop_name', '')}", "",
            "설정한 조건: " + (" 또는 ".join(cond) or "-"),
            "", "지금은 조건에 맞는 버스가 없어 미리보기로 보냈어요.",
            "실제로는 버스가 이 조건에 들어오면 이렇게 알림이 옵니다.",
        ])

    def _within_window(self, rule: dict, now: datetime) -> bool:
        """규칙의 요일·시간대 안에 있는지."""
        weekdays = rule.get("weekdays") or []
        if weekdays and now.weekday() not in weekdays:  # 월=0 ~ 일=6
            return False
        start, end = rule.get("start_time"), rule.get("end_time")
        s, e = _hm(start), _hm(end)
        if s is None or e is None:
            return True  # 시간대 미지정 = 상시
        cur = now.hour * 60 + now.minute
        return s <= cur <= e if s <= e else (cur >= s or cur <= e)  # 자정 넘김 지원

    def _alarm_condition_met(self, arrival: BusArrival, rule: dict) -> bool:
        n = rule.get("n_stations")
        m = rule.get("notify_minutes")
        remain, minutes = arrival.remaining_stations, arrival.arrival_minutes
        if n is not None and remain is not None and remain <= n:
            return True
        if m is not None and minutes is not None and minutes <= m:
            return True
        return False

    def format_alarm_message(self, arrival: BusArrival, rule: dict) -> str:
        no = rule.get("route_no") or arrival.route_no
        lines = [f"🚌 {no}번 버스", f"📍 {rule.get('stop_name', '')}", ""]
        if arrival.remaining_stations is not None:
            lines.append(f"남은 정류장 : {arrival.remaining_stations}개")
        if arrival.arrival_minutes is not None:
            lines.append(f"도착 예정 : {arrival.arrival_minutes}분")
        lines += ["", "곧 도착합니다. 준비하세요!"]
        return "\n".join(lines)

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


def _hm(value: str | None) -> int | None:
    """'HH:MM' → 자정 기준 분. 형식이 아니면 None."""
    if not value or ":" not in value:
        return None
    try:
        h, m = value.split(":", 1)
        return int(h) * 60 + int(m)
    except (TypeError, ValueError):
        return None
