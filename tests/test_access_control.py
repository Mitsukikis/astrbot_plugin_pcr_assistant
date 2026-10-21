import asyncio
import importlib.util
import inspect
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from auth import is_allowed_qq
from storage import PCRStorage


OWNER = "3555982933"
OTHER = "10001"
GROUP = "12345"
SESSION = f"qq:GroupMessage:{GROUP}"


@pytest.fixture
def plugin_module(monkeypatch):
    def command(*args, **kwargs):
        def decorate(handler):
            handler.test_registered_command = True
            return handler
        return decorate

    fake_filter = types.SimpleNamespace(
        command=command,
        event_message_type=lambda *args: lambda handler: handler,
        EventMessageType=types.SimpleNamespace(ALL="all"),
    )
    module_attrs = {
        "astrbot": {},
        "astrbot.api": {"AstrBotConfig": dict, "logger": Mock()},
        "astrbot.api.event": {"AstrMessageEvent": object, "filter": fake_filter},
        "astrbot.api.star": {
            "Context": object, "Star": type("Star", (), {}),
            "register": lambda *args: lambda cls: cls,
        },
        "astrbot.core": {},
        "astrbot.core.message": {},
        "astrbot.core.message.message_event_result": {"MessageChain": Mock},
    }
    for name, attrs in module_attrs.items():
        module = types.ModuleType(name)
        module.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, module)

    root = Path(__file__).resolve().parents[1]
    name = "pcr_access_test_plugin"
    spec = importlib.util.spec_from_file_location(
        name, root / "main.py", submodule_search_locations=[str(root)]
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    yield module
    for key in list(sys.modules):
        if key.startswith(name + "."):
            del sys.modules[key]


@pytest.fixture
def plugin(plugin_module, tmp_path):
    instance = object.__new__(plugin_module.PCRAssistantPlugin)
    instance.config = {"allowed_qqs": ""}
    instance.admin_qq = OWNER
    instance.admin_qqs = {OWNER}
    instance.blocked_qqs = set()
    instance.storage = PCRStorage(tmp_path / "state.json")
    instance.storage.set_group_enabled(GROUP, True)
    instance.autopcr = types.SimpleNamespace(
        health_text=AsyncMock(return_value="online"),
        login_url="https://example.com/daily/login",
    )
    instance.arena = types.SimpleNamespace(query=AsyncMock())
    instance.real_api = types.SimpleNamespace(clan_status=AsyncMock(return_value={'ok': True, 'damage_history': []}))
    instance.context = types.SimpleNamespace(send_message=AsyncMock())
    return instance


def event(sender=OWNER, text="", group=GROUP):
    return types.SimpleNamespace(
        message_obj=types.SimpleNamespace(
            group_id=group,
            sender=types.SimpleNamespace(user_id=sender, nickname=OWNER, card=OWNER),
        ),
        get_sender_id=lambda: sender,
        message_str=text,
        unified_msg_origin=SESSION if group else f"qq:FriendMessage:{sender}",
        plain_result=lambda text: text,
    )


def collect(handler, *args):
    async def run():
        return [item async for item in handler(*args)]
    return asyncio.run(run())


def test_only_owner_or_explicit_allowlist_grants_access():
    assert is_allowed_qq(OWNER, OWNER)
    assert not is_allowed_qq(OTHER, OWNER)
    assert is_allowed_qq(OTHER, OWNER, f"{OTHER}, 20002")
    assert not is_allowed_qq(OTHER, OWNER, OTHER, OTHER)
    assert not is_allowed_qq(OWNER, OWNER, blocked_qqs=OWNER)
    assert not is_allowed_qq("", "")
    assert not is_allowed_qq("神秘嘉宾", OWNER, "神秘嘉宾")
    assert not is_allowed_qq("１２３４５", "１２３４５")


@pytest.mark.parametrize("group", [GROUP, None])
def test_all_registered_handlers_ignore_unknown_qq(plugin, group):
    before = repr(plugin.storage.data)
    handlers = [
        handler for _, handler in inspect.getmembers(plugin, inspect.ismethod)
        if getattr(handler, "test_registered_command", False)
    ]
    assert len(handlers) >= 25
    for handler in handlers:
        assert collect(handler, event(OTHER, group=group)) == [], handler.__name__
    assert repr(plugin.storage.data) == before
    plugin.autopcr.health_text.assert_not_awaited()
    plugin.arena.query.assert_not_awaited()
    plugin.real_api.clan_status.assert_not_awaited()


@pytest.mark.parametrize("text", [
    "清日常", "#清日常", "#配置日常", "pcr帮助", "pcr启用",
    "竞技场查询", "竞技场监控", "公主竞技场排行榜1", "竞技场排行榜2",
    "出刀监控", "当前战报", "状态", "怎么拆", "b怎么拆",
])
def test_plain_commands_unknown_qq_are_silent(plugin, text):
    assert collect(plugin.plain_text_dispatch, event(OTHER, text)) == []
    plugin.autopcr.health_text.assert_not_awaited()


def test_allowlisted_daily_is_direct_and_does_not_require_admin(plugin):
    plugin.config["allowed_qqs"] = OTHER
    replies = collect(plugin.plain_text_dispatch, event(OTHER, "清日常"))
    assert len(replies) == 1
    assert "https://example.com/daily/login" in replies[0]
    plugin.autopcr.health_text.assert_awaited_once()


@pytest.mark.parametrize("sender", [OWNER, OTHER])
def test_disabled_group_has_no_business_replies_or_requests(plugin, sender):
    plugin.config["allowed_qqs"] = OTHER
    plugin.storage.set_group_enabled(GROUP, False)
    for text in ("清日常", "竞技场查询", "竞技场排行榜1", "怎么拆", "出刀监控", "状态"):
        assert collect(plugin.plain_text_dispatch, event(sender, text)) == []
    plugin.autopcr.health_text.assert_not_awaited()
    plugin.arena.query.assert_not_awaited()
    plugin.real_api.clan_status.assert_not_awaited()


def test_group_owner_can_enable_but_allowlisted_user_cannot(plugin):
    plugin.storage.set_group_enabled(GROUP, False)
    plugin.config["allowed_qqs"] = OTHER
    assert collect(plugin.group_enable, event(OTHER)) == []
    assert not plugin.storage.group_enabled(GROUP)
    assert collect(plugin.group_enable, event(OWNER))
    assert plugin.storage.group_enabled(GROUP)


def test_admin_flag_alone_does_not_authorize_user(plugin):
    plugin.admin_qqs.add(OTHER)
    assert collect(plugin.daily_link, event(OTHER)) == []
    assert collect(plugin.group_enable, event(OTHER)) == []


def test_revoked_or_blocked_user_loses_access(plugin):
    plugin.config["allowed_qqs"] = OTHER
    assert plugin._pcr_event_allowed(event(OTHER))
    plugin.config["allowed_qqs"] = ""
    assert not plugin._pcr_event_allowed(event(OTHER))
    plugin.config["allowed_qqs"] = OTHER
    plugin.blocked_qqs.add(OTHER)
    assert collect(plugin.daily_link, event(OTHER)) == []


def test_private_daily_is_silent_but_owner_can_read_own_account(plugin):
    assert collect(plugin.daily_link, event(OWNER, group=None)) == []
    assert collect(plugin.account_status, event(OWNER, group=None))
    assert collect(plugin.account_status, event(OTHER, group=None)) == []


def test_group_card_cannot_impersonate_owner(plugin):
    forged = event(OTHER)
    assert forged.message_obj.sender.card == OWNER
    assert not plugin._pcr_event_allowed(forged)


def test_monitor_target_rejects_disabled_group_or_other_private_recipient(plugin):
    assert plugin._monitor_target_allowed(OWNER, f"session:{SESSION}")
    assert not plugin._monitor_target_allowed(OTHER, f"session:{SESSION}")
    assert not plugin._monitor_target_allowed(OWNER, f"session:qq:FriendMessage:{OTHER}")
    assert plugin._monitor_target_allowed(OWNER, f"session:qq:FriendMessage:{OWNER}")
    plugin.storage.set_group_enabled(GROUP, False)
    assert not plugin._monitor_target_allowed(OWNER, f"session:{SESSION}")


def test_old_unapproved_monitors_never_query_accounts(plugin):
    plugin.storage.data["arena"] = {
        OTHER: [{"uid": "999", "push_target": f"session:{SESSION}", "settings": "1100"}]
    }
    plugin.storage.data["clan"] = {
        GROUP: {"out_damage_monitor": True, "monitor_qq": OTHER, "monitor_session": SESSION}
    }
    asyncio.run(plugin._poll_arena_monitors())
    asyncio.run(plugin._poll_clan_monitors())
    plugin.arena.query.assert_not_awaited()
    plugin.real_api.clan_status.assert_not_awaited()
    plugin.context.send_message.assert_not_awaited()


def test_owner_poll_runs_only_in_enabled_group(plugin, plugin_module, monkeypatch):
    plugin.storage.set_account(OWNER, {"kind": "channel", "uid": "999"})
    plugin.storage.data["arena"] = {
        OWNER: [{"uid": "999", "push_target": f"session:{SESSION}", "settings": "1100"}]
    }
    plugin.storage.data["clan"] = {
        GROUP: {"out_damage_monitor": True, "monitor_qq": OWNER, "monitor_session": SESSION}
    }
    monkeypatch.setattr(plugin_module, "update_arena_entry_from_result", lambda *args: [])
    monkeypatch.setattr(plugin_module, "update_clan_damage_state", lambda *args: [])
    asyncio.run(plugin._poll_arena_monitors())
    asyncio.run(plugin._poll_clan_monitors())
    plugin.arena.query.assert_awaited_once()
    assert plugin.arena.query.await_args.kwargs["user"] == OWNER
    plugin.real_api.clan_status.assert_awaited_once_with(OWNER, account="main")
    plugin.arena.query.reset_mock()
    plugin.real_api.clan_status.reset_mock()
    plugin.storage.set_group_enabled(GROUP, False)
    asyncio.run(plugin._poll_arena_monitors())
    asyncio.run(plugin._poll_clan_monitors())
    plugin.arena.query.assert_not_awaited()
    plugin.real_api.clan_status.assert_not_awaited()


def test_permission_is_checked_again_before_sending_monitor_result(plugin):
    assert not asyncio.run(plugin._send_monitor_message(
        f"session:{SESSION}", "private result", user_id=OTHER
    ))
    plugin.context.send_message.assert_not_awaited()


@pytest.mark.parametrize("change", ["revoke", "disable_group"])
def test_access_change_after_query_status_prevents_backend_request(plugin, change):
    plugin.config["allowed_qqs"] = OTHER
    plugin.storage.set_account(OTHER, {"kind": "channel", "uid": "999"})
    plugin.arena.ranking_text = AsyncMock(return_value="ranks")

    async def run():
        results = plugin._arena_ranking_page(event(OTHER), "jjc", 1)
        assert await anext(results)
        if change == "revoke":
            plugin.config["allowed_qqs"] = ""
        else:
            plugin.storage.set_group_enabled(GROUP, False)
        with pytest.raises(StopAsyncIteration):
            await anext(results)
        plugin.arena.ranking_text.assert_not_awaited()
    asyncio.run(run())


def test_terminate_cancels_background_monitor(plugin):
    async def run():
        plugin._monitor_task = asyncio.create_task(asyncio.sleep(60))
        await plugin.terminate()
        assert plugin._monitor_task.cancelled()
    asyncio.run(run())


def test_no_api_key_still_identifies_and_returns_prefilled_link(plugin,plugin_module,tmp_path,monkeypatch):
    plugin._arena_image_lock=asyncio.Lock()
    plugin.image_recognizer=types.SimpleNamespace(
        load_cached_templates=Mock(return_value=0),
        recognize_teams=Mock(return_value=[{'ids':[1001,1002,1003,1004,1005],'label':'defense_1'}]),
        get_icon=lambda cid:None,
    )
    plugin.pcrdfans=types.SimpleNamespace(api_key='',query=AsyncMock())
    plugin._pcr_image_path=lambda category:str(tmp_path/(category+'.png'))
    monkeypatch.setattr(plugin_module,'_has_image_message',lambda event:True)
    monkeypatch.setattr(plugin_module,'_first_image_path',AsyncMock(return_value='synthetic.png'))
    request=event(OWNER,'怎么拆')
    request.chain_result=lambda chain:chain
    replies=collect(plugin._arena_solution_query,request,1,'')
    plugin.image_recognizer.recognize_teams.assert_called_once()
    plugin.pcrdfans.query.assert_not_awaited()
    messages=[reply for reply in replies if isinstance(reply,str)]
    assert any('防守队伍 1' in reply for reply in messages)
    assert any('id=100101' in reply and 'id=100501' in reply for reply in messages)


def test_selected_personal_report_is_not_overwritten_by_mylog(plugin_module):
    from clan_report import prepare_clan_report
    status={'report_command':'my_report','damage_history':[{'history_id':9,'viewer_id':77,'damage':10}],'history_scope':'selected'}
    assert prepare_clan_report(status,'my_report',{'actual_logs':[]})['damage_history']==status['damage_history']


def test_status_render_failure_falls_back_to_text(plugin, plugin_module, monkeypatch):
    plugin.storage.set_account(OWNER, {'kind': 'channel', 'uid': '999'})
    plugin.real_api.clan_status.return_value = {'ok': True, 'clan': {'clan_id': 1},
        'clan_battle': {'id': 2}, 'damage_history': []}
    monkeypatch.setattr(plugin_module, 'render_clan_status', Mock(side_effect=RuntimeError('font missing')))
    replies = collect(plugin.clan_command, event(OWNER, '状态'))
    assert any(isinstance(reply, str) and '监控' in reply for reply in replies)


def _web_query_fixture(plugin, plugin_module, tmp_path):
    plugin.image_recognizer = types.SimpleNamespace(get_icon=lambda cid: None)
    plugin.pcrdfans = types.SimpleNamespace(api_key='', query=AsyncMock())
    plugin.arena_web = types.SimpleNamespace(enabled=True, query=AsyncMock(return_value=
        types.SimpleNamespace(empty=False, path=tmp_path/'web.png', count=5,
                              url='https://www.pcrdfans.com/battle')))
    plugin._pcr_image_path = lambda category: str(tmp_path/(category+'.png'))
    payload = ' '.join(plugin_module.name_for_id(cid) for cid in range(1001, 1006))
    request = event(OWNER, '怎么拆 '+payload)
    request.chain_result = lambda chain: chain
    return request, payload


def test_no_key_uses_enabled_public_web_query_and_never_bot_api(plugin, plugin_module, tmp_path):
    request, payload = _web_query_fixture(plugin, plugin_module, tmp_path)
    replies = collect(plugin._arena_solution_query, request, 1, payload)
    plugin.arena_web.query.assert_awaited_once()
    assert plugin.arena_web.query.await_args.args[0] == [1001,1002,1003,1004,1005]
    assert any(isinstance(reply,str) and '网页前5条' in reply for reply in replies)
    plugin.pcrdfans.query.assert_not_awaited()


def test_web_error_returns_manual_link_without_fabricated_solutions(plugin, plugin_module, tmp_path):
    request, payload = _web_query_fixture(plugin, plugin_module, tmp_path)
    plugin.arena_web.query.side_effect = plugin_module.ArenaWebQueryError('要求验证')
    replies = collect(plugin._arena_solution_query, request, 1, payload)
    assert any(isinstance(reply,str) and '要求验证' in reply and 'id=100101' in reply for reply in replies)
    plugin.pcrdfans.query.assert_not_awaited()


def test_recognition_only_never_opens_browser(plugin, plugin_module, tmp_path):
    request, payload = _web_query_fixture(plugin, plugin_module, tmp_path)
    request.message_str = '识别阵容 '+payload
    collect(plugin._arena_solution_query, request, 1, payload)
    plugin.arena_web.query.assert_not_awaited()
    plugin.pcrdfans.query.assert_not_awaited()


def test_api_key_prefers_api_without_opening_web_browser(plugin, plugin_module, tmp_path):
    request, payload = _web_query_fixture(plugin, plugin_module, tmp_path)
    plugin.pcrdfans.api_key = 'synthetic-test-key'
    plugin.pcrdfans.query.return_value = types.SimpleNamespace(entries=[])
    collect(plugin._arena_solution_query, request, 1, payload)
    plugin.pcrdfans.query.assert_awaited_once()
    plugin.arena_web.query.assert_not_awaited()


def test_permission_revocation_after_web_progress_prevents_browser_request(plugin, plugin_module, tmp_path):
    request, payload = _web_query_fixture(plugin, plugin_module, tmp_path)
    async def run():
        replies = plugin._arena_solution_query(request, 1, payload)
        assert await anext(replies)
        assert await anext(replies)
        progress = await anext(replies)
        assert '网页查询' in progress
        plugin.storage.set_group_enabled(GROUP, False)
        with pytest.raises(StopAsyncIteration):
            await anext(replies)
        plugin.arena_web.query.assert_not_awaited()
    asyncio.run(run())
