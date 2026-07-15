"""애플리케이션 설정. config.yaml + 환경변수(pydantic-settings)로 로드한다."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

ProviderName = Literal["incheon", "seoul"]


class ApiSettings(BaseModel):
    """지역 버스 Open API 접속 설정."""

    base_url: str = ""
    endpoint: str = ""
    service_key: str = ""
    timeout: float = 10.0
    # 실제 API 없이 동작 확인용 목업 모드
    use_mock: bool = False


class KakaoSettings(BaseModel):
    """카카오톡 '나에게 보내기' 설정."""

    access_token: str = ""
    # None 이면 access_token 유무로 자동 판단, True/False 로 강제 지정 가능
    dry_run: bool | None = None

    @property
    def is_dry_run(self) -> bool:
        if self.dry_run is not None:
            return self.dry_run
        return not self.access_token


class StopConfig(BaseModel):
    """알림을 받을 정류소 한 곳의 설정."""

    provider: ProviderName = "incheon"
    station_id: str
    label: str = ""
    # 이 정류소에서 대상으로 삼을 노선(인천=ROUTEID, 서울=노선번호/ID). 비우면 전체.
    routes: list[str] = Field(default_factory=list)
    # 정류소별 알림 조건 오버라이드(없으면 전역값 사용)
    notify_minutes: int | None = None
    notify_stations: int | None = None

    def display_name(self) -> str:
        return self.label or f"{self.provider}:{self.station_id}"


class Settings(BaseSettings):
    """전체 설정. 환경변수가 config.yaml 값보다 우선한다."""

    model_config = SettingsConfigDict(
        yaml_file="config.yaml",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
    )

    # 감시할 정류소 목록
    stops: list[StopConfig] = Field(default_factory=list)

    check_interval: int = 60

    # 전역 알림 조건(정류소별로 오버라이드 가능)
    notify_minutes: int = 10
    notify_stations: int | None = None

    # 지역별 API 설정
    incheon_api: ApiSettings = Field(
        default_factory=lambda: ApiSettings(
            base_url="https://apis.data.go.kr/6280000/busArrivalService",
            endpoint="/getAllRouteBusArrivalList",
        )
    )
    seoul_api: ApiSettings = Field(
        default_factory=lambda: ApiSettings(
            base_url="http://ws.bus.go.kr/api/rest/arrive",
            endpoint="/getLowArrInfoByStId",
        )
    )

    # 인천 노선정보 서비스(검색/노선도). 도착정보와 별개 서비스이며 이미 승인됨.
    incheon_route_base_url: str = "https://apis.data.go.kr/6280000/busRouteService"
    incheon_route_use_mock: bool = False

    kakao: KakaoSettings = Field(default_factory=KakaoSettings)

    database_path: str = "bus_notifier.db"
    dedup_ttl: int = 1800
    log_level: str = "INFO"

    # 서버 실행 설정
    host: str = "0.0.0.0"
    port: int = 8010

    def api_for(self, provider: ProviderName) -> ApiSettings:
        return self.seoul_api if provider == "seoul" else self.incheon_api

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # 우선순위: 초기값 > 환경변수 > .env > config.yaml
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls),
        )


def load_settings() -> Settings:
    """설정을 로드한다."""
    return Settings()
