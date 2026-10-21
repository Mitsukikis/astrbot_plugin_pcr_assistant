"""Synthetic, offline unit tests: no game accounts, servers or Github writes."""

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clan_coordination import COORDINATION_COMMANDS, handle_clan_coordination
from clan_history import (
    CN_TIMEZONE, MAX_HISTORY_RECORDS, game_day_bounds, merge_clan_history,
    select_clan_report,
)


def stamp(value):
    return int(datetime.fromisoformat(value).replace(tzinfo=CN_TIMEZONE).timestamp())


NOW = stamp("2026-10-21T12:00:00")
RESET = stamp("2026-10-21T05:00:00")
QQ_A, QQ_B, OWNER = "10001", "10002", "10003"


def hit(identifier, viewer_id=101, **fields):
    return {
        "history_id": identifier, "viewer_id": viewer_id,
        "name": "合成甲" if viewer_id == 101 else "合成乙",
        "damage": 100, "order_num": 1, "lap_num": 10,
        "create_time": RESET, **fields,
    }


def snapshot(*rows, **fields):
    return {
        "ok": True, "clan": {"clan_id": 7, "clan_name": "合成测试公会"},
        "clan_battle": {"id": 88, "period": 1, "own_rank": 20},
        "account": {"uid": 101, "user_name": "合成甲"},
        "members": [{"viewer_id": 101, "name": "合成甲"},
                    {"viewer_id": 102, "name": "合成乙"},
                    {"viewer_id": 103, "name": "合成零刀"}],
        "boss_info": [{"order_num": 1, "current_hp": 900, "lap_num": 10}],
        "damage_history": list(rows), **fields,
    }


def ids(status):
    return {str(row["history_id"]) for row in status["damage_history"] if row.get("history_id")}


def coordinate(state, command, payload="", qq=QQ_A, name="合成玩家", **kwargs):
    kwargs.setdefault("now", NOW)
    return handle_clan_coordination(command, payload, state, qq, name, **kwargs)


def test_archive_accumulates_dedupes_and_never_caches_live_fields():
    state = {"unrelated": {"preserved": True}}
    first = snapshot(hit(1), hit(2))
    original = deepcopy(first)
    merged = merge_clan_history(state, first, now=NOW)
    assert first == original
    assert ids(merged) == {"1", "2"}
    assert state["observed_history_meta"]["observed_from"] == NOW

    fresh = snapshot(hit("2", damage=250), hit(3))
    fresh["clan_battle"]["own_rank"] = 4
    fresh["boss_info"][0]["current_hp"] = 600
    fresh["account"]["user_name"] = "新游戏名"
    fresh["members"] = [{"viewer_id": 101, "name": "新游戏名"}]
    merged = merge_clan_history(state, fresh, now=NOW + 60)
    assert ids(merged) == {"1", "2", "3"}
    assert len(merged["damage_history"]) == 3
    assert next(row for row in merged["damage_history"] if str(row["history_id"]) == "2")["damage"] == 250
    for key in ("boss_info", "account", "members", "clan_battle"):
        assert merged[key] == fresh[key]
        assert key not in state
    assert state["unrelated"] == {"preserved": True}
    assert merged["observed_from"] == NOW
    merged["boss_info"][0]["current_hp"] = 1
    merged["damage_history"][0]["damage"] = 1
    assert fresh["boss_info"][0]["current_hp"] == 600
    assert all(row["damage"] != 1 for row in state["observed_damage_history"])


@pytest.mark.parametrize("section,key,value", [("clan", "clan_id", 8), ("clan_battle", "id", 89)])
def test_archive_context_changes_clear_reset_history_ids(section, key, value):
    state = {}
    merge_clan_history(state, snapshot(hit(1), hit(100)), now=NOW)
    fresh = snapshot(hit(1, damage=999))
    fresh[section][key] = value
    result = merge_clan_history(state, fresh, now=NOW + 1)
    assert ids(result) == {"1"}
    assert result["damage_history"][0]["damage"] == 999
    assert result["observed_from"] == NOW + 1
    assert len(state["observed_damage_history"]) == 1


def test_archive_normalizes_context_and_does_not_use_period_as_entire_battle():
    state = {}
    merge_clan_history(state, snapshot(hit(1, period=1)), now=NOW)
    fresh = snapshot(hit(2, period=2))
    fresh["clan"]["clan_id"] = "7"
    fresh["clan_battle"].update(id="88", period=2)
    result = merge_clan_history(state, fresh, now=NOW + 1)
    assert ids(select_clan_report(result, "current_report")) == {"1", "2"}


def test_archive_rejects_explicit_foreign_records_and_updates_kill():
    state = {}
    merge_clan_history(state, snapshot(hit(1, kill=False, score=10)), now=NOW)
    result = merge_clan_history(state, snapshot(
        hit("1", kill=True, create_time=None, score=None),
        hit(2, clan_id=8), hit(3, clan_battle_id=89), hit(4, battle_id=89),
    ), now=NOW + 1)
    assert ids(result) == {"1"}
    assert result["damage_history"][0]["kill"] is True
    assert result["damage_history"][0]["create_time"] == RESET
    assert result["damage_history"][0]["score"] == 10
    assert "已排除3条" in result["history_scope"]


def test_archive_false_zero_corrections_override_previous_values():
    state = {}
    merge_clan_history(state, snapshot(hit(1, kill=True, score=20)), now=NOW)
    result = merge_clan_history(state, snapshot(hit(1, kill=False, score=0, damage=0)), now=NOW)
    assert result["damage_history"][0]["score"] == 0
    assert result["damage_history"][0]["kill"] is False
    assert result["damage_history"][0]["damage"] == 0


def test_archive_limit_is_sticky_until_context_changes():
    state = {}
    result = merge_clan_history(state, snapshot(*[hit(index) for index in range(1, MAX_HISTORY_RECORDS + 3)]), now=NOW)
    assert len(state["observed_damage_history"]) == MAX_HISTORY_RECORDS
    assert len(result["damage_history"]) == MAX_HISTORY_RECORDS
    assert "1" not in ids(result) and "2" not in ids(result)
    assert result["history_truncated"] is True
    assert "截断" in result["history_scope"]
    result = merge_clan_history(state, snapshot(), now=NOW + 1)
    assert result["history_truncated"] is True
    fresh = snapshot(hit(1))
    fresh["clan_battle"]["id"] = 89
    result = merge_clan_history(state, fresh, now=NOW + 2)
    assert result["history_truncated"] is False


def test_partial_pages_are_not_promoted_to_complete_history():
    state = {}
    result = merge_clan_history(state, snapshot(
        hit(1, create_time=None), history_complete=True, damage_history_complete=True,
    ), now=NOW)
    assert result["history_complete"] is False
    assert result["damage_history_complete"] is False
    assert result["observed_from"] == NOW
    assert "不保证连续覆盖" in result["history_scope"]
    assert "时间未知" in result["history_scope"]
    assert "不代表整期" in result["history_scope"]


def test_idless_rows_are_not_accumulated_or_guessed_equal():
    state = {}
    row = hit(None)
    first = merge_clan_history(state, snapshot(row, deepcopy(row), hit(1)), now=NOW)
    assert len(first["damage_history"]) == 3
    assert len(state["observed_damage_history"]) == 1
    second = merge_clan_history(state, snapshot(row, deepcopy(row)), now=NOW + 1)
    assert len(second["damage_history"]) == 3
    assert "缺少有效history_id" in second["history_scope"]
    third = merge_clan_history(state, snapshot(), now=NOW + 2)
    assert ids(third) == {"1"}


@pytest.mark.parametrize("broken", [{}, {"clan": {"clan_id": 7}}, {"ok": False}])
def test_unknown_or_failed_context_never_reuses_archive(broken):
    state = {}
    merge_clan_history(state, snapshot(hit(1)), now=NOW)
    saved = deepcopy(state)
    result = merge_clan_history(state, {"damage_history": [hit(2)], **broken}, now=NOW + 1)
    assert "1" not in ids(result)
    assert state == saved
    assert result["history_complete"] is False
    assert "未累积归档" in result["history_scope"]


def test_archive_state_can_be_serialized_and_restored_without_loss():
    state = {}
    merge_clan_history(state, snapshot(hit(1)), now=NOW)
    restored = json.loads(json.dumps(state))
    result = merge_clan_history(restored, snapshot(hit("1"), hit(2)), now=NOW + 10)
    assert ids(result) == {"1", "2"}
    assert result["observed_from"] == NOW


@pytest.mark.parametrize("now,start", [(RESET - 1, RESET - 86400), (RESET, RESET), (RESET + 86400 - 1, RESET)])
def test_cn_game_day_bounds(now, start):
    assert game_day_bounds(now) == (start, start + 86400)


@pytest.mark.parametrize("command,expected", [
    ("current_report", {"1", "2", "3", "4", "5"}),
    ("my_report", {"1", "2", "4"}),
    ("today_damage", {"2", "3"}),
    ("yesterday_damage", {"1"}),
    ("today_report", {"2"}),
    ("yesterday_report", {"1"}),
])
def test_report_command_scopes_use_archive_identity_and_game_days(command, expected):
    real = snapshot(
        hit(1, create_time=RESET - 1), hit(2, create_time=RESET),
        hit(3, viewer_id=102, create_time=RESET + 1),
        hit(4, create_time=None),
        hit(5, viewer_id=102, create_time=RESET + 86400),
    )
    merged = merge_clan_history({}, real, now=NOW)
    original = deepcopy(merged)
    result = select_clan_report(merged, command, now=NOW)
    assert ids(result) == expected
    assert merged == original
    assert result["history_complete"] is False
    assert result["observed_from"] == NOW
    assert "筛选范围" in result["history_scope"]
    if command in {"my_report", "today_report", "yesterday_report"}:
        assert {member["viewer_id"] for member in result["members"]} == {101}
    else:
        assert len(result["members"]) == 3
    if command.startswith(("today_", "yesterday_")):
        assert result["history_unknown_time_count"] == 1
        assert "时间未知" in result["history_scope"]


@pytest.mark.parametrize("payload,expected", [("昨日", {"1"}), ("昨日 合成乙", {"2"}), ("合成乙 昨天", {"2"}), ("今日", {"3"})])
def test_my_report_day_modifiers_never_become_today_mylog(payload, expected):
    real = snapshot(hit(1, create_time=RESET - 1), hit(2, viewer_id=102, create_time=RESET - 1), hit(3))
    real["actual_logs"] = [{"mylog_id": 7, "total_damage": 9999}]
    result = select_clan_report(real, "my_report", payload, now=NOW)
    assert ids(result) == expected
    assert all(row["damage"] != 9999 for row in result["damage_history"])


def test_named_report_filters_renamed_member_by_viewer_not_history_label():
    real = snapshot(hit(1, name="旧名"), hit(2, viewer_id=102, name="合成甲"),
                    hit(3, viewer_id=None, name="合成甲"))
    result = select_clan_report(real, "today_report", "合成甲", now=NOW)
    assert ids(result) == {"1"}
    assert result["report_viewer_id"] == "101"
    with pytest.raises(ValueError, match="不存在"):
        select_clan_report(real, "today_report", "旧名", now=NOW)


def test_unknown_name_and_ambiguous_names_raise_instead_of_group_fallback():
    real = snapshot(hit(1), hit(2, viewer_id=102))
    with pytest.raises(ValueError, match="不存在"):
        select_clan_report(real, "current_report", "不存在的合成名")
    real["members"][1]["name"] = "合成甲"
    with pytest.raises(ValueError, match="重名"):
        select_clan_report(real, "my_report", "合成甲")


def test_departed_member_with_known_viewer_can_be_selected_without_fake_roster():
    result = select_clan_report(snapshot(hit(1, viewer_id=104, name="合成离会成员")), "current_report", "合成离会成员")
    assert ids(result) == {"1"}
    assert result["members"] == []


def test_self_prefers_account_uid_and_missing_self_never_falls_back_to_group():
    real = snapshot(hit(1), hit(2, viewer_id=102))
    real["account"]["viewer_id"] = 102
    assert ids(select_clan_report(real, "my_report")) == {"1"}
    real["account"] = {}
    with pytest.raises(ValueError, match="account.uid"):
        select_clan_report(real, "my_report")


def test_all_real_roster_aliases_are_filtered_without_synthetic_members():
    real = snapshot(hit(1), hit(2, viewer_id=102))
    real["clan"]["member_list"] = deepcopy(real["members"])
    real["clan_members"] = deepcopy(real["members"])
    result = select_clan_report(real, "today_report", "合成零刀", now=NOW)
    assert result["damage_history"] == []
    for entries in (result["members"], result["clan_members"], result["clan"]["member_list"]):
        assert entries == [{"viewer_id": 103, "name": "合成零刀"}]


@pytest.mark.parametrize("event_time", [RESET, RESET * 1000, str(RESET), "2026-10-21T05:00:00+08:00", "2026-10-20T21:00:00Z", "2026-10-21 05:00:00"])
def test_event_timestamp_formats(event_time):
    real = snapshot(hit(1, create_time=event_time))
    assert ids(select_clan_report(real, "today_damage", now=NOW)) == {"1"}


@pytest.mark.parametrize("event_time", [None, 90, 0, True, "bad", "NaN", "Infinity", "2026-10-21"])
def test_unknown_time_never_uses_poll_time_or_remaining_seconds(event_time):
    real = snapshot(hit(1, create_time=event_time, finish_time=20), observed_from=NOW)
    selected = select_clan_report(real, "today_damage", now=NOW)
    assert selected["damage_history"] == []
    assert selected["history_unknown_time_count"] == 1
    assert ids(select_clan_report(real, "current_report", now=NOW)) == {"1"}


def test_previous_game_day_before_five_am_and_conflicting_modifier():
    real = snapshot(hit(1, create_time=RESET - 1), hit(2, create_time=RESET))
    assert ids(select_clan_report(real, "today_damage", now=RESET - 1)) == {"1"}
    with pytest.raises(ValueError, match="冲突"):
        select_clan_report(real, "today_report", "昨日", now=NOW)
    with pytest.raises(ValueError, match="同时"):
        select_clan_report(real, "my_report", "今日 昨日", now=NOW)


@pytest.mark.parametrize("payload", ["500", "#500", "0500"])
def test_damage_detail_uses_real_history_id_not_positional_index(payload):
    real = snapshot(hit(500), hit(900, viewer_id=102))
    assert ids(select_clan_report(real, "damage_detail", payload)) == {"500"}
    for invalid in ("1", "2", "", "500 900", "1.5", "0"):
        with pytest.raises(ValueError):
            select_clan_report(real, "damage_detail", invalid)


def test_select_preserves_live_rank_without_archive_ranking_fallback():
    state = {}
    merge_clan_history(state, snapshot(hit(1)), now=NOW)
    fresh = snapshot(hit(2))
    fresh["clan_battle"].pop("own_rank")
    selected = select_clan_report(merge_clan_history(state, fresh, now=NOW), "current_report")
    assert "own_rank" not in selected["clan_battle"]
    assert ids(selected) == {"1", "2"}


def test_local_reservations_are_qq_keyed_and_do_not_create_game_roster():
    state = {"members": [{"viewer_id": 101, "name": "真实结构合成成员"}]}
    coordinate(state, "reserve", "1王 备刀", qq=QQ_A, name="同名")
    coordinate(state, "reserve", "1", qq=QQ_B, name="同名")
    coordinate(state, "reserve", "1 更新备注", qq=QQ_A, name="改名", now=NOW + 1)
    coordinate(state, "reserve", "boss 5", qq=QQ_A)
    reservations = state["clan_coordination"]["reservations"]
    assert set(reservations["1"]) == {QQ_A, QQ_B}
    assert reservations["1"][QQ_A]["note"] == "更新备注"
    assert reservations["1"][QQ_A]["created_at"] == NOW
    assert reservations["5"][QQ_A]["qq"] == QQ_A
    table = coordinate(state, "reservation_table")
    assert QQ_A in table and QQ_B in table and "改名" in table
    assert "备刀" not in table
    assert "仅为本群本地登记" in table
    assert state["members"] == [{"viewer_id": 101, "name": "真实结构合成成员"}]


@pytest.mark.parametrize("command", ["reserve", "hang_tree", "apply_damage"])
@pytest.mark.parametrize("payload", ["", "0", "6", "-1", "1.5", "1 2 3\n4\n5\n6" if False else "99", "一王", "2王多余字符"])
def test_local_invalid_boss_is_rejected_without_state_changes(command, payload):
    state = {"unrelated": True}
    saved = deepcopy(state)
    result = coordinate(state, command, payload)
    assert "1至5" in result
    assert state == saved


@pytest.mark.parametrize("command", ["reservation_table", "check_tree", "cancel_reservation", "clear_reservation", "leave_tree", "cancel_apply", "clear_apply"])
def test_optional_boss_is_validated_for_queries_and_removals(command):
    state = {}
    result = coordinate(state, command, "6", is_admin=True)
    assert "1至5" in result
    assert state == {}


def test_self_cancel_cannot_remove_others_even_when_admin():
    state = {}
    for qq in (QQ_A, QQ_B):
        coordinate(state, "reserve", "1", qq=qq)
        coordinate(state, "reserve", "2", qq=qq)
        coordinate(state, "apply_damage", "1", qq=qq)
    coordinate(state, "cancel_reservation", "1", is_admin=True)
    assert QQ_A not in state["clan_coordination"]["reservations"]["1"]
    assert QQ_B in state["clan_coordination"]["reservations"]["1"]
    assert QQ_A in state["clan_coordination"]["reservations"]["2"]
    coordinate(state, "cancel_reservation")
    assert set(state["clan_coordination"]["reservations"]["2"]) == {QQ_B}
    coordinate(state, "cancel_apply", is_admin=True)
    assert set(state["clan_coordination"]["applications"]) == {QQ_B}


@pytest.mark.parametrize("command", ["clear_reservation", "clear_apply"])
def test_clear_requires_group_owner_or_trusted_admin(command):
    state = {"owner_qq": OWNER, "monitor_qq": QQ_A}
    coordinate(state, "reserve", "1", qq=QQ_B)
    coordinate(state, "apply_damage", "1", qq=QQ_B)
    saved = deepcopy(state)
    assert "只有群主或管理员" in coordinate(state, command)
    assert state == saved
    coordinate(state, command, qq=OWNER)
    key = "reservations" if command == "clear_reservation" else "applications"
    assert state["clan_coordination"][key] == {}


def test_admin_boss_specific_clear_preserves_other_bosses():
    state = {}
    coordinate(state, "reserve", "1")
    coordinate(state, "reserve", "2", qq=QQ_B)
    coordinate(state, "apply_damage", "1")
    coordinate(state, "apply_damage", "2", qq=QQ_B)
    coordinate(state, "clear_reservation", "1", is_admin=True)
    coordinate(state, "clear_apply", "1", is_admin=True)
    assert set(state["clan_coordination"]["reservations"]) == {"2"}
    assert set(state["clan_coordination"]["applications"]) == {QQ_B}


def test_tree_upsert_and_leave_preserve_other_qq_and_boss_filters():
    state = {}
    coordinate(state, "hang_tree", "1 保持", name="甲")
    coordinate(state, "hang_tree", "1", qq=QQ_B, name="乙")
    coordinate(state, "hang_tree", "3 等合刀", name="甲新名")
    assert len(state["clan_coordination"]["trees"]) == 2
    assert QQ_A not in coordinate(state, "check_tree", "1")
    assert "甲新名" in coordinate(state, "check_tree", "3")
    assert "没有挂树" in coordinate(state, "leave_tree", "1")
    coordinate(state, "leave_tree")
    assert set(state["clan_coordination"]["trees"]) == {QQ_B}


def test_apply_queue_is_local_unique_stable_and_can_switch_boss():
    state = {}
    result = coordinate(state, "apply_damage", "1", name="甲")
    assert "第1位" in result and "不代表游戏内已进刀" in result
    result = coordinate(state, "apply_damage", "1", qq=QQ_B, name="乙")
    assert "第2位" in result
    result = coordinate(state, "apply_damage", "1 备注更新", name="甲新名", now=NOW + 20)
    assert "第1位" in result
    assert len(state["clan_coordination"]["applications"]) == 2
    coordinate(state, "apply_damage", "5", now=NOW + 30)
    assert state["clan_coordination"]["applications"][QQ_A]["boss"] == 5
    assert state["clan_coordination"]["applications"][QQ_A]["created_at"] == NOW + 30
    coordinate(state, "cancel_apply", "1")
    assert QQ_A in state["clan_coordination"]["applications"]
    coordinate(state, "cancel_apply", "5")
    assert set(state["clan_coordination"]["applications"]) == {QQ_B}


def test_sl_is_once_per_qq_and_resets_at_cn_five_not_midnight():
    state = {}
    assert "已记录" in coordinate(state, "sl", now=RESET - 100)
    original_entry = deepcopy(state["clan_coordination"]["sl_records"][QQ_A])
    assert "不会重复记录" in coordinate(state, "record_sl", "3 重复", now=RESET - 1)
    assert state["clan_coordination"]["sl_records"][QQ_A] == original_entry
    assert "已记录" in coordinate(state, "record_sl", "5 可选备注", now=RESET)
    assert state["clan_coordination"]["sl_records"][QQ_A]["boss"] == 5
    assert "已记录" in coordinate(state, "sl", qq=QQ_B, now=RESET + 1)
    assert "不会重复记录" in coordinate(state, "sl", now=RESET + 86400 - 1)
    status = coordinate(state, "sl_status", now=RESET + 86400 - 1)
    assert QQ_A in status and QQ_B in status and "已登记SL" in status
    assert "暂无登记" in coordinate(state, "sl_status", now=RESET + 86400)
    assert state["clan_coordination"]["sl_records"] == {}


def test_sl_date_rollover_in_month_boundary():
    state = {}
    before = stamp("2026-11-01T04:59:59")
    coordinate(state, "sl", now=before)
    assert "不会重复记录" in coordinate(state, "record_sl", now=before)
    assert "已记录" in coordinate(state, "record_sl", now=before + 1)


def test_permission_query_cannot_grant_rights_from_payload_or_player_name():
    state = {"monitor_qq": QQ_A}
    saved = deepcopy(state)
    result = coordinate(state, "permission", "管理员", name="群主")
    assert "普通成员" in result
    assert "不能通过此命令授予" in result
    assert state == saved
    assert "群主或管理员" in coordinate(state, "permission", is_admin=True)


def test_group_states_are_independent_and_json_roundtrip_keeps_qq_identity():
    first, second = {}, {}
    coordinate(first, "reserve", "1")
    coordinate(first, "sl")
    coordinate(first, "hang_tree", "2")
    coordinate(first, "apply_damage", "3")
    saved = json.loads(json.dumps(first))
    assert QQ_A not in coordinate(second, "reservation_table")
    assert QQ_A not in coordinate(second, "check_tree")
    assert "尚未登记SL" in coordinate(second, "sl_status")
    assert "不会重复记录" in coordinate(saved, "record_sl")
    coordinate(saved, "cancel_reservation", qq=int(QQ_A))
    assert saved["clan_coordination"]["reservations"] == {}
    assert first["clan_coordination"]["reservations"] != {}


@pytest.mark.parametrize("qq", [None, "", "昵称而非QQ", "@10001", True, 0, -1, "1.5"])
def test_invalid_sender_does_not_mutate_state(qq):
    state = {}
    assert "无法确认" in coordinate(state, "reserve", "1", qq=qq)
    assert state == {}


def test_unknown_commands_return_none_without_side_effects():
    state = {}
    assert coordinate(state, "current_report") is None
    assert state == {}
    with pytest.raises(ValueError, match="不支持"):
        select_clan_report(snapshot(), "not_a_report")


@pytest.mark.parametrize("command", sorted(COORDINATION_COMMANDS))
def test_all_coordination_commands_return_natural_local_text(command):
    required = command in {"reserve", "hang_tree", "apply_damage"}
    result = coordinate({}, command, "1" if required else "", is_admin=True, name="")
    assert isinstance(result, str) and result
    assert "后端" not in result and "占位" not in result
    assert "仅为本群本地登记" in result


def test_shared_archive_and_coordination_state_do_not_modify_each_other():
    state = {}
    merge_clan_history(state, snapshot(hit(1)), now=NOW)
    history = deepcopy(state["observed_damage_history"])
    coordinate(state, "reserve", "1")
    local = deepcopy(state["clan_coordination"])
    merge_clan_history(state, snapshot(hit(2)), now=NOW + 1)
    assert state["clan_coordination"] == local
    assert history[0] in state["observed_damage_history"]
