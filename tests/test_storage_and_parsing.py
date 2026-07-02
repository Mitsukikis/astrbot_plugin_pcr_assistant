import json
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storage import PCRStorage, mask_value, parse_bind_payload
from autopcr_client import AutoPCRClient
from arena_client import ArenaClient
from arena_ranking import format_arena_ranking, parse_arena_ranking_command
from arena_solution import (
    PcrdFansMissingKey,
    build_solution_payload,
    format_arena_solution_text,
    parse_solution_command,
)
from command_router import match_plain_command
from auth import is_admin_qq, numeric_sender_id_from_event, parse_qq_list
from clan_access import clan_command_account_qq
from clan_report import build_current_report_text, build_damage_count_summary
from clan_state import build_clan_command_reply
from monitoring import update_clan_damage_state
from pcr_image_recognizer import PcrImageRecognizer
from pcr_chara import name_for_id, parse_team_names
from real_api_client import PCRRealAPIClient


CHANNEL_CN = "\u6e20\u9053\u670d"
BILI_CN_LOWER = "b\u670d"
BILI_CN_UPPER = "B\u670d"


def test_unicode_alias_constants_are_correct():
    assert CHANNEL_CN.encode("unicode_escape").decode("ascii") == "\\u6e20\\u9053\\u670d"
    assert BILI_CN_LOWER.encode("unicode_escape").decode("ascii") == "b\\u670d"
    assert BILI_CN_UPPER.encode("unicode_escape").decode("ascii") == "B\\u670d"


def test_autopcr_urls():
    client = AutoPCRClient("http://127.0.0.1:18080/daily", "http://example.com/daily/login")
    assert client.login_url == "http://example.com/daily/login"
    assert client.health_url == "http://127.0.0.1:18080/daily/login"


def test_match_plain_command_handles_bare_and_slash_prefixed_text():
    commands = ["pcr\u5e2e\u52a9", "\u6e05\u65e5\u5e38"]

    assert match_plain_command("pcr\u5e2e\u52a9", commands) == "pcr\u5e2e\u52a9"
    assert match_plain_command("/\u6e05\u65e5\u5e38", commands) is None
    assert match_plain_command("pcr\u5e2e\u52a9 extra", commands) == "pcr\u5e2e\u52a9"
    assert match_plain_command("pcr\u5e2e\u52a9\u4e00\u4e0b", commands) is None


def test_parse_qq_list_accepts_common_separators_and_ignores_names():
    value = "123456789, 10001\uff1b\u6d4b\u8bd5\u73a9\u5bb6\n20002"

    assert parse_qq_list(value) == {"123456789", "10001", "20002"}


def test_sender_id_prefers_numeric_qq_over_group_card_or_nickname():
    class Sender:
        user_id = "10001"
        nickname = "\u795e\u79d8\u5609\u5bbe"
        card = "123456789"

    class Message:
        sender = Sender()
        user_id = "10001"

    class Event:
        message_obj = Message()

        def get_sender_id(self):
            return "\u795e\u79d8\u5609\u5bbe"

    assert numeric_sender_id_from_event(Event()) == "10001"
    assert is_admin_qq("10001", {"123456789"}) is False
    assert is_admin_qq("123456789", {"123456789"}) is True


def test_blocked_qq_overrides_admin_list():
    assert is_admin_qq("123456789", {"123456789"}, {"123456789"}) is False


def test_clan_command_uses_sender_qq_not_existing_monitor_qq():
    clan_state = {"monitor_qq": "123456789"}

    assert clan_command_account_qq("10001", clan_state) == "10001"


def test_real_api_client_can_target_user_and_account_alias():
    client = PCRRealAPIClient("http://127.0.0.1:18081/")

    url = client._url("clan/status", {"user": "10001", "account": "main"})

    assert url == "http://127.0.0.1:18081/clan/status?user=10001&account=main"


def test_real_api_methods_pass_user_and_account_alias():
    class RecordingClient(PCRRealAPIClient):
        async def get_json(self, path, params=None):
            self.path = path
            self.params = params
            return {"ok": True}

    client = RecordingClient("http://127.0.0.1:18081/")

    asyncio.run(client.clan_status("10001", account="main"))

    assert client.path == "clan/status"
    assert client.params == {"user": "10001", "account": "main"}


def test_real_api_arena_ranking_passes_kind_page_user_and_account_alias():
    class RecordingClient(PCRRealAPIClient):
        async def get_json(self, path, params=None):
            self.path = path
            self.params = params
            return {"ok": True}

    client = RecordingClient("http://127.0.0.1:18081/")

    asyncio.run(client.arena_ranking("pjjc", page=2, user="10001", account="main"))

    assert client.path == "arena/ranking"
    assert client.params == {
        "kind": "pjjc",
        "page": 2,
        "limit": 20,
        "user": "10001",
        "account": "main",
    }


def test_real_api_upsert_account_posts_bound_account_payload():
    class RecordingClient(PCRRealAPIClient):
        async def post_json(self, path, payload=None):
            self.path = path
            self.payload = payload
            return {"ok": True}

    client = RecordingClient("http://127.0.0.1:18081/")

    asyncio.run(client.upsert_account("10001", {"kind": "channel", "uid": "u1", "secret": "s1"}))

    assert client.path == "account/upsert"
    assert client.payload == {
        "user": "10001",
        "account": "main",
        "kind": "channel",
        "uid": "u1",
        "secret": "s1",
    }


def test_arena_query_can_target_sender_real_api_user():
    class RecordingAPI:
        async def profile(self, uid, user=None, account=None):
            self.uid = uid
            self.user = user
            self.account = account
            return {
                "account": {},
                "profile": {
                    "user_name": "\u5343\u6b4c",
                    "arena_rank": 1,
                    "grand_arena_rank": 2,
                },
            }

    api = RecordingAPI()
    client = ArenaClient(api, default_user="123456789")

    asyncio.run(client.query("1257970475520", "\u5343\u6b4c", user="10001", account="main"))

    assert api.uid == "1257970475520"
    assert api.user == "10001"
    assert api.account == "main"


def test_arena_client_formats_current_ranking_page():
    class RecordingAPI:
        async def arena_ranking(self, kind="jjc", page=1, limit=20, user=None, account=None):
            self.kind = kind
            self.page = page
            self.limit = limit
            self.user = user
            self.account = account
            return {
                "kind": kind,
                "page": page,
                "limit": limit,
                "arena": {"group": 15, "rank": 5},
                "ranking": [
                    {"rank": 21, "user_name": "\u661f\u5b87\u591c", "viewer_id": 1146063659575},
                    {"rank": 22, "user_name": "\u4e91\u5361\u6cd5\u4f0a", "viewer_id": 1278742520300},
                ],
            }

    api = RecordingAPI()
    client = ArenaClient(api, default_user="123456789")

    text = asyncio.run(client.ranking_text("jjc", page=2, user="10001", account="main"))

    assert api.kind == "jjc"
    assert api.page == 2
    assert api.user == "10001"
    assert api.account == "main"
    assert "\u5f53\u524d\u4e3a\u7ade\u6280\u573a15\u53f7\u573a\uff0821-40\uff09" in text
    assert "21: \u661f\u5b87\u591c (1146063659575)" in text


def test_parse_arena_ranking_commands_and_format_payload():
    assert parse_arena_ranking_command("\u7ade\u6280\u573a\u6392\u884c\u699c1") == ("jjc", 1)
    assert parse_arena_ranking_command("\u516c\u4e3b\u7ade\u6280\u573a\u6392\u884c\u699c2") == ("pjjc", 2)
    assert parse_arena_ranking_command("\u7ade\u6280\u573a\u6392\u884c\u699c0") is None

    text = format_arena_ranking({
        "kind": "pjjc",
        "page": 2,
        "limit": 20,
        "arena": {"group": 3},
        "ranking": [{"rank": 21, "user_name": "\u4f51\u6811", "viewer_id": 10001}],
    })

    assert text.splitlines() == [
        "\u5f53\u524d\u4e3a\u516c\u4e3b\u7ade\u6280\u573a3\u53f7\u573a\uff0821-40\uff09",
        "21: \u4f51\u6811 (10001)",
    ]


def test_parse_arena_solution_commands_with_region_prefixes():
    assert parse_solution_command("\u600e\u4e48\u62c6 \u5bab\u5b50 \u601c") == (1, "\u5bab\u5b50 \u601c")
    assert parse_solution_command("b\u600e\u4e48\u62c6 \u5bab\u5b50") == (2, "\u5bab\u5b50")
    assert parse_solution_command("B\u600e\u4e48\u89e3 \u5bab\u5b50") == (2, "\u5bab\u5b50")
    assert parse_solution_command("\u53f0\u600e\u4e48\u6253 \u5bab\u5b50") == (3, "\u5bab\u5b50")
    assert parse_solution_command("\u65e5jjc\u67e5\u8be2 \u5bab\u5b50") == (4, "\u5bab\u5b50")
    assert parse_solution_command("\u7ade\u6280\u573a\u6392\u884c\u699c1") is None


def test_parse_pcr_team_names_resolves_common_aliases():
    team, unknown = parse_team_names("\u5bab\u5b50 \u601c(\u65b0\u5e74) \u7231\u871c\u8389\u96c5 \u971e(\u9b54\u6cd5\u5c11\u5973) \u4f3c\u4f3c\u82b1")

    assert team == [1007, 1089, 1099, 1122, 1070]
    assert unknown == ""
    assert name_for_id(1089) == "\u601c(\u65b0\u5e74)"


def test_pcrdfans_payload_uses_unit_ids_and_region():
    payload = build_solution_payload([1007, 1089, 1099, 1122, 1070], region=2, now=123456)

    assert payload == {
        "_sign": "a",
        "def": [100701, 108901, 109901, 112201, 107001],
        "nonce": "a",
        "page": 1,
        "sort": 1,
        "ts": 123456,
        "region": 2,
    }


def test_format_arena_solution_text_uses_defense_and_solution_rows():
    text = format_arena_solution_text(
        defender_ids=[1007, 1089, 1099, 1122, 1070],
        entries=[
            {
                "qkey": "ABCDE",
                "up": 178,
                "down": 19,
                "atk": [
                    {"id": 100701, "star": 6, "equip": 1},
                    {"id": 100301, "star": 6, "equip": 1},
                    {"id": 101001, "star": 6, "equip": 1},
                    {"id": 102901, "star": 6, "equip": 1},
                    {"id": 107001, "star": 5, "equip": 1},
                ],
            }
        ],
        region=1,
    )

    assert "\u9632\u5b88\u65b9 [\u5bab\u5b50 \u601c(\u65b0\u5e74) \u7231\u871c\u8389\u96c5 \u971e(\u9b54\u6cd5\u5c11\u5973) \u4f3c\u4f3c\u82b1]" in text
    assert "ABCDE 178/19" in text
    assert "\u5bab\u5b50 \u601c \u771f\u6b65" in text
    assert 'b\u600e\u4e48\u62c6' in text


def test_missing_pcrdfans_key_is_explicit():
    assert str(PcrdFansMissingKey()) == "\u672a\u914d\u7f6e pcrdfans_api_key\uff0c\u8bf7\u5148\u5728\u63d2\u4ef6\u914d\u7f6e\u91cc\u586b\u5165 pcrdfans Bot API Key\u3002"


def test_image_recognizer_splits_horizontal_five_icon_team(tmp_path):
    from PIL import Image, ImageDraw

    colors = {
        1001: (230, 40, 60),
        1002: (40, 200, 90),
        1003: (60, 120, 230),
        1004: (230, 210, 50),
        1005: (190, 70, 220),
    }
    templates = {
        chara_id: Image.new("RGB", (64, 64), color)
        for chara_id, color in colors.items()
    }
    row = Image.new("RGB", (5 * 74 + 24, 94), (245, 245, 245))
    draw = ImageDraw.Draw(row)
    x = 12
    for chara_id in colors:
        draw.rectangle((x - 3, 7, x + 66, 76), outline=(255, 0, 0), width=3)
        row.paste(templates[chara_id], (x, 10))
        x += 74
    path = tmp_path / "team.png"
    row.save(path)

    recognizer = PcrImageRecognizer(templates=templates)

    assert recognizer.recognize_file(path) == [1001, 1002, 1003, 1004, 1005]


def test_config_schema_descriptions_are_chinese():
    schema = json.loads((Path(__file__).resolve().parents[1] / "_conf_schema.json").read_text(encoding="utf-8"))

    assert schema["autopcr_base_url"]["description"].startswith("AutoPCR 本机地址")
    assert schema["blocked_qqs"]["description"].startswith("\u9ed1\u540d\u5355 QQ")
    assert schema["pcrdfans_api_key"]["description"].startswith("pcrdfans Bot API Key")


def test_out_damage_monitor_reply_matches_standard_start_format():
    reply = build_clan_command_reply(
        "out_damage_monitor_on",
        {"out_damage_monitor": True, "monitor_qq": "10001", "monitor_id": "HN00023"},
        {"kind": "channel", "uid": "1234567890123456789012", "nickname": "\u6d4b\u8bd5\u73a9\u5bb6"},
        real_status={"account": {"uid": "1234567890123456789012"}},
    )

    assert "\u6b63\u5728\u767b\u5f55\u8d26\u53f7\uff0c\u8bf7\u8010\u5fc3\u7b49\u5f85" in reply
    assert "\u5f53\u524d\u76d1\u63a7\u73a9\u5bb6\u4e3a\u6d4b\u8bd5\u73a9\u5bb6" in reply
    assert "\u5f00\u59cb\u76d1\u63a7\u4e2d, \u53ef\u4ee5\u53d1\u9001\u3010\u53d6\u6d88\u51fa\u5200\u76d1\u63a7\u3011\u6216\u8005\u9876\u53f7\u9000\u51fa" in reply
    assert "#\u76d1\u63a7\u7f16\u53f7HN00023" in reply
    assert "\u540e\u7aef\u6b63\u5728\u63a5\u5165" not in reply


def test_damage_count_summary_uses_roster_and_reports_zero_hit_members():
    real_status = {
        "members": [
            {"name": "\u5343\u6b4c"},
            {"name": "\u4f51\u6811"},
            {"name": "\u53ef\u53ef\u841d"},
        ],
        "damage_history": [
            {"name": "\u5343\u6b4c", "damage": 100},
            {"name": "\u5343\u6b4c", "damage": 200},
            {"name": "\u5343\u6b4c", "damage": 300},
            {"name": "\u4f51\u6811", "damage": 400},
            {"name": "\u4f51\u6811", "damage": 500},
        ],
    }

    summary = build_damage_count_summary(real_status)

    assert "\u603b\u8ba1\u51fa\u5200: 5" in summary
    assert "\u4ee5\u4e0b\u662f\u51fa\u4e863\u5200\u7684\u6210\u5458: \u5343\u6b4c" in summary
    assert "\u4ee5\u4e0b\u662f\u51fa\u4e862\u5200\u7684\u6210\u5458: \u4f51\u6811" in summary
    assert "\u4ee5\u4e0b\u662f\u51fa\u4e860\u5200\u7684\u6210\u5458: \u53ef\u53ef\u841d" in summary


def test_current_report_text_aggregates_real_damage_without_fake_score():
    text = build_current_report_text({
        "damage_history": [
            {"name": "\u5343\u6b4c", "damage": 300, "score": 900},
            {"name": "\u4f51\u6811", "damage": 100},
            {"name": "\u5343\u6b4c", "damage": 200, "score": 600},
        ],
    })

    assert "\u6392\u540d | \u6635\u79f0 | \u51fa\u5200\u6b21\u6570 | \u9020\u6210\u4f24\u5bb3 | \u5206\u6570 | \u4f24\u5bb3\u5360\u6bd4 | \u5206\u6570\u5360\u6bd4" in text
    assert "1 | \u5343\u6b4c | 2 | 500 | 1500 | 83.33% | 100.00%" in text
    assert "2 | \u4f51\u6811 | 1 | 100 | - | 16.67% | -" in text


def test_clan_monitor_reports_active_boss_challenge_count_changes():
    clan_state = {"boss_active_counts": {"1": 0}}
    real_status = {
        "boss_info": [
            {"order_num": 1, "attacking_user_list": [{"viewer_id": 1}, {"viewer_id": 2}]},
        ],
        "damage_history": [],
    }

    messages = update_clan_damage_state(clan_state, real_status)

    assert messages == ["1\u738b\u5f53\u524d\u67092\u4eba\u51fa\u5200"]
    assert clan_state["boss_active_counts"] == {"1": 2}


def test_mask_value_keeps_edges():
    assert mask_value("1234567890123456789012") == "1234***************9012"
    assert mask_value("1234567") == "123****"


def test_parse_channel_bind_payload():
    text = f'{CHANNEL_CN} 1234567890123456789012 <string name="x">secret</string>'
    parsed = parse_bind_payload(text)
    assert parsed["kind"] == "channel"
    assert parsed["uid"] == "1234567890123456789012"
    assert parsed["secret"] == '<string name="x">secret</string>'


def test_parse_bili_bind_payload():
    parsed = parse_bind_payload(f"{BILI_CN_LOWER} 1234567890123 abc_access_key")
    assert parsed == {
        "kind": "bili",
        "uid": "1234567890123",
        "secret": "abc_access_key",
    }


@pytest.mark.parametrize(
    ("alias", "kind"),
    [
        (CHANNEL_CN, "channel"),
        ("channel", "channel"),
        (BILI_CN_LOWER, "bili"),
        (BILI_CN_UPPER, "bili"),
        ("bili", "bili"),
        ("bilibili", "bili"),
    ],
)
def test_parse_all_required_aliases(alias, kind):
    parsed = parse_bind_payload(f"{alias} 1234567890123 secret tail")
    assert parsed == {"kind": kind, "uid": "1234567890123", "secret": "secret tail"}


def test_storage_round_trip(tmp_path: Path):
    path = tmp_path / "state.json"
    store = PCRStorage(path)
    store.set_account("10001", {"kind": "channel", "uid": "1234567890123456789012", "secret": "hidden"})
    store.bind_arena_uid("10001", "1234567890123", "main")
    store.set_group("group-origin", {"arena_push": True, "clan_monitor": False})
    reloaded = PCRStorage(path)
    assert reloaded.get_account("10001")["uid"] == "1234567890123456789012"
    assert reloaded.data["arena"]["10001"][0]["nickname"] == "main"
    assert reloaded.data["groups"]["group-origin"]["arena_push"] is True


def test_storage_merges_defaults_from_partial_file(tmp_path: Path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"accounts": {"10001": {"uid": "u1"}}}), encoding="utf-8")

    store = PCRStorage(path)

    assert store.data["accounts"]["10001"]["uid"] == "u1"
    assert store.data["arena"] == {}
    assert store.data["groups"] == {}
    assert store.data["clan"] == {}


def test_remove_account_persists_removal(tmp_path: Path):
    path = tmp_path / "state.json"
    store = PCRStorage(path)
    account = {"kind": "bili", "uid": "1234567890123", "secret": "hidden"}
    store.set_account("10001", account)

    assert store.remove_account("10001") == {"kind": "bili", "uid": "1234567890123"}
    assert store.get_account("10001") is None
    assert PCRStorage(path).get_account("10001") is None


def test_bind_arena_uid_replaces_duplicate_uid(tmp_path: Path):
    path = tmp_path / "state.json"
    store = PCRStorage(path)

    store.bind_arena_uid("10001", "1234567890123", "old")
    store.bind_arena_uid("10001", "1234567890123", "new")

    assert store.data["arena"]["10001"][0]["uid"] == "1234567890123"
    assert store.data["arena"]["10001"][0]["nickname"] == "new"
    assert PCRStorage(path).data["arena"]["10001"][0]["uid"] == "1234567890123"
    assert PCRStorage(path).data["arena"]["10001"][0]["nickname"] == "new"


def test_bind_arena_uid_keeps_max_8(tmp_path: Path):
    path = tmp_path / "state.json"
    store = PCRStorage(path)

    for index in range(10):
        store.bind_arena_uid("10001", f"uid-{index}", f"name-{index}")

    bindings = store.data["arena"]["10001"]
    assert len(bindings) == 8
    assert bindings[0]["uid"] == "uid-9"
    assert bindings[0]["nickname"] == "name-9"
    assert bindings[-1]["uid"] == "uid-2"
    assert bindings[-1]["nickname"] == "name-2"


def test_set_group_merges_existing_settings(tmp_path: Path):
    path = tmp_path / "state.json"
    store = PCRStorage(path)

    store.set_group("group-origin", {"arena_push": True})
    store.set_group("group-origin", {"clan_monitor": False})

    assert store.data["groups"]["group-origin"] == {
        "arena_push": True,
        "clan_monitor": False,
    }
    assert PCRStorage(path).data["groups"]["group-origin"] == {
        "arena_push": True,
        "clan_monitor": False,
    }

