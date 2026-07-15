"""의존성 조립(DI) 컨테이너."""

from __future__ import annotations

import httpx

from app.config.settings import Settings, load_settings
from app.repositories.dedup_repository import DedupRepository
from app.services.bus_service import BusProvider, build_providers
from app.services.kakao_service import KakaoService
from app.services.notify_service import NotifyService
from app.services.route_service import IncheonRouteService
from app.services.scheduler import BusScheduler


class Container:
    """애플리케이션 전역 의존성을 보관하고 생명주기를 관리한다."""

    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient,
        dedup_repo: DedupRepository,
        providers: dict[str, BusProvider],
        kakao_service: KakaoService,
        notify_service: NotifyService,
        route_service: IncheonRouteService,
        scheduler: BusScheduler,
    ) -> None:
        self.settings = settings
        self.client = client
        self.dedup_repo = dedup_repo
        self.providers = providers
        self.kakao_service = kakao_service
        self.notify_service = notify_service
        self.route_service = route_service
        self.scheduler = scheduler

    @classmethod
    async def create(cls, settings: Settings | None = None) -> Container:
        settings = settings or load_settings()

        # data.go.kr WAF 는 User-Agent 없는 요청을 차단하므로 브라우저 UA 를 지정한다.
        client = httpx.AsyncClient(
            headers={"User-Agent": "Mozilla/5.0 (bus-notifier)"},
        )
        dedup_repo = DedupRepository(settings.database_path, settings.dedup_ttl)
        await dedup_repo.init()

        providers = build_providers(settings, client)
        kakao_service = KakaoService(settings.kakao, client)
        notify_service = NotifyService(settings, providers, kakao_service, dedup_repo)
        route_service = IncheonRouteService(
            settings.incheon_api.service_key,
            settings.incheon_route_base_url,
            client,
            location_base_url=settings.incheon_location_base_url,
            use_mock=settings.incheon_route_use_mock,
        )
        scheduler = BusScheduler(notify_service, settings.check_interval)

        return cls(
            settings=settings,
            client=client,
            dedup_repo=dedup_repo,
            providers=providers,
            kakao_service=kakao_service,
            notify_service=notify_service,
            route_service=route_service,
            scheduler=scheduler,
        )

    async def aclose(self) -> None:
        self.scheduler.shutdown()
        await self.dedup_repo.close()
        await self.client.aclose()
