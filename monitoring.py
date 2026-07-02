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
    messages = _boss_active_messages(clan_state, real_status)
    history = [
        item for item in (real_status.get("damage_history") or [])
        if isinstance(item, dict) and item.get("history_id") is not None
    ]
    if not history:
        return messages

    latest_id = max(int(item["history_id"]) for item in history)
    last_seen = int(clan_state.get("last_damage_history_id") or 0)
    clan_state["last_damage_history_id"] = latest_id
    if last_seen <= 0:
        return messages

    new_items = [
        item for item in history
        if int(item["history_id"]) > last_seen
    ]
    new_items.sort(key=lambda item: int(item.get("history_id") or 0))
    messages.extend(_format_clan_damage_message(item) for item in new_items)
    return messages


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
        current[order] = count
        old_count = int(previous.get(order) or 0)
        if count > 0 and count != old_count:
            messages.append(f"{order}\u738b\u5f53\u524d\u6709{count}\u4eba\u51fa\u5200")
    clan_state["boss_active_counts"] = current
    return messages


def _boss_order(item):
    for key in ("order_num", "boss_order", "enemy_order", "boss_number"):
        value = item.get(key)
        if value:
            return str(value)
    enemy_id = str(item.get("enemy_id") or "")
    if enemy_id and enemy_id[-1:].isdigit():
        return enemy_id[-1:]
    return ""


def _active_battle_count(item):
    for key in ("attacking_count", "challenge_count", "battle_count"):
        value = item.get(key)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
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
    return 0


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
    name = item.get("name") or item.get("viewer_id") or "-"
    lap = item.get("lap_num", "-")
    order = item.get("order_num", "-")
    damage = _format_number(item.get("damage"))
    kill = " \u51fb\u7834" if item.get("kill") else ""
    return f"{name}\n\u51fa\u5200: {lap}-{order} {damage}{kill}"


def _format_number(value):
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "-"
