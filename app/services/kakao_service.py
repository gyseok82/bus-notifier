"""카카오톡 '나에게 보내기' 발송 서비스 (access_token 자동 갱신 포함)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
from loguru import logger

from app.config.settings import KakaoSettings


class KakaoError(RuntimeError):
    """카카오 메시지 발송 실패."""


class KakaoService:
    """카카오톡 메모(나에게 보내기) API로 텍스트 메시지를 보낸다.

    access_token 이 만료(401)되면 refresh_token 으로 자동 재발급 후 1회 재시도한다.
    """

    MEMO_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
    TOKEN_URL = "https://kauth.kakao.com/oauth/token"

    def __init__(self, settings: KakaoSettings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client
        self._access = settings.access_token
        self._refresh = settings.refresh_token
        self._token_path = Path(settings.token_path) if settings.token_path else None
        self._load_tokens()

    @property
    def is_dry_run(self) -> bool:
        # 설정이 dry_run 이거나, 발송할 access_token 이 없으면 실제 발송하지 않는다.
        return self._settings.is_dry_run or not self._access

    def _load_tokens(self) -> None:
        if self._token_path and self._token_path.exists():
            try:
                d = json.loads(self._token_path.read_text(encoding="utf-8"))
                self._access = d.get("access_token") or self._access
                self._refresh = d.get("refresh_token") or self._refresh
                logger.info("카카오 토큰 파일 로드됨: {}", self._token_path)
            except Exception as exc:  # noqa: BLE001
                logger.warning("카카오 토큰 파일 로드 실패: {}", exc)

    def _save_tokens(self) -> None:
        if not self._token_path:
            return
        try:
            self._token_path.write_text(
                json.dumps({"access_token": self._access, "refresh_token": self._refresh},
                           ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("카카오 토큰 저장 실패: {}", exc)

    async def send_to_me(self, text: str, link_url: str = "http://localhost:8010") -> None:
        """나에게 텍스트 메시지를 보낸다. dry-run 이면 로그로만 출력한다."""
        if self.is_dry_run:
            logger.info("[KAKAO dry-run] 발송 생략:\n{}", text)
            return
        try:
            await self._post_memo(text, link_url)
        except httpx.HTTPStatusError as exc:
            # 401 = 토큰 만료 추정 → refresh 후 1회 재시도
            if exc.response.status_code == 401 and self._can_refresh():
                logger.info("카카오 토큰 만료 추정, 갱신 시도")
                await self._do_refresh()
                try:
                    await self._post_memo(text, link_url)
                    return
                except httpx.HTTPError as exc2:
                    raise KakaoError(f"카카오 발송 실패(갱신 후): {exc2}") from exc2
            raise KakaoError(
                f"카카오 발송 실패 ({exc.response.status_code}): {exc.response.text}"
            ) from exc
        except httpx.HTTPError as exc:
            raise KakaoError(f"카카오 발송 실패: {exc}") from exc

    async def _post_memo(self, text: str, link_url: str) -> None:
        template = {
            "object_type": "text",
            "text": text,
            "link": {"web_url": link_url, "mobile_web_url": link_url},
        }
        headers = {"Authorization": f"Bearer {self._access}"}
        data = {"template_object": json.dumps(template, ensure_ascii=False)}
        resp = await self._client.post(self.MEMO_URL, headers=headers, data=data)
        resp.raise_for_status()
        logger.info("카카오 알림 발송 완료")

    def _can_refresh(self) -> bool:
        return bool(self._settings.rest_api_key and self._refresh)

    async def _do_refresh(self) -> None:
        if not self._can_refresh():
            raise KakaoError("토큰 갱신 불가: rest_api_key/refresh_token 이 필요합니다.")
        data = {
            "grant_type": "refresh_token",
            "client_id": self._settings.rest_api_key,
            "refresh_token": self._refresh,
        }
        try:
            resp = await self._client.post(self.TOKEN_URL, data=data)
            resp.raise_for_status()
            tok = resp.json()
        except httpx.HTTPError as exc:
            raise KakaoError(f"카카오 토큰 갱신 실패: {exc}") from exc
        self._access = tok["access_token"]
        if tok.get("refresh_token"):  # 갱신 시 새 refresh_token 이 올 수도 있다
            self._refresh = tok["refresh_token"]
        self._save_tokens()
        logger.info("카카오 access_token 갱신 완료")
