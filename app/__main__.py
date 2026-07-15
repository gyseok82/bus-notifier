"""`python -m app` 실행 진입점. config 의 host/port 로 uvicorn 을 띄운다."""

from __future__ import annotations

import uvicorn

from app.config.settings import load_settings


def main() -> None:
    settings = load_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_config=None,  # loguru 로 통합(lifespan 에서 설정)
    )


if __name__ == "__main__":
    main()
