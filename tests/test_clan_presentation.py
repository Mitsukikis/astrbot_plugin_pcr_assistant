import copy
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clan_report import (
    _load_font, _wrap_text, build_current_report_rows, build_current_report_text,
    build_damage_count_summary, prepare_clan_report, render_clan_report,
    render_clan_status, render_text_image,
)
from clan_state import build_clan_command_reply, build_clan_status_rows, build_clan_status_text
from monitoring import update_clan_damage_state


def _hit(history_id, viewer_id=1, **fields):
    return {
        "history_id": history_id, "viewer_id": viewer_id, "name": "\u5408\u6210\u6210\u5458",
        "lap_num": 32, "order_num": 4, "damage": 100, **fields,
    }


def _snapshot(*hits, period=1, **fields):
    return {
        "clan": {"clan_id": 42, "clan_name": "\u5408\u6210\u6f14\u793a\u516c\u4f1a\uff08\u975e\u771f\u5b9e\u6570\u636e\uff09"},
        "clan_battle": {"id": 123, "period": period, "own_rank": 321},
        "damage_history": list(hits), **fields,
    }


def synthetic_preview_status():
    """Explicitly fabricated presentation fixture, never a player/runtime capture."""
    members = [
        {"viewer_id": 90001, "name": "\u5408\u6210\u7532"},
        {"viewer_id": 90002, "name": "\u5408\u6210\u540c\u540d"},
        {"viewer_id": 90003, "name": "\u5408\u6210\u540c\u540d"},
        {"viewer_id": 90004, "name": "\u5408\u6210\u957f\u540d\u5b57\u7528\u4e8e\u9a8c\u8bc1\u4e2d\u6587\u6362\u884c\u4e0e\u8868\u683c\u8fb9\u754c\u4e0d\u4f1a\u6ea2\u51fa"},
        {"viewer_id": 90005, "name": "\u5408\u6210\u96f6\u5200\u6210\u5458"},
        {"viewer_id": 90006, "name": "\u5408\u6210\u4e59"},
        {"viewer_id": 90007, "name": "\u5408\u6210\u4e19"},
    ]
    damages = [318455848, 245678901, 202020202, 111111111, 88000000, 63000000]
    hits = [
        _hit(index, viewer_id=member["viewer_id"], name=member["name"], damage=damage,
             create_time="2026-10-21T12:30:00+08:00", kill=index == 1)
        for index, (member, damage) in enumerate(zip(members[:4] + members[5:], damages), 1)
    ]
    hits.append(_hit(7, viewer_id=90001, name="\u5408\u6210\u7532", damage=208000000))
    bosses = [
        {"order_num": order, "lap_num": 32, "phase": 4,
         "current_hp": hp, "max_hp": maximum, "can_challenge": order != 2,
         "attacking_count": 1 if order == 4 else 0}
        for order, hp, maximum in (
            (1, 318000000, 600000000), (2, 0, 650000000),
            (3, 427000000, 700000000), (4, 281544152, 800000000),
            (5, 900000000, 900000000),
        )
    ]
    return _snapshot(*hits, period=2, members=members, boss_info=bosses,
                     history_scope="\u533f\u540d\u6a21\u62df\u9884\u89c8\uff1a\u4ec5\u5df2\u91c7\u96c6\u8bb0\u5f55\uff0c\u975e\u6574\u6708",
                     account={"viewer_id": 90001, "user_name": "\u5408\u6210\u76d1\u63a7\u73a9\u5bb6\uff08\u975e\u771f\u5b9e\uff09"})


def test_viewer_id_identity_includes_roster_zeros_and_renames():
    status = _snapshot(
        _hit(1, viewer_id="1", name="\u65e7\u540d", damage=300),
        _hit(2, viewer_id=1, name="\u53e6\u4e00\u65e7\u540d", damage=200),
        _hit(3, viewer_id=2, name="\u540c\u540d", damage=100),
        members=[
            {"viewer_id": 1, "name": "\u540c\u540d"},
            {"viewer_id": "1", "name": "\u540c\u540d"},
            {"viewer_id": 2, "name": "\u540c\u540d"},
            {"viewer_id": 3, "name": "\u96f6\u5200"},
        ],
    )
    before = copy.deepcopy(status)
    rows = {row["viewer_id"]: row for row in build_current_report_rows(status)}
    assert set(rows) == {"1", "2", "3"}
    assert (rows["1"]["name"], rows["1"]["damage"], rows["1"]["hits"]) == ("\u540c\u540d", 500, 2)
    assert rows["2"]["damage"] == 100
    assert rows["3"]["hits"] == 0
    assert rows["3"]["score"] == "-"
    assert "[ID:1]" in build_current_report_text(status)
    assert "[ID:2]" in build_damage_count_summary(status)
    assert status == before


def test_idless_history_is_not_assigned_to_a_same_name_viewer():
    rows = build_current_report_rows({
        "members": [{"viewer_id": 1, "name": "\u540c\u540d"}, {"viewer_id": 2, "name": "\u540c\u540d"}],
        "damage_history": [{"name": "\u540c\u540d", "damage": 300}],
    })
    assert len(rows) == 3
    assert all(row["hits"] == 0 for row in rows if row["viewer_id"])
    assert next(row for row in rows if not row["viewer_id"])["damage"] == 300
    assert "\u8eab\u4efd\u672a\u786e\u8ba4" in build_current_report_text({"damage_history": [{"name": "\u540c\u540d", "damage": 300}]})


def test_known_and_partial_scores_are_not_mixed_into_fake_total():
    status = _snapshot(
        _hit(1, score=900), _hit(2, score=None),
        _hit(3, viewer_id=2, score=200), _hit(4, viewer_id=3, damage_score=0),
    )
    rows = {row["viewer_id"]: row for row in build_current_report_rows(status)}
    assert rows["1"]["score"] == "-"
    assert rows["1"]["known_score"] == 900
    assert rows["1"]["score_percent"] == "-"
    assert rows["2"]["score"] == "200"
    assert rows["2"]["score_percent"] == "100.00%"
    assert not rows["2"]["score_percent_complete"]
    assert rows["3"]["score"] == "0"
    text = build_current_report_text(status)
    assert "\u5206\u6570\u672a\u5b8c\u6574\u8fd4\u56de" in text
    assert "\u4ec5\u6309\u5df2\u77e5\u5b8c\u6574\u5206\u6570\u8ba1\u7b97" in text


def test_full_scores_allow_score_ranking_and_percentages():
    rows = build_current_report_rows(_snapshot(
        _hit(1, viewer_id=1, damage=1000, score=1),
        _hit(2, viewer_id=2, damage=10, battle_score=9),
    ))
    assert rows[0]["viewer_id"] == "2"
    assert rows[0]["score_percent"] == "90.00%"
    assert all(row["score_percent_complete"] for row in rows)


@pytest.mark.parametrize("fields,expected", [
    ({}, 1), ({"kill": True}, 1), ({"kill": 1}, 1),
    ({"is_compensation": None}, 1), ({"is_extra_time": "false"}, 1),
    ({"is_compensation": "unknown"}, 1), ({"is_extra_time": False}, 1),
    ({"is_extra_time": 1}, 0.5), ({"is_compensation": True}, 0.5),
    ({"is_compensation": "1"}, 0.5), ({"is_extra_time": "true"}, 0.5),
    ({"finish_time": 20}, 1), ({"finish_time": 0}, 1),
    ({"finish_time": 91}, 1), ({"finish_time": 1792555200}, 1),
    ({"finish_time": "unknown"}, 1),
])
def test_compensation_only_with_explicit_valid_markers(fields, expected):
    row = build_current_report_rows(_snapshot(_hit(1, **fields)))[0]
    assert row["hits"] == expected
    assert row["records"] == 1
    assert row["damage"] == 100


def test_count_summary_does_not_drop_half_hits_or_more_than_three_hits():
    status = _snapshot(*[_hit(index) for index in range(1, 6)], _hit(6, is_compensation=True),
                       members=[{"viewer_id": 2, "name": "\u96f6\u5200"}])
    text = build_damage_count_summary(status)
    assert "\u603b\u8ba1\u51fa\u5200: 5.5" in text
    assert "\u51fa\u4e865.5\u5200" in text
    assert "\u51fa\u4e860\u5200" in text
    assert "finish_time" in text


def test_history_dedupes_stable_ids_but_not_equal_idless_hits():
    a = _hit(1)
    status = _snapshot(a, copy.deepcopy(a), {"name": "\u65e0ID", "damage": 10}, {"name": "\u65e0ID", "damage": 10})
    rows = build_current_report_rows(status)
    assert sum(row["records"] for row in rows) == 3
    assert sum(row["damage"] for row in rows) == 120


def test_current_period_filter_does_not_mix_reset_history_ids():
    status = _snapshot(_hit(1, period=1), _hit(1, period=2, damage=250),
                       _hit(2, clan_battle_id=122, damage=1000), period=2)
    assert build_current_report_rows(status)[0]["damage"] == 250
    prepared = prepare_clan_report(status)
    assert "\u5df2\u6392\u96642\u6761" in "\n".join(prepared["presentation_notes"])


@pytest.mark.parametrize("command,expected", [
    ("today_report", 200), ("today_damage", 200),
    ("yesterday_report", 100), ("yesterday_damage", 100),
])
def test_day_reports_filter_times_at_game_reset_and_warn_missing(command, expected):
    status = _snapshot(
        _hit(1, create_time="2026-10-21T04:59:59+08:00", damage=100),
        _hit(2, create_time="2026-10-21T05:00:00+08:00", damage=200),
        _hit(3, create_time="2026-10-22T05:00:00+08:00", damage=300),
        _hit(4, damage=400), reference_time="2026-10-21T15:00:00+08:00",
    )
    prepared = prepare_clan_report(status, command)
    assert sum(row["damage"] for row in build_current_report_rows(prepared)) == expected
    assert "\u7f3a\u5c11\u53ef\u8bc6\u522b\u65f6\u95f4" in "\n".join(prepared["presentation_notes"])
    assert "UTC+8" in "\n".join(prepared["presentation_notes"])


def test_my_report_uses_only_actual_logs_and_never_falls_back_to_clan_history():
    status = _snapshot(_hit(1, damage=999), members=[{"viewer_id": 9, "name": "\u5176\u4ed6\u4eba"}],
                       damage_history_complete=True, account={"viewer_id": 1, "user_name": "\u6e38\u620f\u540d"})
    payload = {
        "actual_logs": [{"mylog_id": 7, "total_damage": 123}],
        "rehearsal_logs": [{"total_damage": 500}],
        "training_logs": [{"total_damage": 800}],
    }
    prepared = prepare_clan_report(status, "my_report", payload)
    rows = build_current_report_rows(prepared)
    assert len(rows) == 1
    assert rows[0]["name"] == "\u6e38\u620f\u540d"
    assert rows[0]["damage"] == 123
    assert prepared["damage_history_complete"] is False
    assert not build_current_report_rows(prepare_clan_report(status, "my_report"))


def test_history_scope_is_explicit_not_all_month():
    text = build_current_report_text(_snapshot(_hit(1)))
    assert "\u5386\u53f2\u5b8c\u6574\u6027\u672a\u786e\u8ba4" in text
    assert "\u4e0d\u4ee3\u8868\u5168\u6708\u7edf\u8ba1" in text
    assert "\u65e0\u660e\u786e\u8865\u507f\u6807\u8bb0\u4e0d\u6298\u5200" in text


def test_unknown_damage_and_invalid_score_are_not_fabricated():
    status = _snapshot(_hit(1, damage=None, score="bad"), _hit(2, viewer_id=2, damage=20, score=None))
    rows = build_current_report_rows(status)
    assert next(row for row in rows if row["viewer_id"] == "1")["damage_complete"] is False
    assert all(row["damage_percent"] == "-" for row in rows)
    assert "\u672a\u77e5\u4e0d\u4f5c0" in build_current_report_text(status)


def test_first_poll_baselines_history_but_keeps_live_attacking_notice():
    state = {}
    status = _snapshot(_hit(10), boss_info=[{"order_num": 4, "attacking_count": 1}])
    assert update_clan_damage_state(state, status) == ["4\u738b\u5f53\u524d\u67091\u4eba\u51fa\u5200"]
    assert update_clan_damage_state(state, status) == []
    assert state["last_damage_history_id"] == 10


def test_damage_notice_exact_game_name_format_and_deduplication():
    state = {}
    update_clan_damage_state(state, _snapshot(_hit(9)))
    item = _hit("10", name="\u65e7\u540d", damage=318455848)
    status = _snapshot(item, copy.deepcopy(item), members=[{"viewer_id": 1, "name": "\u91cd\u534e"}])
    assert update_clan_damage_state(state, status) == ["\u91cd\u534e\u5bf932\u5468\u76ee4\u738b\u9020\u6210\u4e86318455848\u70b9\u4f24\u5bb3\u3002"]
    assert update_clan_damage_state(state, status) == []


def test_period_change_baselines_new_history_and_excludes_old_period_records():
    state = {}
    update_clan_damage_state(state, _snapshot(_hit(100, period=1)))
    assert update_clan_damage_state(state, _snapshot(_hit(1, period=2), _hit(101, period=1), period=2)) == []
    assert state["last_damage_history_id"] == 1
    assert len(update_clan_damage_state(state, _snapshot(_hit(2, period=2), period=2))) == 1
    assert update_clan_damage_state(state, _snapshot(_hit(2, period=2), period=2)) == []


def test_battle_change_and_numeric_id_rollback_rebaseline():
    state = {}
    update_clan_damage_state(state, _snapshot(_hit(100)))
    next_battle = _snapshot(_hit(1))
    next_battle["clan_battle"]["id"] = 124
    assert update_clan_damage_state(state, next_battle) == []
    next_battle["damage_history"] = [_hit(2)]
    assert len(update_clan_damage_state(state, next_battle)) == 1
    next_battle["damage_history"] = [_hit(0)]
    assert update_clan_damage_state(state, next_battle) == []
    next_battle["damage_history"] = [_hit(1)]
    assert len(update_clan_damage_state(state, next_battle)) == 1


def test_empty_first_poll_then_new_hit_and_empty_page_preserves_cursor():
    state = {}
    assert update_clan_damage_state(state, _snapshot()) == []
    assert len(update_clan_damage_state(state, _snapshot(_hit(1)))) == 1
    assert update_clan_damage_state(state, _snapshot()) == []
    assert state["last_damage_history_id"] == 1
    assert len(update_clan_damage_state(state, _snapshot(_hit(2)))) == 1


def test_no_history_field_does_not_initialize_cursor():
    state = {}
    assert update_clan_damage_state(state, {"boss_info": []}) == []
    assert not state.get("damage_history_initialized")
    assert update_clan_damage_state(state, _snapshot(_hit(100))) == []


def test_active_count_ignores_historical_attack_count_and_unknown_count():
    state = {}
    status = _snapshot(boss_info=[{"order_num": 4, "attack_count": 99, "challenge_count": 50, "battle_count": 30}])
    assert update_clan_damage_state(state, status) == []
    assert state["boss_active_counts"] == {}
    status["boss_info"] = [{"order_num": 4, "fighter_num": 1}]
    assert update_clan_damage_state(state, status) == ["4\u738b\u5f53\u524d\u67091\u4eba\u51fa\u5200"]
    status["boss_info"] = [{"order_num": 4, "attacking_count": "unknown"}]
    assert update_clan_damage_state(state, status) == []
    status["boss_info"] = [{"order_num": 4, "attacking_count": 1}]
    assert update_clan_damage_state(state, status) == []
    status["boss_info"] = [{"order_num": 4, "attacking_count": 0}]
    assert update_clan_damage_state(state, status) == []
    status["boss_info"] = [{"order_num": 4, "attacking_count": 1}]
    assert update_clan_damage_state(state, status) == ["4\u738b\u5f53\u524d\u67091\u4eba\u51fa\u5200"]


@pytest.mark.parametrize("payload", [None, [], {"damage_history": None}, {"damage_history": [None, {}, {"history_id": "bad"}, {"history_id": "1.5"}]}])
def test_monitor_tolerates_malformed_payloads(payload):
    assert update_clan_damage_state({}, payload) == []


def test_status_has_all_five_bosses_actual_hp_lock_phase_and_game_name():
    status = synthetic_preview_status()
    rows = build_clan_status_rows(status)
    assert len(rows) == 5
    assert rows[0]["hp_percent"] == "53.00%"
    assert rows[1]["can_challenge"] is False
    text = build_clan_command_reply("status", {"out_damage_monitor": True},
                                    {"nickname": "\u672c\u5730\u5907\u6ce8"}, real_status=status)
    assert "\u76d1\u63a7\u73a9\u5bb6\uff1a\u5408\u6210\u76d1\u63a7\u73a9\u5bb6\uff08\u975e\u771f\u5b9e\uff09" in text
    assert "\u516c\u4f1a\u6392\u540d\uff1a321" in text
    assert "\u9636\u6bb5\uff1a4" in text
    assert "\u9636\u6bb5\uff1a2" not in text
    assert "\u4f1a\u6218\u671f\u6b21\uff1a2" in text
    assert "\u6700\u5927\u8840\u91cf 650,000,000" in text
    assert "\u65e0\u6cd5\u6311\u6218" in text
    for order in range(1, 6):
        assert f"{order}\u738b | 32\u5468\u76ee | 4\u9636\u6bb5" in text


def test_period_is_never_a_phase_and_missing_bosses_are_unknown():
    status = _snapshot(period=99, boss_info=[{"order_num": 1, "lap_num": 7, "current_hp": 10}])
    text = build_clan_status_text(status)
    assert "\u9636\u6bb5\uff1a\u672a\u77e5" in text
    assert "\u4f1a\u6218\u671f\u6b21\uff1a99" in text
    assert "\u6700\u5927\u8840\u91cf \u672a\u77e5" in text
    assert "\u6bd4\u4f8b \u672a\u77e5" in text
    assert "5\u738b | \u5468\u76ee\u672a\u77e5 | \u9636\u6bb5\u672a\u77e5 | \u6311\u6218\u72b6\u6001\u672a\u77e5" in text
    assert build_clan_status_rows(status)[4]["attacking_count"] is None


def test_mixed_boss_phases_are_shown_individually_not_assumed_global():
    status = _snapshot(boss_info=[{"order_num": 1, "phase": 3}, {"order_num": 2, "phase": 4}])
    text = build_clan_status_text(status)
    assert "\u5404\u738b\u9636\u6bb5\u4e0d\u540c" in text
    assert "1\u738b | \u5468\u76ee\u672a\u77e5 | 3\u9636\u6bb5" in text
    assert "2\u738b | \u5468\u76ee\u672a\u77e5 | 4\u9636\u6bb5" in text


def test_font_supports_requested_linux_zenhei_path():
    class FontProbe:
        def __init__(self):
            self.attempted = []

        def truetype(self, path, size):
            self.attempted.append(path)
            if path == "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc":
                return "font"
            raise OSError(path)

    probe = FontProbe()
    assert _load_font(probe, 24) == "font"
    assert probe.attempted[-1].endswith("wqy-zenhei.ttc")


def test_wrap_measures_chinese_and_long_unbroken_names():
    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    font = _load_font(ImageFont, 24)
    text = "\u8d85\u957f\u6e38\u620f\u540d" * 15 + "LongName" * 10
    lines = _wrap_text(draw, text, font, 216)
    assert len(lines) > 2
    assert "".join(lines) == text
    assert all(draw.textlength(line, font=font) <= 216 for line in lines)


def test_structured_report_image_white_bounded_nonblank_and_damage_bars(tmp_path):
    status = synthetic_preview_status()
    before = copy.deepcopy(status)
    path = render_clan_report(status, tmp_path / "nested" / "synthetic-report.png")
    assert isinstance(path, Path) and path.is_file()
    with Image.open(path) as image:
        assert image.width == 1280
        assert image.getpixel((0, image.height - 1)) == (255, 255, 255)
        colors = dict((color, count) for count, color in image.getcolors(image.width * image.height))
        assert colors[(37, 140, 106)] > 100  # Real damage-share bars.
        assert colors[(255, 255, 255)] > image.width * image.height / 2
        # Both outer margins remain white below the top accent.
        assert image.crop((0, 200, 20, image.height)).getextrema() == ((255, 255),) * 3
        assert image.crop((1260, 200, 1280, image.height)).getextrema() == ((255, 255),) * 3
    assert status == before


@pytest.mark.parametrize("command", ["current_report", "today_report", "yesterday_report", "my_report", "damage_detail", "today_damage", "yesterday_damage"])
def test_all_report_commands_render_without_data_invention(tmp_path, command):
    path = render_clan_report({}, tmp_path / f"{command}.png", command)
    with Image.open(path) as image:
        assert image.width == 1280
        assert image.height > 300


def test_text_and_status_images_wrap_without_widening(tmp_path):
    normal = render_text_image("\u77ed\u6587\u672c", tmp_path / "normal.png")
    long = render_text_image("\u4e2d\u6587\u957f\u540d\u5b57" * 100, tmp_path / "long.png", title="\u5408\u6210\u9884\u89c8")
    status = render_clan_status(synthetic_preview_status(), tmp_path / "status.png")
    with Image.open(normal) as a, Image.open(long) as b, Image.open(status) as c:
        assert a.width == b.width == c.width == 1280
        assert b.height > a.height
        assert c.height > 600


def test_unsupported_report_command_is_explicit(tmp_path):
    with pytest.raises(ValueError, match="Unsupported"):
        render_clan_report({}, tmp_path / "unsupported.png", "not_a_report")


def test_real_damage_history_schema_never_infers_score_or_compensation():
    status = {
        "clan": {"members": [
            {"viewer_id": 1, "name": "\u540c\u540d"},
            {"viewer_id": 2, "name": "\u540c\u540d"},
            {"viewer_id": 3, "name": "\u96f6\u5200"},
        ]},
        "damage_history": [
            {"viewer_id": viewer, "name": "\u540c\u540d", "damage": damage,
             "kill": kill, "create_time": 1792555200, "history_id": index,
             "lap_num": 32, "order_num": 4}
            for index, viewer, damage, kill in ((1, 1, 318455848, 1), (2, 1, 100, 0), (3, 2, 200, 1))
        ],
        "history_scope": "\u6e38\u620f\u6700\u8fd1\u8bb0\u5f55\uff1b\u6301\u7eed\u76d1\u63a7\u540e\u7d2f\u79ef",
    }
    rows = {row["viewer_id"]: row for row in build_current_report_rows(status)}
    assert len(rows) == 3
    assert rows["1"]["hits"] == 2
    assert rows["2"]["hits"] == 1
    assert rows["3"]["hits"] == 0
    assert rows["1"]["damage"] == 318455948
    assert all(row["score"] == row["score_percent"] == "-" for row in rows.values())
    assert status["history_scope"] in build_current_report_text(status)
    assert status["history_scope"] in build_damage_count_summary(status)


def test_my_report_does_not_reuse_clan_history_scope():
    status = _snapshot(_hit(1), history_scope="clan-only-scope")
    prepared = prepare_clan_report(status, "my_report", {
        "actual_logs": [{"mylog_id": 2, "total_damage": 456}],
        "history_scope": "personal-only-scope",
    })
    assert prepared["history_scope"] == "personal-only-scope"
    assert "clan-only-scope" not in build_current_report_text(prepared)
    assert status["history_scope"] == "clan-only-scope"


def test_status_never_substitutes_local_nickname_or_battle_period_for_game_fields():
    status = _snapshot(period=99, account={"nickname": "local-real-label"})
    status["clan_battle"]["phase"] = 77
    text = build_clan_status_text(status, account={"nickname": "local-bound-label"})
    assert "local-real-label" not in text and "local-bound-label" not in text
    assert "\u76d1\u63a7\u73a9\u5bb6\uff1a\u672a\u77e5\u73a9\u5bb6" in text
    assert "\u9636\u6bb5\uff1a\u672a\u77e5" in text
    assert "\u9636\u6bb5\uff1a77" not in text


def test_status_finds_monitor_game_name_by_viewer_id_in_nested_roster():
    status = _snapshot(account={"viewer_id": 2})
    status["clan"]["members"] = [
        {"viewer_id": 1, "name": "\u5176\u4ed6\u4eba"},
        {"viewer_id": "2", "name": "\u6e38\u620f\u540d"},
    ]
    assert "\u76d1\u63a7\u73a9\u5bb6\uff1a\u6e38\u620f\u540d" in build_clan_status_text(status)


def test_status_never_guesses_challenge_lock_from_hp_or_lap():
    status = _snapshot(boss_info=[
        {"order_num": 1, "current_hp": 0, "max_hp": 100, "lap_num": 2},
        {"order_num": 2, "current_hp": 100, "max_hp": 100, "lap_num": 1},
        {"order_num": 3, "is_locked": 1, "phase": 4},
    ])
    rows = build_clan_status_rows(status)
    assert rows[0]["can_challenge"] is None
    assert rows[1]["can_challenge"] is None
    assert rows[2]["can_challenge"] is False
    assert rows[0]["hp_percent"] == "0.00%"


def test_battle_change_drops_previous_period_scope_and_resets_live_counts():
    state = {}
    update_clan_damage_state(state, _snapshot(_hit(99), boss_info=[{"order_num": 4, "fighter_num": 1}]))
    changed = _snapshot(_hit(1), boss_info=[{"order_num": 4, "fighter_num": 1}])
    changed["clan_battle"] = {"id": 124}
    assert update_clan_damage_state(state, changed) == ["4\u738b\u5f53\u524d\u67091\u4eba\u51fa\u5200"]
    assert state["damage_history_scope"] == {"clan_id": "42", "clan_battle_id": "124"}
    assert state["last_damage_history_id"] == 1


def test_legacy_cursor_without_battle_scope_rebaselines_instead_of_replaying():
    state = {"last_damage_history_id": 1}
    assert update_clan_damage_state(state, _snapshot(_hit(100))) == []
    assert state["last_damage_history_id"] == 100
    assert len(update_clan_damage_state(state, _snapshot(_hit(101)))) == 1


@pytest.mark.parametrize("renderer", [render_clan_report, render_clan_status])
def test_renderers_wrap_long_metadata_and_keep_all_text_inside_image(tmp_path, monkeypatch, renderer):
    status = synthetic_preview_status()
    status["clan"]["clan_name"] = "\u533f\u540d\u957f\u516c\u4f1a\u540d" * 20
    status["history_scope"] = "\u5df2\u91c7\u96c6\u7684\u533f\u540d\u8bb0\u5f55" * 20
    status["account"]["user_name"] = "\u533f\u540d\u957f\u6e38\u620f\u540d" * 20
    boxes = []
    drawn_text = []
    original = ImageDraw.ImageDraw.text

    def record(draw, xy, text, *args, **kwargs):
        boxes.append(draw.textbbox(xy, text, font=kwargs.get("font"), anchor=kwargs.get("anchor")))
        drawn_text.append((str(text), xy))
        return original(draw, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", record)
    path = renderer(status, path=tmp_path / f"{renderer.__name__}.png")
    with Image.open(path) as image:
        assert all(0 <= left <= right <= image.width and 0 <= top <= bottom <= image.height
                   for left, top, right, bottom in boxes)
        assert image.width == 1280
    if renderer is render_clan_report:
        scope_y = min(xy[1] for text, xy in drawn_text if text.startswith("\u7edf\u8ba1\u8303\u56f4"))
        totals_y = next(xy[1] for text, xy in drawn_text if text == "\u5df2\u77e5\u5206\u6570")
        assert scope_y < totals_y
    else:
        assert all(f"{order}\u738b" in [text for text, _ in drawn_text] for order in range(1, 6))


def test_status_image_has_real_hp_bar_and_explicit_locked_row(tmp_path):
    path = render_clan_status(synthetic_preview_status(), tmp_path / "status.png")
    with Image.open(path) as image:
        colors = {color: count for count, color in image.getcolors(image.width * image.height)}
        assert colors[(37, 140, 106)] > 1000
        assert colors[(179, 75, 67)] > 100
        assert colors[(255, 255, 255)] > image.width * image.height / 2


def test_selected_archive_is_not_filtered_again_by_live_period():
    status = _snapshot(_hit(1, period=1), _hit(2, period=2), period=2)
    status['report_command'] = 'current_report'
    rows = build_current_report_rows(status)
    assert sum(row['records'] for row in rows) == 2

