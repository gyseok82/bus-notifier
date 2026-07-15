"""카카오톡 '나에게 보내기' 발송 서비스."""

from __future__ import annotations

import json

import httpx
from loguru import logger

from app.config.settings import KakaoSettings


class KakaoError(RuntimeError):
    """카카오 메시지 발송 실패."""


class KakaoService:
    """카카오톡 메모(나에게 보내기) API로 텍스트 메시지를 보낸다."""

    MEMO_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"

    def __init__(self, settings: KakaoSettings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client

    async def send_to_me(self, text: str, link_url: str = "https://www.kakaocorp.com") -> None:
        """나에게 텍스트 메시지를 보낸다. dry-run 이면 로그로만 출력한다."""
        if self._settings.is_dry_run:
            logger.info("[KAKAO dry-run] 발송 생략:\n{}", text)
            return

        template = {
            "object_type": "text",
            "text": text,
            "link": {"web_url": link_url, "mobile_web_url": link_url},
        }
        headers = {"Authorization": f"Bearer {self._settings.access_token}"}
        data = {"template_object": json.dumps(template, ensure_ascii=False)}

        try:
            resp = await self._client.post(self.MEMO_URL, headers=headers, data=data)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise KakaoError(
                f"카카오 발송 실패 ({exc.response.status_code}): {exc.response.text}"
            ) from exc
        except httpx.HTTPError as exc:
            raise KakaoError(f"카카오 발송 실패: {exc}") from exc

        logger.info("카카오 알림 발송 완료")
