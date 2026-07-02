import asyncio
import base64
import json
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    from .pcr_chara import id_from_unit_id, name_for_id, unit_id_from_id
except ImportError:
    from pcr_chara import id_from_unit_id, name_for_id, unit_id_from_id


PCRDFANS_SEARCH_URL = "https://api.pcrdfans.com/x/v1/search"
SOLUTION_ALIASES = (
    "\u600e\u4e48\u62c6",
    "\u600e\u4e48\u89e3",
    "\u600e\u4e48\u6253",
    "\u5982\u4f55\u62c6",
    "\u5982\u4f55\u89e3",
    "\u5982\u4f55\u6253",
    "jjc\u67e5\u8be2",
    "arena-query",
)
REGION_PREFIXES = {
    "": 1,
    "b": 2,
    "B": 2,
    "\u53f0": 3,
    "\u81fa": 3,
    "\u65e5": 4,
}


class PcrdFansError(RuntimeError):
    pass


class PcrdFansMissingKey(PcrdFansError):
    def __str__(self) -> str:
        return "\u672a\u914d\u7f6e pcrdfans_api_key\uff0c\u8bf7\u5148\u5728\u63d2\u4ef6\u914d\u7f6e\u91cc\u586b\u5165 pcrdfans Bot API Key\u3002"


@dataclass
class ArenaSolutionResult:
    defender_ids: list[int]
    entries: list[dict]
    region: int

    def format_text(self) -> str:
        return format_arena_solution_text(self.defender_ids, self.entries, self.region)


def parse_solution_command(text: str) -> tuple[int, str] | None:
    raw = str(text or "").strip()
    for prefix, region in REGION_PREFIXES.items():
        for alias in SOLUTION_ALIASES:
            command = prefix + alias
            if raw == command:
                return region, ""
            if raw.startswith(command):
                tail = raw[len(command):].strip()
                if tail == "" or raw[len(command):len(command) + 1].isspace():
                    return region, tail
    return None


def build_solution_payload(defender_ids: list[int], region: int = 1, now: int | None = None) -> dict:
    return {
        "_sign": "a",
        "def": [unit_id_from_id(chara_id) for chara_id in defender_ids],
        "nonce": "a",
        "page": 1,
        "sort": 1,
        "ts": int(time.time() if now is None else now),
        "region": int(region or 1),
    }


class PcrdFansClient:
    def __init__(
        self,
        api_key: str = "",
        search_url: str = PCRDFANS_SEARCH_URL,
        timeout_seconds: int = 15,
    ):
        self.api_key = str(api_key or "").strip()
        self.search_url = search_url
        self.timeout_seconds = int(timeout_seconds)

    async def query(self, defender_ids: list[int], user_id: str, region: int = 1) -> ArenaSolutionResult:
        if not self.api_key:
            raise PcrdFansMissingKey()
        payload = build_solution_payload(defender_ids, region=region)
        data = await asyncio.to_thread(self._post_search, payload)
        entries = _normalize_entries(data.get("data", {}).get("result") or [], str(user_id or ""))
        return ArenaSolutionResult(defender_ids=list(defender_ids), entries=entries, region=region)

    def _post_search(self, payload: dict) -> dict:
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            self.search_url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/78.0 Safari/537.36"
                ),
                "authorization": self.api_key,
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                text = response.read().decode("utf-8")
        except HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")
            raise PcrdFansError(_message_from_json(text) or f"pcrdfans HTTP {exc.code}") from exc
        except (URLError, TimeoutError) as exc:
            raise PcrdFansError(str(getattr(exc, "reason", exc))) from exc

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PcrdFansError("pcrdfans 返回了无效 JSON") from exc
        if not isinstance(data, dict):
            raise PcrdFansError("pcrdfans 返回格式异常")
        if data.get("code"):
            raise PcrdFansError(data.get("message") or f"pcrdfans 错误码 {data.get('code')}")
        return data


def format_arena_solution_text(defender_ids: list[int], entries: list[dict], region: int = 1) -> str:
    defender_names = " ".join(name_for_id(chara_id) for chara_id in defender_ids)
    lines = [
        f"\u9632\u5b88\u65b9 [{defender_names}]",
    ]
    if not entries:
        lines.extend([
            "\u62b1\u6b49\u6ca1\u6709\u67e5\u8be2\u5230\u89e3\u6cd5",
            "\u203b\u6ca1\u6709\u4f5c\u4e1a\u8bf4\u660e\u53ef\u4ee5\u81ea\u7531\u53d1\u6325\uff0c\u4f5c\u4e1a\u4e0a\u4f20\u8bf7\u524d\u5f80 pcrdfans.com",
        ])
        return "\n".join(lines)

    lines.append("\u5df2\u67e5\u8be2\u5230\u4ee5\u4e0a\u8fdb\u653b\u65b9\u6848\uff1a")
    for index, entry in enumerate(entries[:6], start=1):
        attack_names = _format_attack_names(entry.get("atk") or [])
        qkey = str(entry.get("qkey") or "-")
        up = int(entry.get("up") or 0) + int(entry.get("my_up") or 0)
        down = int(entry.get("down") or 0) + int(entry.get("my_down") or 0)
        lines.append(f"{index}. {attack_names}")
        lines.append(f"   {qkey} {up}/{down}")
    lines.append("\u203b\u53d1\u9001\u201c\u70b9\u8d5e/\u70b9\u8e29 + \u4f5c\u4e1aid\u201d\u53ef\u8bb0\u5f55\u672c\u5730\u8bc4\u4ef7")
    if int(region or 1) == 1:
        lines.append('\u203b\u4f7f\u7528 "b\u600e\u4e48\u62c6" \u6216 "\u53f0\u600e\u4e48\u62c6" \u53ef\u6309\u670d\u8fc7\u6ee4')
    lines.append("Support by pcrdfans.com")
    return "\n".join(lines)


def _normalize_entries(entries: list[dict], user_id: str) -> list[dict]:
    hashed_user = hash(user_id)
    normalized: list[dict] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        normalized_entry = dict(entry)
        true_id = str(entry.get("id") or "")
        normalized_entry["qkey"] = _quick_key(true_id, hashed_user) if true_id else ""
        normalized.append(normalized_entry)
    return normalized


def _quick_key(true_id: str, user_id: int) -> str:
    qkey = int(true_id[-6:], 16)
    mask = user_id & 0xFFFFFF
    qkey ^= mask
    return base64.b32encode(qkey.to_bytes(3, "little")).decode("ascii")[:5]


def _format_attack_names(attack: list[dict]) -> str:
    names: list[str] = []
    for chara in attack:
        unit_id = chara.get("id") if isinstance(chara, dict) else chara
        try:
            names.append(name_for_id(id_from_unit_id(int(unit_id))))
        except (TypeError, ValueError):
            names.append("?")
    return " ".join(names)


def _message_from_json(text: str) -> str:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(data, dict):
        return str(data.get("message") or data.get("error") or text)
    return text
