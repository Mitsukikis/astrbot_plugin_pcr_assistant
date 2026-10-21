"""Offline archive and selection of observed, already completed clan attacks.

Call merge_clan_history on each fresh clan_status response and persist the
mutated group state. Only observed_damage_history and observed_history_meta
are persisted here. Rankings, bosses, accounts and rosters remain live.
Pass the returned snapshot to select_clan_report; do not replace it with mylog.
Neither function asserts that polling has captured an entire battle.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import math
import re
import time


MAX_HISTORY_RECORDS = 5000
# CN game days use UTC+8; this also works on Windows without a tzdata package.
CN_TIMEZONE = timezone(timedelta(hours=8), name="Asia/Shanghai")
REPORT_COMMANDS = frozenset({
    "current_report", "my_report", "today_report", "yesterday_report",
    "today_damage", "yesterday_damage", "damage_detail",
})
MEMBER_KEYS = ("members", "clan_members", "member_list", "clan_member_list")


def game_day_bounds(now: int | None = None) -> tuple[int, int]:
    """Return the current CN 05:00 game day's half-open Unix-second bounds."""
    current = datetime.fromtimestamp(_now(now), CN_TIMEZONE)
    start = current.replace(hour=5, minute=0, second=0, microsecond=0)
    if current < start:
        start -= timedelta(days=1)
    return int(start.timestamp()), int((start + timedelta(days=1)).timestamp())


def merge_clan_history(
    clan_state: dict, real_status: dict, *, now: int | None = None,
) -> dict:
    """Merge a bounded history copy, deduplicated by clan/battle/history_id.

    Missing context is never joined to an old archive. ID-less rows may be
    shown from the current response, but are not accumulated between polls.
    Metadata observed_from means first observation, not the first attack time.
    """
    if not isinstance(clan_state, dict) or not isinstance(real_status, dict):
        raise TypeError("clan_state and real_status must be dictionaries")
    status = deepcopy(real_status)
    timestamp = _now(now)
    context = _context(status)
    rows, excluded = _snapshot_history(status)
    meta = clan_state.get("observed_history_meta")
    meta = meta if isinstance(meta, dict) else {}
    usable = all(context) and status.get("ok") is not False

    if not usable:
        # Keep any previous identified archive intact, but never display it as
        # if it belonged to an unidentified or failed live response.
        if status.get("ok") is False:
            rows = []
        truncated = len(rows) > MAX_HISTORY_RECORDS
        status["damage_history"] = _bounded(rows)
        _set_coverage(status, timestamp, truncated)
        status["history_scope"] += " 缺少可确认的公会/会战上下文或响应失败，仅展示本次返回，未累积归档。"
    else:
        same_context = (
            _identifier(meta.get("clan_id")), _identifier(meta.get("battle_id"))
        ) == context
        cached = clan_state.get("observed_damage_history") if same_context else []
        by_id = {}
        for row in cached if isinstance(cached, list) else []:
            if isinstance(row, dict) and _matches_context(row, context):
                identifier = _identifier(row.get("history_id"))
                if identifier:
                    by_id[identifier] = deepcopy(row)
        transient = []
        for row in rows:
            identifier = _identifier(row.get("history_id"))
            if not identifier:
                transient.append(row)
                continue
            previous = by_id.get(identifier, {})
            # Null optional fields in a later page must not erase known times
            # or scores. Explicit zero/False corrections still take effect.
            previous.update({key: value for key, value in row.items()
                             if value is not None or key not in previous})
            by_id[identifier] = previous
        truncated = (same_context and meta.get("history_truncated") is True)
        truncated = bool(truncated or len(by_id) + len(transient) > MAX_HISTORY_RECORDS)
        archived = _bounded(list(by_id.values()))
        observed_from = meta.get("observed_from") if same_context else None
        if not isinstance(observed_from, int) or isinstance(observed_from, bool):
            observed_from = timestamp
        clan_state["observed_damage_history"] = deepcopy(archived)
        clan_state["observed_history_meta"] = {
            "clan_id": context[0], "battle_id": context[1],
            "observed_from": observed_from, "last_observed_at": timestamp,
            "history_truncated": truncated,
        }
        status["damage_history"] = _bounded(archived + transient)
        _set_coverage(status, observed_from, truncated)
        if transient:
            status["history_scope"] += f" {len(transient)}条本次记录缺少有效history_id，未累积归档。"

    if excluded:
        status["history_scope"] += f" 已排除{excluded}条其他公会或会战的记录。"
    notes = status.get("presentation_notes")
    status["presentation_notes"] = list(notes) if isinstance(notes, list) else []
    status["presentation_notes"].append(status["history_scope"])
    return status


def select_clan_report(
    real_status: dict, command_key: str, payload: str = "", *, now: int | None = None,
) -> dict:
    """Select observed history, never realtime rankings or today's mylog.

    Payload is an exact game name, optionally prefixed/suffixed with a spaced
    今日/昨日 modifier. my_report and day *_report default to account.uid;
    *_damage and current_report default to the whole group. damage_detail
    requires a real history_id (optionally prefixed with '#'), not a row index.
    Unknown/ambiguous names and unavailable IDs raise ValueError.
    """
    if command_key not in REPORT_COMMANDS:
        raise ValueError(f"不支持的战报命令：{command_key}")
    if not isinstance(real_status, dict):
        raise TypeError("real_status must be a dictionary")
    status = deepcopy(real_status)
    history, excluded = _snapshot_history(status)
    text = " ".join(str(payload or "").split())
    target = None
    day = None
    label = "全群已归档记录"
    unknown_time = 0
    start = end = None

    if command_key == "damage_detail":
        identifier = _identifier(text.removeprefix("#"))
        if not identifier:
            raise ValueError("请提供真实出刀记录的history_id。")
        history = [row for row in history if _identifier(row.get("history_id")) == identifier]
        if not history:
            raise ValueError(f"本地已观察记录中不存在history_id={identifier}的出刀。")
        status["report_history_id"] = identifier
        target = _viewer_id(history[0])
        if target:
            _filter_roster(status, target)
        label = f"出刀记录history_id={identifier}"
    else:
        day = 0 if command_key.startswith("today_") else -1 if command_key.startswith("yesterday_") else None
        text, modifier = _report_payload(text)
        if modifier is not None:
            if day is not None and day != modifier:
                raise ValueError("日期参数与战报命令冲突。")
            day = modifier
        if text:
            target = _resolve_name(status, history, text)
            label = f"游戏名：{text}（viewer_id={target}）"
        elif command_key in {"my_report", "today_report", "yesterday_report"}:
            account = status.get("account")
            account = account if isinstance(account, dict) else {}
            target = _identifier(account.get("uid")) or _viewer_id(account)
            if not target:
                raise ValueError("未返回本人的account.uid，无法确定个人战报。")
            label = f"本人（viewer_id={target}）"
        if target:
            history = [row for row in history if _viewer_id(row) == target]
            _filter_roster(status, target)
        if day is not None:
            start, end = game_day_bounds(now)
            start += day * 86400
            end += day * 86400
            selected = []
            for row in history:
                timestamp = _event_time(row)
                if timestamp is None:
                    unknown_time += 1
                elif start <= timestamp < end:
                    selected.append(row)
            history = selected
            label += f"；游戏日 {_date_text(start)} 至 {_date_text(end)}（Asia/Shanghai，05:00换日）"

    status["damage_history"] = history
    status["history_complete"] = False
    status["damage_history_complete"] = False
    status["history_truncated"] = status.get("history_truncated") is True
    status.setdefault("observed_from", None)
    status["report_command"] = command_key
    status["report_viewer_id"] = target
    status["report_day_start"], status["report_day_end"] = start, end
    status["history_unknown_time_count"] = unknown_time
    coverage = status.get("history_scope") or "仅当前接口已返回的出刀记录；历史覆盖不完整，不代表整期。"
    status["history_scope"] = f"{coverage} 筛选范围：{label}，共{len(history)}条。"
    notes = status.get("presentation_notes")
    status["presentation_notes"] = list(notes) if isinstance(notes, list) else []
    status["presentation_notes"].append(status["history_scope"])
    if unknown_time:
        status["presentation_notes"].append(f"{unknown_time}条记录缺少可识别时间，未归入该游戏日。")
        status["history_scope"] += f" {unknown_time}条记录时间未知，未计入。"
    if excluded:
        status["presentation_notes"].append(f"已排除{excluded}条其他公会或会战的记录。")
    return status


def _now(value):
    return int(time.time()) if value is None else int(value)


def _identifier(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    text = str(value).strip()
    if text.isascii() and text.isdigit() and int(text) > 0:
        return str(int(text))
    return None


def _context(status):
    clan = status.get("clan")
    battle = status.get("clan_battle")
    clan = clan if isinstance(clan, dict) else {}
    battle = battle if isinstance(battle, dict) else {}
    return (
        _identifier(clan.get("clan_id")) or _identifier(status.get("clan_id")),
        _identifier(battle.get("id")) or _identifier(status.get("clan_battle_id")) or _identifier(status.get("battle_id")),
    )


def _matches_context(row, context):
    for key, expected in (("clan_id", context[0]), ("clan_battle_id", context[1]), ("battle_id", context[1])):
        if row.get(key) is not None and expected is not None and _identifier(row[key]) != expected:
            return False
    return True


def _snapshot_history(status):
    rows = status.get("damage_history")
    by_id, idless, excluded = {}, [], 0
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not row:
            continue
        if not _matches_context(row, _context(status)):
            excluded += 1
            continue
        identifier = _identifier(row.get("history_id"))
        if identifier:
            previous = by_id.setdefault(identifier, {})
            previous.update({key: value for key, value in row.items()
                             if value is not None or key not in previous})
        else:
            idless.append(deepcopy(row))
    return list(by_id.values()) + idless, excluded


def _bounded(rows):
    return sorted(rows, key=lambda row: int(_identifier(row.get("history_id")) or 0), reverse=True)[:MAX_HISTORY_RECORDS]


def _set_coverage(status, observed_from, truncated):
    history = status["damage_history"]
    times = [timestamp for row in history if (timestamp := _event_time(row)) is not None]
    unknown = len(history) - len(times)
    status["observed_from"] = observed_from
    status["history_truncated"] = bool(truncated)
    status["history_complete"] = False
    status["damage_history_complete"] = False
    status["history_scope"] = (
        f"本地自{_date_text(observed_from)}（Asia/Shanghai）起观察，共保留{len(history)}条已发生出刀；"
        "仅为已观察记录，不保证连续覆盖，不代表整期完整历史。"
    )
    if times:
        status["history_scope"] += f" 已知记录时间：{_date_text(min(times))} 至 {_date_text(max(times))}。"
    if unknown:
        status["history_scope"] += f" {unknown}条记录时间未知。"
    if truncated:
        status["history_scope"] += f" 历史已截断，最多保留{MAX_HISTORY_RECORDS}条。"


def _date_text(timestamp):
    return datetime.fromtimestamp(timestamp, CN_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")


def _event_time(row):
    # finish_time is remaining battle seconds, not an event timestamp.
    for key in ("create_time", "battle_end_time", "end_time", "battle_time", "timestamp"):
        value = row.get(key)
        if value is None or isinstance(value, bool):
            continue
        try:
            number = float(value)
            if number > 100_000_000_000:
                number /= 1000
            if math.isfinite(number) and 946_684_800 <= number < 253_402_214_400:
                return int(number)
        except (ValueError, TypeError, OverflowError):
            pass
        if isinstance(value, str) and re.search(r"[T ]\d{2}:\d{2}", value):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return int((parsed if parsed.tzinfo else parsed.replace(tzinfo=CN_TIMEZONE)).timestamp())
            except (ValueError, OverflowError, OSError):
                pass
    return None


def _viewer_id(row):
    return _identifier(row.get("viewer_id")) or _identifier(row.get("player_viewer_id")) if isinstance(row, dict) else None


def _name(row):
    if isinstance(row, dict):
        for key in ("name", "user_name", "viewer_name", "nickname"):
            if row.get(key):
                return " ".join(str(row[key]).split())
    return ""


def _members(status):
    result = []
    for source in (status, status.get("clan")):
        if isinstance(source, dict):
            for key in MEMBER_KEYS:
                if isinstance(source.get(key), list):
                    result.extend(source[key])
    return result


def _resolve_name(status, history, name):
    members = _members(status)
    candidates = {_viewer_id(row) for row in members if _name(row) == name and _viewer_id(row)}
    if not candidates:
        # Allow departed members, but do not revive an obsolete name for a
        # viewer whose current roster entry has a different name.
        named_ids = {_viewer_id(row) for row in members if _viewer_id(row) and _name(row)}
        candidates = {_viewer_id(row) for row in history
                      if _name(row) == name and _viewer_id(row) and _viewer_id(row) not in named_ids}
    if not candidates:
        raise ValueError(f"不存在游戏名为“{name}”的可确认成员或出刀记录。")
    if len(candidates) != 1:
        raise ValueError(f"游戏名“{name}”重名，无法唯一确定viewer_id。")
    return candidates.pop()


def _filter_roster(status, target):
    for source in (status, status.get("clan")):
        if isinstance(source, dict):
            for key in MEMBER_KEYS:
                if isinstance(source.get(key), list):
                    source[key] = [row for row in source[key] if _viewer_id(row) == target]


def _report_payload(text):
    modifiers = {"今日": 0, "今天": 0, "昨日": -1, "昨天": -1}
    parts = text.split(" ") if text else []
    day = None
    if parts and parts[0] in modifiers:
        day = modifiers[parts.pop(0)]
    if parts and parts[-1] in modifiers:
        other = modifiers[parts.pop()]
        if day is not None and day != other:
            raise ValueError("不能同时筛选今日与昨日。")
        day = other
    return " ".join(parts), day
