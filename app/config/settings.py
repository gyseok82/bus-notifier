"""애플리케이션 설정. config.yaml + 환경변수(pydantic-settings)로 로드한다."""

from __future__ import annotations

from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)


class BusApiSettings(BaseModel):
    """인천 버스 Open API 접속 설정."""

    base_url: str = "https://apis.data.go.kr/6280000/busArrivalService"
    endpoint: str = "/getAllRouteBusArrivalList"
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


class Settings(BaseSettings):
    """전체 설정. 환경변수가 config.yaml 값보다 우선한다."""

    model_config = SettingsConfigDict(
        yaml_file="config.yaml",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
    )

    station_id: str
    routes: list[str] = Field(default_factory=list)
    check_interval: int = 60

    # 알림 조건
    notify_minutes: int = 10
    notify_stations: int | None = None

    bus_api: BusApiSettings = Field(default_factory=BusApiSettings)
    kakao: KakaoSettings = Field(default_factory=KakaoSettings)

    database_path: str = "bus_notifier.db"
    dedup_ttl: int = 1800
    log_level: str = "INFO"

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
