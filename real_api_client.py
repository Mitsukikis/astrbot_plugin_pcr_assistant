import asyncio
import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class RealAPIError(RuntimeError):
    pass


@dataclass
class PCRRealAPIClient:
    base_url: str
    timeout_seconds: int = 20

    def _url(self, path: str, params: dict | None = None) -> str:
        url = self.base_url.rstrip("/") + "/" + path.lstrip("/")
        if params:
            query = urlencode({
                key: value for key, value in params.items()
                if value is not None and value != ""
            })
            if query:
                url += "?" + query
        return url

    async def get_json(self, path: str, params: dict | None = None) -> dict:
        return await asyncio.to_thread(self._get_json_sync, path, params or {})

    async def post_json(self, path: str, payload: dict | None = None) -> dict:
        return await asyncio.to_thread(self._post_json_sync, path, payload or {})

    def _get_json_sync(self, path: str, params: dict) -> dict:
        url = self._url(path, params)
        return self._request_json(url)

    def _post_json_sync(self, path: str, payload: dict) -> dict:
        url = self._url(path)
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return self._request_json(request)

    def _request_json(self, request_or_url) -> dict:
        try:
            with urlopen(request_or_url, timeout=self.timeout_seconds) as resp:
                payload = resp.read().decode("utf-8")
        except HTTPError as exc:
            payload = exc.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(payload)
                message = data.get("message") or data.get("error") or payload
            except json.JSONDecodeError:
                message = payload or str(exc)
            raise RealAPIError(message) from exc
        except URLError as exc:
            raise RealAPIError(str(exc.reason)) from exc
        except TimeoutError as exc:
            raise RealAPIError("request timed out") from exc

        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise RealAPIError("invalid json from real api") from exc
        if isinstance(data, dict) and data.get("ok") is False:
            raise RealAPIError(data.get("message") or data.get("error") or "real api error")
        if not isinstance(data, dict):
            raise RealAPIError("unexpected real api response")
        return data

    async def profile(
        self,
        uid: str,
        user: str | None = None,
        account: str | None = None,
    ) -> dict:
        return await self.get_json("profile", {"uid": uid, "user": user, "account": account})

    async def arena_history(
        self,
        kind: str = "jjc",
        user: str | None = None,
        account: str | None = None,
    ) -> dict:
        return await self.get_json(
            "arena/history",
            {"kind": kind, "user": user, "account": account},
        )

    async def arena_ranking(
        self,
        kind: str = "jjc",
        page: int = 1,
        limit: int = 20,
        user: str | None = None,
        account: str | None = None,
    ) -> dict:
        return await self.get_json(
            "arena/ranking",
            {
                "kind": kind,
                "page": page,
                "limit": limit,
                "user": user,
                "account": account,
            },
        )

    async def clan_status(self, user: str | None = None, account: str | None = None) -> dict:
        return await self.get_json("clan/status", {"user": user, "account": account})

    async def clan_mylog(self, user: str | None = None, account: str | None = None) -> dict:
        return await self.get_json("clan/mylog", {"user": user, "account": account})

    async def upsert_account(
        self,
        user: str,
        account_data: dict,
        account: str = "main",
    ) -> dict:
        payload = {
            "user": str(user or ""),
            "account": account,
            "kind": account_data.get("kind"),
            "uid": account_data.get("uid"),
            "secret": account_data.get("secret"),
        }
        return await self.post_json("account/upsert", payload)
