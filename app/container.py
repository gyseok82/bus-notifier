"""의존성 조립(DI) 컨테이너."""

from __future__ import annotations

import httpx

from app.config.settings import Settings, load_settings
from app.repositories.dedup_repository import DedupRepository
from app.services.bus_service import BusService
from app.services.kakao_service import KakaoService
from app.services.notify_service import NotifyService
from app.services.scheduler import BusScheduler


class Container:
    """애플리케이션 전역 의존성을 보관하고 생명주기를 관리한다."""

    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient,
        dedup_repo: DedupRepository,
        bus_service: BusService,
        kakao_service: KakaoService,
        notify_service: NotifyService,
        scheduler: BusScheduler,
    ) -> None:
        self.settings = settings
        self.client = client
        self.dedup_repo = dedup_repo
        self.bus_service = bus_service
        self.kakao_service = kakao_service
        self.notify_service = notify_service
        self.scheduler = scheduler

    @classmethod
    async def create(cls, settings: Settings | None = None) -> Container:
        settings = settings or load_settings()

        client = httpx.AsyncClient()
        dedup_repo = DedupRepository(settings.database_path, settings.dedup_ttl)
        await dedup_repo.init()

        bus_service = BusService(settings.bus_api, client)
        kakao_service = KakaoService(settings.kakao, client)
        notify_service = NotifyService(settings, bus_service, kakao_service, dedup_repo)
        scheduler = BusScheduler(notify_service, settings.check_interval)

        return cls(
            settings=settings,
            client=client,
            dedup_repo=dedup_repo,
            bus_service=bus_service,
            kakao_service=kakao_service,
            notify_service=notify_service,
            scheduler=scheduler,
        )

    async def aclose(self) -> None:
        self.scheduler.shutdown()
        await self.dedup_repo.close()
        await self.client.aclose()
