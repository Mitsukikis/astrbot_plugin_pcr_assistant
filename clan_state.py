try:
    from .storage import mask_value
    from .clan_report import (
        _flag, _member_name, _members, _number, _viewer_id, build_current_report_text,
        build_damage_count_summary, prepare_clan_report,
    )
    from .monitoring import _active_battle_count, _boss_order
except ImportError:
    from storage import mask_value
    from clan_report import (
        _flag, _member_name, _members, _number, _viewer_id, build_current_report_text,
        build_damage_count_summary, prepare_clan_report,
    )
    from monitoring import _active_battle_count, _boss_order


COMMAND_TITLES = {
    "out_damage_monitor_on": "\u51fa\u5200\u76d1\u63a7",
    "out_damage_monitor_off": "\u5173\u95ed\u51fa\u5200\u76d1\u63a7",
    "status": "\u72b6\u6001",
    "urge": "\u50ac\u5200",
    "current_report": "\u5f53\u524d\u6218\u62a5",
    "my_report": "\u6211\u7684\u6218\u62a5",
    "today_report": "\u4eca\u65e5\u6218\u62a5",
    "yesterday_report": "\u6628\u65e5\u6218\u62a5",
    "damage_detail": "\u51fa\u5200\u8be6\u60c5",
    "today_damage": "\u4eca\u65e5\u51fa\u5200",
    "yesterday_damage": "\u6628\u65e5\u51fa\u5200",
    "reservation_table": "\u9884\u7ea6\u8868",
    "reserve": "\u9884\u7ea6",
    "cancel_reservation": "\u53d6\u6d88\u9884\u7ea6",
    "clear_reservation": "\u6e05\u7a7a\u9884\u7ea6",
    "check_tree": "\u67e5\u6811",
    "hang_tree": "\u6302\u6811",
    "leave_tree": "\u4e0b\u6811",
    "sl": "sl",
    "record_sl": "\u8bb0\u5f55sl",
    "sl_status": "sl?",
    "apply_damage": "\u7533\u8bf7\u51fa\u5200",
    "cancel_apply": "\u53d6\u6d88\u7533\u8bf7",
    "clear_apply": "\u6e05\u7a7a\u7533\u8bf7",
    "correct_damage": "\u4fee\u6b63\u51fa\u5200",
    "effective_damage_count": "\u67e5\u770b\u7b49\u6548\u51fa\u5200\u6570",
    "permission": "\u6743\u9650",
    "manual_report_off": "\u5173\u95ed\u624b\u52a8\u62a5\u5200",
    "manual_report_on": "\u5f00\u542f\u624b\u52a8\u62a5\u5200",
    "image_mode_on": "\u5f00\u542f\u56fe\u7247\u6a21\u5f0f",
    "image_mode_off": "\u5173\u95ed\u56fe\u7247\u6a21\u5f0f",
    "tree_display_separate_on": "\u5f00\u542f\u6302\u6811\u5355\u72ec\u663e\u793a",
    "tree_display_separate_off": "\u5173\u95ed\u6302\u6811\u5355\u72ec\u663e\u793a",
    "manual_add_group_record": "\u624b\u52a8\u6dfb\u52a0\u7fa4\u8bb0\u5f55",
}

BACKEND_PENDING = (
    "\u540e\u7aef\u6b63\u5728\u63a5\u5165\uff0c"
    "\u6682\u672a\u8bfb\u53d6\u771f\u5b9e\u6e38\u620f\u51fa\u5200\u8bb0\u5f55\u3002"
)
LOCAL_ONLY = (
    "\u5f53\u524d\u4ec5\u4fdd\u5b58\u672c\u5730\u7fa4\u72b6\u6001\uff0c"
    "\u4e0d\u4f1a\u6267\u884c\u6e38\u620f\u5185\u64cd\u4f5c\u3002"
)


def clan_state_update_for_command(command_key, sender_id=None):
    if command_key == "out_damage_monitor_on":
        return {
            "out_damage_monitor": True,
            "monitor_qq": str(sender_id or ""),
            "manual_pause": False,
            "pause_reason": "",
        }
    if command_key == "out_damage_monitor_off":
        return {
            "out_damage_monitor": False,
            "manual_pause": True,
            "pause_reason": "manual_off",
        }
    if command_key == "manual_report_on":
        return {"manual_report_enabled": True}
    if command_key == "manual_report_off":
        return {"manual_report_enabled": False}
    if command_key == "image_mode_on":
        return {"image_mode_enabled": True}
    if command_key == "image_mode_off":
        return {"image_mode_enabled": False}
    if command_key == "tree_display_separate_on":
        return {"tree_display_separate": True}
    if command_key == "tree_display_separate_off":
        return {"tree_display_separate": False}
    return {}


def build_clan_command_reply(command_key, state, account, real_status=None, real_mylog=None):
    clan_state = dict(state or {})
    title = COMMAND_TITLES.get(command_key, str(command_key or ""))

    if command_key == "out_damage_monitor_on" and real_status:
        return _build_monitor_start_reply(clan_state, account, real_status)
    if command_key == "out_damage_monitor_off":
        return '出刀监控已关闭。'

    if real_status:
        return _build_real_reply(title, command_key, clan_state, account, real_status, real_mylog)

    if command_key == "out_damage_monitor_on":
        return _build_monitor_reply(True, clan_state, account)
    if command_key == "out_damage_monitor_off":
        return _build_monitor_reply(False, clan_state, account)
    if command_key == "status":
        return _build_status_reply(title, clan_state, account)
    if command_key in {
        "manual_report_on",
        "manual_report_off",
        "image_mode_on",
        "image_mode_off",
        "tree_display_separate_on",
        "tree_display_separate_off",
    }:
        return _build_toggle_reply(title, command_key)

    return f"{title}\uff1a\n{BACKEND_PENDING}\n{LOCAL_ONLY}"


def build_clan_reply(state, command):
    clan_state = dict(state or {})
    return _build_monitor_reply(bool(clan_state.get("out_damage_monitor")), clan_state, None)


def _build_monitor_reply(enabled, clan_state, account):
    if enabled:
        lines = ["\u51fa\u5200\u76d1\u63a7\u5df2\u5f00\u542f"]
    else:
        lines = ["\u51fa\u5200\u76d1\u63a7\u5df2\u5173\u95ed"]

    monitor_qq = clan_state.get("monitor_qq")
    if monitor_qq:
        lines.append(f"\u76d1\u63a7QQ\uff1a{monitor_qq}")

    account_text = _format_account(account)
    if account_text:
        lines.append(f"\u76d1\u63a7\u8d26\u53f7\uff1a{account_text}")
    elif enabled:
        lines.append(
            "\u63d0\u9192\uff1a\u5f53\u524d QQ \u8fd8\u6ca1\u6709"
            "\u79c1\u804a\u7ed1\u5b9a PCR \u8d26\u53f7\u3002"
        )

    lines.append(BACKEND_PENDING)
    lines.append(LOCAL_ONLY)
    return "\n".join(lines)


def _build_monitor_start_reply(clan_state, account, real_status):
    player_name = _player_name(account, real_status)
    monitor_id = clan_state.get("monitor_id") or ""
    lines = [
        "\u6b63\u5728\u767b\u5f55\u8d26\u53f7\uff0c\u8bf7\u8010\u5fc3\u7b49\u5f85\uff0c"
        f"\u5f53\u524d\u76d1\u63a7\u73a9\u5bb6\u4e3a{player_name}",
        "\u5f00\u59cb\u76d1\u63a7\u4e2d, \u53ef\u4ee5\u53d1\u9001\u3010\u53d6\u6d88\u51fa\u5200\u76d1\u63a7\u3011\u6216\u8005\u9876\u53f7\u9000\u51fa",
    ]
    if monitor_id:
        lines.append(f"#\u76d1\u63a7\u7f16\u53f7{monitor_id}")
    return "\n".join(lines)


def _build_status_reply(title, clan_state, account):
    lines = [
        f"{title}\uff1a",
        "\u51fa\u5200\u76d1\u63a7\uff1a" + _enabled_text(clan_state.get("out_damage_monitor")),
        "\u624b\u52a8\u62a5\u5200\uff1a" + _enabled_text(clan_state.get("manual_report_enabled")),
        "\u56fe\u7247\u6a21\u5f0f\uff1a" + _enabled_text(clan_state.get("image_mode_enabled")),
        "\u6302\u6811\u5355\u72ec\u663e\u793a\uff1a"
        + _enabled_text(clan_state.get("tree_display_separate")),
    ]

    monitor_qq = clan_state.get("monitor_qq")
    if monitor_qq:
        lines.append(f"\u76d1\u63a7QQ\uff1a{monitor_qq}")

    account_text = _format_account(account)
    if account_text:
        lines.append(f"\u76d1\u63a7\u8d26\u53f7\uff1a{account_text}")

    lines.append(BACKEND_PENDING)
    return "\n".join(lines)


def _build_toggle_reply(title, command_key):
    enabled = command_key.endswith("_on")
    return f'{title}：{_enabled_text(enabled)}。'


def _build_real_reply(title, command_key, clan_state, account, real_status, real_mylog):
    if not isinstance(real_status, dict):
        return _build_status_reply(title, clan_state, account)

    if command_key == "status":
        return f"{title}\uff1a\n{build_clan_status_text(real_status, clan_state, account)}"
    if command_key in {
        "current_report", "today_report", "yesterday_report", "my_report",
        "today_damage", "yesterday_damage", "damage_detail",
    }:
        scoped = prepare_clan_report(real_status, command_key, real_mylog)
        formatter = build_damage_count_summary if command_key in {"today_damage", "yesterday_damage"} else build_current_report_text
        return f"{title}\uff1a\n{formatter(scoped)}"

    lines = [f"{title}\uff1a"]
    lines.extend(_real_header_lines(clan_state, account, real_status))

    if command_key in {"current_report", "today_report", "today_damage", "damage_detail"}:
        lines.append("")
        lines.append("\u6700\u8fd1\u51fa\u5200\uff1a")
        lines.extend(_format_damage_history(real_status.get("damage_history") or []))
    elif command_key in {"my_report", "yesterday_report", "yesterday_damage"}:
        lines.append("")
        lines.append("\u6211\u7684\u6218\u62a5\uff1a")
        lines.extend(_format_mylog(real_mylog or {}))
    elif command_key in {"out_damage_monitor_on", "out_damage_monitor_off"}:
        enabled = command_key == "out_damage_monitor_on"
        lines.insert(0, "\u51fa\u5200\u76d1\u63a7\u5df2\u5f00\u542f" if enabled else "\u51fa\u5200\u76d1\u63a7\u5df2\u5173\u95ed")

    return "\n".join(lines)


def _real_header_lines(clan_state, account, real_status):
    lines = [
        "\u51fa\u5200\u76d1\u63a7\uff1a" + _enabled_text(clan_state.get("out_damage_monitor")),
    ]
    monitor_qq = clan_state.get("monitor_qq")
    if monitor_qq:
        lines.append(f"\u76d1\u63a7QQ\uff1a{monitor_qq}")
    lines.append(f"\u76d1\u63a7\u73a9\u5bb6\uff1a{_player_name(account, real_status)}")
    account_text = _format_account(account) or _format_real_account(real_status.get("account"))
    if account_text:
        lines.append(f"\u76d1\u63a7\u8d26\u53f7\uff1a{account_text}")

    clan = real_status.get("clan")
    clan = clan if isinstance(clan, dict) else {}
    battle = real_status.get("clan_battle")
    battle = battle if isinstance(battle, dict) else {}
    clan_name = _member_name({"name": clan.get("clan_name")}) or "\u672a\u77e5"
    lines.append(f"\u516c\u4f1a\uff1a{clan_name}({clan.get('clan_id', '-')})")
    if battle.get("id"):
        lines.append(f"clan_battle_id\uff1a{battle.get('id')}")
    phases = sorted({row["phase"] for row in build_clan_status_rows(real_status) if row["phase"] is not None})
    phase = phases[0] if len(phases) == 1 else None
    if len(phases) > 1:
        phase = "\u5404\u738b\u9636\u6bb5\u4e0d\u540c\uff0c\u8be6\u89c1\u4e0b\u65b9"
    lines.append(f"\u9636\u6bb5\uff1a{phase if phase is not None else '\u672a\u77e5'}")
    if battle.get("period") is not None:
        lines.append(f"\u4f1a\u6218\u671f\u6b21\uff1a{battle['period']}")
    rank = _first_value(battle, "own_rank", "clan_rank")
    if rank is None:
        rank = _first_value(clan, "rank", "clan_rank")
    lines.append(f"\u516c\u4f1a\u6392\u540d\uff1a{rank if rank is not None else '\u672a\u77e5'}")
    if battle.get("period_rank") is not None:
        lines.append(f"\u672c\u671f\u6392\u540d\uff1a{battle['period_rank']}")
    return lines


def build_clan_status_text(real_status, clan_state=None, account=None):
    """Describe all five bosses; never derive max HP or locks from lap numbers."""
    status = real_status if isinstance(real_status, dict) else {}
    lines = _real_header_lines(clan_state or {}, account, status)
    lines.append("")
    for row in build_clan_status_rows(status):
        lap = f"{row['lap_num']}\u5468\u76ee" if row["lap_num"] is not None else "\u5468\u76ee\u672a\u77e5"
        phase = f"{row['phase']}\u9636\u6bb5" if row["phase"] is not None else "\u9636\u6bb5\u672a\u77e5"
        hp = f"{row['current_hp']:,}" if row["current_hp"] is not None else "\u672a\u77e5"
        maximum = f"{row['max_hp']:,}" if row["max_hp"] is not None else "\u672a\u77e5"
        challenge = _challenge_text(row["can_challenge"])
        active = f" | \u5f53\u524d{row['attacking_count']}\u4eba\u51fa\u5200" if row["attacking_count"] is not None else ""
        lines.extend([
            f"{row['order_num']}\u738b | {lap} | {phase} | {challenge}{active}",
            f"\u5f53\u524d\u8840\u91cf {hp} / \u6700\u5927\u8840\u91cf {maximum} | \u6bd4\u4f8b {row['hp_percent']}",
        ])
    return "\n".join(lines)


def build_clan_status_rows(real_status):
    status = real_status if isinstance(real_status, dict) else {}
    bosses = status.get("boss_info")
    bosses = bosses if isinstance(bosses, list) else []
    by_order = {}
    for item in bosses:
        if not isinstance(item, dict):
            continue
        order = _number(_boss_order(item))
        if order in range(1, 6):
            by_order[order] = item
    rows = []
    for order in range(1, 6):
        boss = by_order.get(order, {})
        enemy = boss.get("enemy")
        enemy = enemy if isinstance(enemy, dict) else {}
        hp = _number(_first_value(boss, "current_hp", "hp", "boss_hp"))
        maximum = _number(_first_value(boss, "max_hp", "max_boss_hp", "hp_max"))
        if maximum is None:
            maximum = _number(enemy.get("max_hp"))
        hp = hp if hp is not None and hp >= 0 else None
        maximum = maximum if maximum is not None and maximum > 0 else None
        can_challenge = None
        for key in ("can_challenge", "is_challengeable", "is_unlocked"):
            flag = _flag(boss.get(key))
            if flag is not None:
                can_challenge = flag
                break
        if can_challenge is None:
            for key in ("is_locked", "is_unavailable", "cannot_challenge"):
                flag = _flag(boss.get(key))
                if flag is not None:
                    can_challenge = not flag
                    break
        rows.append({
            "order_num": order, "lap_num": _number(boss.get("lap_num")),
            "phase": _number(_first_value(boss, "phase", "phase_num", "stage")),
            "current_hp": hp, "max_hp": maximum, "can_challenge": can_challenge,
            "hp_percent": f"{hp / maximum * 100:.2f}%" if hp is not None and maximum else "\u672a\u77e5",
            "attacking_count": _active_battle_count(boss),
        })
    return rows


def _first_value(payload, *keys):
    for key in keys:
        if payload.get(key) is not None:
            return payload[key]
    return None


def _challenge_text(can_challenge):
    if can_challenge is False:
        return "\u65e0\u6cd5\u6311\u6218"
    if can_challenge is True:
        return "\u53ef\u6311\u6218"
    return "\u6311\u6218\u72b6\u6001\u672a\u77e5"


def _format_damage_history(items):
    if not items:
        return ["\u6682\u65e0\u51fa\u5200\u8bb0\u5f55"]
    lines = []
    for item in items[:10]:
        name = item.get("name") or item.get("user_name") or item.get("viewer_id") or "-"
        lap = item.get("lap_num", "-")
        order = item.get("order_num", "-")
        damage = _format_number(item.get("damage"))
        kill = " \u51fb\u7834" if item.get("kill") else ""
        lines.append(f"{name} {lap}-{order} {damage}{kill}")
    return lines


def _format_mylog(payload):
    logs = []
    if isinstance(payload, dict):
        logs = payload.get("actual_logs") or []
    if not logs:
        return ["\u6682\u65e0\u6211\u7684\u6b63\u5f0f\u51fa\u5200\u8bb0\u5f55"]
    lines = []
    for item in logs[:10]:
        lap = item.get("lap_num", "-")
        order = item.get("order_num", "-")
        damage = _format_number(item.get("total_damage"))
        is_auto = "\u81ea\u52a8" if item.get("is_auto") else "\u624b\u52a8"
        lines.append(f"{lap}-{order} {damage} {is_auto}")
    return lines


def _format_real_account(account):
    if not isinstance(account, dict) or not account.get("uid"):
        return ""
    channel = account.get("channel") or "\u6e20\u9053\u670d"
    return f"{channel} {mask_value(account.get('uid'))}"


def _player_name(account, real_status):
    status = real_status if isinstance(real_status, dict) else {}
    real_account = status.get("account")
    real_account = real_account if isinstance(real_account, dict) else {}
    value = _member_name({"name": real_account.get("user_name") or real_account.get("name")})
    if value:
        return value
    viewer_id = _viewer_id(real_account) or _viewer_id(account)
    if viewer_id:
        for member in _members(status):
            if _viewer_id(member) == viewer_id and _member_name(member):
                return _member_name(member)
    # A bound account's nickname can be a local label, not an in-game name.
    if isinstance(account, dict) and account.get("user_name"):
        return _member_name({"user_name": account["user_name"]})
    return "\u672a\u77e5\u73a9\u5bb6"


def _format_number(value):
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "-"


def _format_account(account):
    if not isinstance(account, dict):
        return ""
    uid = account.get("uid")
    if not uid:
        return ""
    kind = account.get("kind") or ""
    return f"{kind} {mask_value(uid)}".strip()


def _enabled_text(value):
    return "\u5df2\u5f00\u542f" if bool(value) else "\u5df2\u5173\u95ed"
