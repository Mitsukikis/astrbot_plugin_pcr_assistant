try:
    from .clan_report import _damage_history, _member_name, _members, _number, _same_period, _viewer_id
except ImportError:
    from clan_report import _damage_history, _member_name, _members, _number, _same_period, _viewer_id


def update_arena_entry_from_result(entry, result, pause_on_login=True):
    settings = str(entry.get("settings") or "1100")
    nickname = result.nickname or entry.get("nickname") or entry.get("uid") or ""
    messages = []

    login_changed = _login_time_changed(
        entry.get("last_login_time"),
        result.last_login_time,
    )
    if pause_on_login and login_changed:
        entry["last_jjc_rank"] = result.jjc_rank
        entry["last_pjjc_rank"] = result.pjjc_rank
        entry["last_login_time"] = result.last_login_time
        entry["push_target"] = None
        entry["manual_pause"] = True
        entry["pause_reason"] = "game_login_detected"
        if result.platform:
            entry["platform"] = result.platform
        return [_login_pause_message(nickname)]

    if settings[0] == "1":
        messages.extend(_rank_messages(nickname, "jjc", entry.get("last_jjc_rank"), result.jjc_rank))
    if settings[1] == "1":
        messages.extend(_rank_messages(nickname, "pjjc", entry.get("last_pjjc_rank"), result.pjjc_rank))
    if settings[3] != "0":
        messages.extend(_online_messages(nickname, entry.get("last_login_time"), result.last_login_time))

    entry["last_jjc_rank"] = result.jjc_rank
    entry["last_pjjc_rank"] = result.pjjc_rank
    entry["last_login_time"] = result.last_login_time
    if result.platform:
        entry["platform"] = result.platform
    return messages


def _login_time_changed(old_time, new_time):
    if old_time is None or new_time is None:
        return False
    try:
        return int(old_time) != int(new_time)
    except (TypeError, ValueError):
        return str(old_time) != str(new_time)


def _login_pause_message(nickname):
    return (
        f"{nickname}\u4e0a\u7ebf\u4e86\uff0c"
        "\u5df2\u81ea\u52a8\u6682\u505c\u7ade\u6280\u573a/\u4f1a\u6218\u540e\u53f0\u76d1\u63a7\u3002"
        "\u4e0b\u53f7\u540e\u91cd\u65b0\u53d1\u9001\u7ade\u6280\u573a\u76d1\u63a7\u6216\u51fa\u5200\u76d1\u63a7\u6062\u590d\u3002"
    )


def update_clan_damage_state(clan_state, real_status):
    if not isinstance(real_status, dict):
        return []
    scope = _damage_scope(real_status)
    old_scope = clan_state.get("damage_history_scope")
    old_scope = old_scope if isinstance(old_scope, dict) else {}
    changed = any(key in old_scope and old_scope[key] != value for key, value in scope.items())
    if changed:
        clan_state["last_damage_history_id"] = 0
        clan_state["damage_history_initialized"] = False
        clan_state["boss_active_counts"] = {}
    clan_state["damage_history_scope"] = scope if changed else {**old_scope, **scope}
    messages = _boss_active_messages(clan_state, real_status)
    if not isinstance(real_status.get("damage_history"), list):
        return messages
    battle = real_status.get("clan_battle")
    battle = battle if isinstance(battle, dict) else {}
    history = [
        item for item in _damage_history(real_status)
        if _number(item.get("history_id")) is not None
        and _number(item["history_id"]) >= 0 and _same_period(item, battle)
    ]
    latest_id = max((_number(item["history_id"]) for item in history), default=0)
    last_seen = _number(clan_state.get("last_damage_history_id"))
    initialized = clan_state.get("damage_history_initialized", last_seen is not None and last_seen > 0)
    # A legacy cursor without battle identity cannot establish the current scope.
    if scope and not old_scope:
        initialized = False
    # Empty pages do not lower an established cursor. A new period still gets a
    # fresh baseline, even if its first response contains no damage records.
    if not history and initialized:
        return messages
    reset = last_seen is not None and latest_id < last_seen and bool(history)
    clan_state["last_damage_history_id"] = latest_id
    clan_state["damage_history_initialized"] = True
    if not initialized or reset:
        return messages
    new_items = [
        item for item in history
        if _number(item["history_id"]) > (last_seen if last_seen is not None else -1)
    ]
    new_items.sort(key=lambda item: _number(item["history_id"]))
    names = {_viewer_id(member): _member_name(member) for member in _members(real_status)
             if _viewer_id(member) and _member_name(member)}
    for item in new_items:
        if _viewer_id(item) in names:
            item = {**item, "name": names[_viewer_id(item)]}
        messages.append(_format_clan_damage_message(item))
    return messages


def _damage_scope(real_status):
    battle = real_status.get("clan_battle")
    battle = battle if isinstance(battle, dict) else {}
    clan = real_status.get("clan")
    clan = clan if isinstance(clan, dict) else {}
    values = {
        "clan_id": clan.get("clan_id"),
        "clan_battle_id": battle.get("id", real_status.get("clan_battle_id")),
        "period": battle.get("period", real_status.get("period")),
        "period_id": battle.get("period_id", real_status.get("period_id")),
    }
    return {key: str(value) for key, value in values.items() if value is not None}


def _boss_active_messages(clan_state, real_status):
    if not isinstance(real_status, dict):
        return []
    boss_info = real_status.get("boss_info") or []
    if not isinstance(boss_info, list):
        return []

    previous = clan_state.get("boss_active_counts")
    if not isinstance(previous, dict):
        previous = {}
    current = {}
    messages = []
    for item in boss_info:
        if not isinstance(item, dict):
            continue
        order = _boss_order(item)
        if not order:
            continue
        count = _active_battle_count(item)
        if count is None:
            if order in previous:
                current[order] = previous[order]
            continue
        current[order] = count
        old_count = _number(previous.get(order)) or 0
        if count > 0 and count != old_count:
            messages.append(f"{order}\u738b\u5f53\u524d\u6709{count}\u4eba\u51fa\u5200")
    clan_state["boss_active_counts"] = {**previous, **current}
    return messages


def _boss_order(item):
    for key in ("order_num", "boss_order", "enemy_order", "boss_number"):
        value = item.get(key)
        number = _number(value)
        if number is not None and 1 <= number <= 5:
            return str(number)
    enemy_id = str(item.get("enemy_id") or "")
    if enemy_id and enemy_id[-1:] in "12345":
        return enemy_id[-1:]
    return ""


def _active_battle_count(item):
    for key in ("attacking_count", "fighter_num"):
        value = item.get(key)
        if value is not None:
            count = _number(value)
            if count is not None and count >= 0:
                return count
    for key in (
        "attacking_user_list",
        "attack_user_list",
        "battle_user_list",
        "battle_member",
        "challenging_member_list",
        "challenge_member_list",
    ):
        value = item.get(key)
        if isinstance(value, list):
            return len(value)
    return None


def _rank_messages(nickname, kind, old_rank, new_rank):
    if old_rank is None or new_rank is None or int(old_rank) == int(new_rank):
        return []
    old_value = int(old_rank)
    new_value = int(new_rank)
    marker = "\u25b2" if new_value < old_value else "\u25bd"
    delta = abs(old_value - new_value)
    return [f"{nickname}\n{kind}: {old_value}->{new_value} [{marker}{delta}]"]


def _online_messages(nickname, old_time, new_time):
    if old_time is None or new_time is None or int(old_time) == int(new_time):
        return []
    return [f"{nickname}\u4e0a\u7ebf\u4e86\uff01"]


def _format_clan_damage_message(item):
    name = _member_name(item) or _viewer_id(item) or "\u672a\u77e5\u73a9\u5bb6"
    lap = item.get("lap_num") if item.get("lap_num") is not None else "\u672a\u77e5"
    order = _boss_order(item) or "\u672a\u77e5"
    damage = _number(item.get("damage"))
    damage = str(damage) if damage is not None and damage >= 0 else "\u672a\u77e5"
    return f"{name}\u5bf9{lap}\u5468\u76ee{order}\u738b\u9020\u6210\u4e86{damage}\u70b9\u4f24\u5bb3\u3002"


def _format_number(value):
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "-"
