from dataclasses import dataclass
from urllib.request import urlopen


@dataclass
class AutoPCRClient:
    base_url: str
    public_login_url: str
    timeout_seconds: int = 5

    @property
    def login_url(self) -> str:
        return self.public_login_url.rstrip("/")

    @property
    def health_url(self) -> str:
        return self.base_url.rstrip("/") + "/login"

    async def health_text(self) -> str:
        try:
            with urlopen(self.health_url, timeout=self.timeout_seconds) as resp:
                if 200 <= resp.status < 400:
                    return "AutoPCR \u672c\u673a\u670d\u52a1\u6b63\u5e38"
                return f"AutoPCR \u8fd4\u56de\u72b6\u6001 {resp.status}"
        except Exception as exc:
            return f"AutoPCR \u672c\u673a\u670d\u52a1\u5f02\u5e38\uff1a{type(exc).__name__}"
