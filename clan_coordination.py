"""Per-group, QQ-keyed local coordination; never performs game operations.

Persist clan_state after handling a supported command. Data lives exclusively
under clan_coordination. is_admin is supplied by the trusted chat adapter for
group owners/admins; an explicitly configured clan_state['owner_qq'] also owns
clear operations. Player names are display labels, never identity or a roster.

Boss payloads: '1' through '5', optionally '1王' or 'boss 1', then a spaced note.
Cancellation/table/clear commands accept an optional boss; empty means all
own entries, all displayed entries, or all entries (admin clear), respectively.
SL/record_sl accept no payload or a boss plus note; sl_status has no arguments.
permission only reports permissions and cannot grant them.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import re
import time

try:
    from .clan_history import CN_TIMEZONE, game_day_bounds
except ImportError:
    from clan_history import CN_TIMEZONE, game_day_bounds


COORDINATION_COMMANDS = frozenset({
    "reserve", "reservation_table", "cancel_reservation", "clear_reservation",
    "hang_tree", "check_tree", "leave_tree", "record_sl", "sl", "sl_status",
    "apply_damage", "cancel_apply", "clear_apply", "application_table", "permission",
})
LOCAL_NOTICE = "仅为本群本地登记，不会执行游戏内操作。"


def handle_clan_coordination(
    command_key: str, payload: str, clan_state: dict, sender_id,
    player_name: str = "", is_admin: bool = False, *, now: int | None = None,
) -> str | None:
    """Return Chinese text, or None for a command outside this module.

    Invalid input/permissions return explanatory text without modifying state.
    Normal cancellation always acts on the sender, even for administrators.
    Use a separate clan_state dictionary for each group and persist it yourself.
    """
    if command_key not in COORDINATION_COMMANDS:
        return None
    if not isinstance(clan_state, dict):
        raise TypeError("clan_state must be a dictionary")
    qq = _qq(sender_id)
    if not qq:
        return "无法确认发送者QQ，未更改本地登记。"
    admin = is_admin is True or qq == _qq(clan_state.get("owner_qq"))
    text = " ".join(str(payload or "").split())
    if command_key == "permission":
        role = "群主或管理员" if admin else "普通成员"
        return (
            f"你的本地管理权限：{role}（QQ：{qq}）。\n"
            "成员可登记和撤销自己的预约、挂树、SL及出刀申请；群主或管理员可清空预约和申请。\n"
            "权限由群身份或预先配置的群主QQ确定，不能通过此命令授予。\n" + LOCAL_NOTICE
        )
    if command_key in {"clear_reservation", "clear_apply"} and not admin:
        return "只有群主或管理员可以清空本群登记；你可以取消自己的登记。"

    timestamp = int(time.time()) if now is None else int(now)
    original = clan_state.get("clan_coordination")
    data = deepcopy(original) if isinstance(original, dict) else {}
    for key in ("reservations", "trees", "applications", "sl_records"):
        if not isinstance(data.get(key), dict):
            data[key] = {}
    try:
        result = _handle(command_key, text, data, qq, _clean(player_name), timestamp)
    except ValueError as exc:
        return str(exc)
    if data != original:
        clan_state["clan_coordination"] = data
    return result + "\n" + LOCAL_NOTICE


def _handle(command, payload, data, qq, name, now):
    if command in {"record_sl", "sl", "sl_status"}:
        return _handle_sl(command, payload, data, qq, name, now)
    required = command in {"reserve", "hang_tree", "apply_damage"}
    allow_note = required
    boss, note = _boss_payload(payload, required=required, allow_note=allow_note)

    if command == "reserve":
        entries = data["reservations"].setdefault(str(boss), {})
        previous = entries.get(qq)
        entries[qq] = _entry(qq, name, boss, note, now, previous)
        verb = "已更新" if previous else "已登记"
        return f"{verb}{_person(entries[qq])}对{boss}王的预约。"
    if command in {"reservation_table", "check_tree", "application_table"}:
        is_tree = command == "check_tree"
        is_apply = command == "application_table"
        title = "本群挂树" if is_tree else "本群出刀申请" if is_apply else "本群预约表"
        lines = [title + "："]
        for order in [boss] if boss else range(1, 6):
            entries = (
                [entry for entry in data["trees" if is_tree else "applications"].values() if entry["boss"] == order]
                if is_tree or is_apply else list(data["reservations"].get(str(order), {}).values())
            )
            lines.append(f"{order}王：" + ("；".join(_describe(entry) for entry in _ordered(entries)) or "暂无登记"))
        return "\n".join(lines)
    if command in {"cancel_reservation", "clear_reservation"}:
        count = 0
        for order in [boss] if boss else range(1, 6):
            entries = data["reservations"].get(str(order), {})
            if command == "clear_reservation":
                count += len(entries)
                entries.clear()
            elif qq in entries:
                del entries[qq]
                count += 1
            if not entries:
                data["reservations"].pop(str(order), None)
        return f"已清空{count}条预约登记。" if command == "clear_reservation" else f"已取消你自己的{count}条预约。"
    if command == "hang_tree":
        previous = data["trees"].get(qq)
        data["trees"][qq] = _entry(qq, name, boss, note, now, previous)
        return f"已登记{_person(data['trees'][qq])}挂在{boss}王。"
    if command == "apply_damage":
        previous = data["applications"].get(qq)
        data["applications"][qq] = _entry(qq, name, boss, note, now, previous)
        queue = _ordered([entry for entry in data["applications"].values() if entry["boss"] == boss])
        position = next(index for index, entry in enumerate(queue, 1) if entry["qq"] == qq)
        lines = [f"已登记你对{boss}王的出刀申请，本地队列第{position}位；不代表游戏内已进刀或获准进刀。"]
        lines.extend(f"{index}. {_describe(entry)}" for index, entry in enumerate(queue, 1))
        return "\n".join(lines)
    if command == "clear_apply":
        keys = [key for key, entry in data["applications"].items() if boss is None or entry["boss"] == boss]
        for key in keys:
            del data["applications"][key]
        return f"已清空{len(keys)}条本地出刀申请。"
    key = "trees" if command == "leave_tree" else "applications"
    entry = data[key].get(qq)
    noun = "挂树" if command == "leave_tree" else "出刀申请"
    if not entry or (boss is not None and entry["boss"] != boss):
        return f"你在该范围没有{noun}登记。"
    del data[key][qq]
    return f"已撤销你对{entry['boss']}王的{noun}登记。"


def _handle_sl(command, payload, data, qq, name, now):
    if command == "sl_status" and payload:
        raise ValueError("查询本群今日SL登记无需参数。")
    boss, note = _boss_payload(payload, required=False, allow_note=True)
    start, end = game_day_bounds(now)
    if data.get("sl_day_start") != start:
        data["sl_day_start"] = start
        data["sl_records"] = {}
    records = data["sl_records"]
    if command != "sl_status":
        if qq in records:
            return "你本游戏日已登记过SL，不会重复记录；下次重置为北京时间05:00。"
        records[qq] = _entry(qq, name, boss, note, now)
        return f"已记录{_person(records[qq])}本游戏日的SL；同一QQ本游戏日只记一次。"
    period = datetime.fromtimestamp(start, CN_TIMEZONE).strftime("%Y-%m-%d 05:00")
    until = datetime.fromtimestamp(end, CN_TIMEZONE).strftime("%Y-%m-%d 05:00")
    lines = [f"本群SL登记（北京时间{period} 至 {until}）："]
    lines.extend(_describe(entry, include_boss=True) for entry in _ordered(records.values()))
    if not records:
        lines.append("暂无登记。")
    lines.append("你本游戏日已登记SL。" if qq in records else "你本游戏日尚未登记SL。")
    return "\n".join(lines)


def _boss_payload(payload, *, required, allow_note):
    if not payload:
        if required:
            raise ValueError("请指定1至5王，例如：1王。")
        return None, ""
    match = re.fullmatch(r"(?:boss\s*)?([1-5])(?:王)?(?:\s+(.+))?", payload, re.IGNORECASE)
    if not match or (match.group(2) and not allow_note):
        raise ValueError("王编号必须为1至5；备注请放在王编号后的空格后。")
    return int(match.group(1)), match.group(2) or ""


def _qq(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    text = str(value).strip()
    return str(int(text)) if text.isascii() and text.isdigit() and int(text) > 0 else None


def _clean(value):
    return " ".join(str(value or "").split())


def _entry(qq, name, boss, note, now, previous=None):
    previous = previous if isinstance(previous, dict) else {}
    return {
        "qq": qq, "player_name": name or previous.get("player_name", ""),
        "boss": boss, "note": note, "updated_at": now,
        "created_at": previous.get("created_at", now) if previous.get("boss") == boss else now,
    }


def _person(entry):
    name, qq = entry.get("player_name"), entry["qq"]
    return f"{name}（QQ：{qq}）" if name else f"QQ：{qq}"


def _describe(entry, include_boss=False):
    text = _person(entry)
    if include_boss and entry.get("boss"):
        text += f"，{entry['boss']}王"
    if entry.get("note"):
        text += f"（{entry['note']}）"
    return text


def _ordered(entries):
    # Stable sorting preserves insertion order for requests in the same second.
    return sorted(entries, key=lambda entry: entry["created_at"])
