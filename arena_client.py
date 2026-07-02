from dataclasses import dataclass
from datetime import datetime

try:
    from .real_api_client import RealAPIError
    from .arena_ranking import format_arena_ranking
except ImportError:
    from real_api_client import RealAPIError
    from arena_ranking import format_arena_ranking


@dataclass
class ArenaResult:
    uid: str
    nickname: str
    platform: str | None = None
    jjc_rank: int | None = None
    pjjc_rank: int | None = None
    team_level: int | None = None
    last_login_time: int | None = None
    message: str = (
        "\u771f\u5b9e\u6392\u540d/\u5386\u53f2\u540e\u7aef\u5c1a\u672a"
        "\u63a5\u5165\u3002\u5f53\u524d\u4ec5\u663e\u793a\u672c\u5730"
        "\u7ed1\u5b9a\u548c\u8bbe\u7f6e\u3002"
    )


class ArenaClient:
    def __init__(self, real_api=None, default_user: str | None = None):
        self.real_api = real_api
        self.default_user = default_user

    async def query(
        self,
        uid: str,
        nickname: str = "",
        user: str | None = None,
        account: str | None = None,
    ) -> ArenaResult:
        uid_text = str(uid or "").strip()
        display_name = str(nickname or uid_text).strip() or uid_text
        if self.real_api is None:
            return ArenaResult(uid=uid_text, nickname=display_name)

        try:
            payload = await self.real_api.profile(
                uid_text,
                user=user or self.default_user,
                account=account,
            )
        except RealAPIError as exc:
            return ArenaResult(
                uid=uid_text,
                nickname=display_name,
                message=f"\u771f\u5b9e\u7ade\u6280\u573a\u67e5\u8be2\u5931\u8d25\uff1a{exc}",
            )

        profile = payload.get("profile") or {}
        account = payload.get("account") or {}
        result = ArenaResult(
            uid=uid_text,
            nickname=profile.get("user_name") or display_name,
            platform=_platform_from_account(account),
            jjc_rank=_int_or_none(profile.get("arena_rank")),
            pjjc_rank=_int_or_none(profile.get("grand_arena_rank")),
            team_level=_int_or_none(profile.get("team_level")),
            last_login_time=_int_or_none(profile.get("last_login_time")),
        )
        result.message = _format_profile_message(result, profile)
        return result

    async def history(
        self,
        kind: str = "jjc",
        user: str | None = None,
        account: str | None = None,
    ) -> str:
        normalized = "pjjc" if str(kind).lower() in {"pjjc", "grand"} else "jjc"
        title = "\u51fb\u5251\u8bb0\u5f55" if normalized == "pjjc" else "\u7ade\u6280\u573a\u8bb0\u5f55"
        if self.real_api is None:
            return f"{title}\uff1a\n\u771f\u5b9e\u5386\u53f2\u540e\u7aef\u5c1a\u672a\u63a5\u5165\u3002"

        try:
            payload = await self.real_api.arena_history(
                normalized,
                user=user or self.default_user,
                account=account,
            )
        except RealAPIError as exc:
            return f"{title}\uff1a\n\u771f\u5b9e\u5386\u53f2\u67e5\u8be2\u5931\u8d25\uff1a{exc}"

        items = payload.get("items") or []
        if not items:
            return f"{title}\uff1a\n\u6682\u65e0\u8bb0\u5f55"
        lines = [f"{title}\uff1a"]
        for item in items[:10]:
            lines.append(_format_history_item(item, normalized))
        return "\n".join(lines)

    async def ranking_text(
        self,
        kind: str = "jjc",
        page: int = 1,
        user: str | None = None,
        account: str | None = None,
    ) -> str:
        normalized = "pjjc" if str(kind).lower() in {"pjjc", "grand"} else "jjc"
        title = "\u516c\u4e3b\u7ade\u6280\u573a\u6392\u884c\u699c" if normalized == "pjjc" else "\u7ade\u6280\u573a\u6392\u884c\u699c"
        if self.real_api is None:
            return f"{title}\uff1a\n\u771f\u5b9e\u6392\u884c\u699c\u540e\u7aef\u5c1a\u672a\u63a5\u5165\u3002"

        try:
            payload = await self.real_api.arena_ranking(
                normalized,
                page=page,
                user=user or self.default_user,
                account=account,
            )
        except RealAPIError as exc:
            return f"{title}\uff1a\n\u771f\u5b9e\u6392\u884c\u699c\u67e5\u8be2\u5931\u8d25\uff1a{exc}"
        return format_arena_ranking(payload)


def _platform_from_account(account: dict) -> str:
    channel = str(account.get("channel") or "")
    if "\u6e20" in channel or account.get("platform") == "channel":
        return "channel"
    return str(account.get("platform") or "bili")


def _format_profile_message(result: ArenaResult, profile: dict) -> str:
    lines = [
        f"\u7b49\u7ea7\uff1a{_format_empty(result.team_level)}",
        f"JJC\uff1a{_format_empty(result.jjc_rank)}",
        f"PJJC\uff1a{_format_empty(result.pjjc_rank)}",
    ]
    clan_name = profile.get("clan_name")
    if clan_name:
        lines.append(f"\u516c\u4f1a\uff1a{clan_name}")
    if result.last_login_time:
        lines.append(f"\u6700\u540e\u767b\u5f55\uff1a{_format_time(result.last_login_time)}")
    return "\n".join(lines)


def _format_empty(value):
    if value is None or value == "":
        return "-"
    return value


def _format_time(value: int) -> str:
    try:
        return datetime.fromtimestamp(int(value)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return str(value)


def _int_or_none(value):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _format_history_item(item: dict, kind: str) -> str:
    opponent = item.get("opponent_user") or {}
    opponent_name = opponent.get("user_name") or opponent.get("viewer_id") or "-"
    result = "\u80dc" if item.get("win_or_lose") == 1 else "\u8d1f"
    time_text = _format_time(item.get("versus_time")) if item.get("versus_time") else "-"
    if kind == "pjjc" and item.get("win_number") is not None:
        score = f"{item.get('win_number', '-')}-{item.get('lose_number', '-')}"
        return f"{time_text} {result}({score}) vs {opponent_name}"
    return f"{time_text} {result} vs {opponent_name}"
