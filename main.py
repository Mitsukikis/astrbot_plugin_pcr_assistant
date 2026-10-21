import asyncio
import os
import time
import uuid
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.message.message_event_result import MessageChain

from .arena_client import ArenaClient
from .arena_web_query import ArenaWebQueryClient, ArenaWebQueryError
from .arena_team_builder import build_disjoint_team_plans
from .arena_team_report import compose_team_plans_bytes
from .arena_ranking import parse_arena_ranking_command
from .arena_solution import (
    PCRDFANS_SEARCH_URL,
    PcrdFansClient,
    PcrdFansError,
    PcrdFansMissingKey,
    parse_solution_command,
    pcrdfans_battle_url,
)
from .arena_state import (
    apply_arena_settings,
    bind_arena_uid,
    clear_arena_bindings,
    delete_arena_binding,
    describe_arena_bindings,
    normalize_arena_settings,
    rename_arena_binding,
    resolve_arena_query_targets,
    select_arena_bindings,
    set_arena_push_target,
)
from .autopcr_client import AutoPCRClient
from .auth import (
    is_admin_qq,
    is_allowed_qq,
    numeric_sender_id_from_event,
    parse_qq_list,
    require_pcr_access,
)
from .clan_access import (
    clan_command_account_qq,
    clan_command_needs_account,
    make_monitor_id,
)
from .clan_report import (
    build_current_report_text, build_damage_count_summary, render_text_image,
    render_clan_report, render_clan_status,
)
from .clan_history import merge_clan_history, select_clan_report
from .clan_coordination import COORDINATION_COMMANDS, handle_clan_coordination
from .clan_state import build_clan_command_reply, build_clan_status_text, clan_state_update_for_command
from .compat_commands import build_compat_reply, match_compat_command
from .monitoring import update_arena_entry_from_result, update_clan_damage_state
from .pcr_image_recognizer import ImageRecognitionError, PcrImageRecognizer
from .pcr_chara import parse_team_names
from .pcr_chara import name_for_id, extend_character_roster, load_character_roster, id_from_unit_id
from .pcr_cards import render_arena_recognition, render_arena_solutions, render_clan_damage_detail
from .real_api_client import PCRRealAPIClient, RealAPIError
from .command_router import (
    ARENA_COMMANDS,
    CLAN_COMMAND_ACTIONS,
    CLAN_PLAIN_COMMANDS,
    CMD_DAILY,
    CMD_DAILY_CLEAR_ALL,
    CMD_DAILY_CONFIG,
    CMD_DAILY_HASH,
    CMD_DAILY_RECORD,
    CMD_ARENA_BIND,
    CMD_ARENA_CANCEL_MONITOR,
    CMD_ARENA_CANCEL_MONITOR_HASH,
    CMD_ARENA_CLEAR_BINDINGS,
    CMD_ARENA_DELETE_BINDING,
    CMD_ARENA_DETAIL_QUERY,
    CMD_ARENA_DUEL_RECORD,
    CMD_ARENA_HELP,
    CMD_ARENA_KILLER,
    CMD_ARENA_KILLER_DISABLE,
    CMD_ARENA_KILLER_ENABLE,
    CMD_ARENA_KILLER_JJC_OFF,
    CMD_ARENA_KILLER_JJC_ON,
    CMD_ARENA_KILLER_PJJC_OFF,
    CMD_ARENA_KILLER_PJJC_ON,
    CMD_ARENA_MONITOR,
    CMD_ARENA_MONITOR_HASH,
    CMD_ARENA_PUSH_BILI_DISABLE,
    CMD_ARENA_PUSH_BILI_DISABLE_UPPER,
    CMD_ARENA_PUSH_BILI_ENABLE,
    CMD_ARENA_PUSH_BILI_ENABLE_UPPER,
    CMD_ARENA_PUSH_CHANNEL_DISABLE,
    CMD_ARENA_PUSH_CHANNEL_ENABLE,
    CMD_ARENA_PUSH_GROUP,
    CMD_ARENA_PUSH_PRIVATE,
    CMD_ARENA_QUERY,
    CMD_ARENA_RECORD,
    CMD_ARENA_RENAME,
    CMD_ARENA_SETTINGS,
    CMD_ARENA_STATUS,
    CMD_ARENA_SUBSCRIBE_STATUS,
    CMD_CHANNEL_ARENA_BIND,
    CMD_CHANNEL_ARENA_CLEAR_BINDINGS,
    CMD_CHANNEL_ARENA_DELETE_BINDING,
    CMD_CHANNEL_ARENA_DETAIL_QUERY,
    CMD_CHANNEL_ARENA_DUEL_RECORD,
    CMD_CHANNEL_ARENA_HELP,
    CMD_CHANNEL_ARENA_QUERY,
    CMD_CHANNEL_ARENA_RECORD,
    CMD_CHANNEL_ARENA_RENAME,
    CMD_CHANNEL_ARENA_SETTINGS,
    CMD_CHANNEL_ARENA_SUBSCRIBE_STATUS,
    CMD_CLAN_LEGACY_MONITOR,
    CMD_CLAN_LEGACY_STATUS,
    CMD_CLAN_OUT_DAMAGE_MONITOR,
    CMD_CLAN_OUT_DAMAGE_MONITOR_CLOSE,
    CMD_GROUP_DISABLE,
    CMD_GROUP_ENABLE,
    CMD_GROUP_STATUS,
    DAILY_LINK_COMMANDS,
    GROUP_CONTROL_COMMANDS,
    arena_base_command,
    arena_command_platform,
    group_command_requires_enabled,
    match_plain_command,
    normalize_command_text,
    should_ignore_disabled_plain_clan_command,
)
from .storage import PCRStorage, mask_value, parse_bind_payload


PLUGIN_NAME = "astrbot_plugin_pcr_assistant"
PLUGIN_DESC = "\u81ea\u7528 PCR \u52a9\u624b"
PLUGIN_VERSION = "0.2.2"

DEFAULT_AUTOPCR_BASE_URL = "http://127.0.0.1:18080/daily"
DEFAULT_AUTOPCR_PUBLIC_URL = "http://你的服务器IP:18080/daily/login"
DEFAULT_REAL_API_URL = "http://127.0.0.1:18081"
DEFAULT_ADMIN_QQ = ""
DEFAULT_MONITOR_INTERVAL_SECONDS = "60"
DEFAULT_PCRDFANS_SEARCH_URL = PCRDFANS_SEARCH_URL

CMD_HELP = "pcr\u5e2e\u52a9"
CMD_BIND = "pcr\u7ed1\u5b9a"
CMD_ACCOUNT = "pcr\u8d26\u53f7"
CMD_UNBIND = "pcr\u89e3\u7ed1"
CMD_ARENA_TEMPLATES = "竞技场更新卡池"
CMD_ARENA_CONTINUOUS = "#怎么拆"
CMD_ARENA_CONTINUOUS_END = "结束查询"
PRIVATE_ACCOUNT_COMMANDS = (
    CMD_BIND,
    CMD_ACCOUNT,
    CMD_UNBIND,
)
PLAIN_COMMANDS = (
    CMD_ARENA_TEMPLATES,
    CMD_ARENA_CONTINUOUS,
    CMD_ARENA_CONTINUOUS_END,
    CMD_HELP,
    *GROUP_CONTROL_COMMANDS,
    *DAILY_LINK_COMMANDS,
    CMD_BIND,
    CMD_ACCOUNT,
    CMD_UNBIND,
    *ARENA_COMMANDS,
    *CLAN_PLAIN_COMMANDS,
)
CLAN_COMMAND_ALIASES = tuple(
    command for command in CLAN_PLAIN_COMMANDS
    if command != CMD_CLAN_OUT_DAMAGE_MONITOR
)
ARENA_MONITOR_ON_ALIASES = {
    CMD_ARENA_MONITOR_HASH,
    CMD_ARENA_KILLER_ENABLE,
    CMD_ARENA_PUSH_BILI_ENABLE,
    CMD_ARENA_PUSH_BILI_ENABLE_UPPER,
    CMD_ARENA_PUSH_CHANNEL_ENABLE,
}
ARENA_MONITOR_OFF_ALIASES = {
    CMD_ARENA_CANCEL_MONITOR_HASH,
    CMD_ARENA_KILLER_DISABLE,
    CMD_ARENA_PUSH_BILI_DISABLE,
    CMD_ARENA_PUSH_BILI_DISABLE_UPPER,
    CMD_ARENA_PUSH_CHANNEL_DISABLE,
}
ARENA_STATUS_ALIASES = {
    CMD_ARENA_KILLER,
}

WORD_OPEN = "\u5f00\u542f"
WORD_CLOSE = "\u5173\u95ed"
WORD_CLOSED_ALT = "\u5173"
WORD_OFF = "off"
WORD_DISABLE = "disable"
WORD_DISABLED = "disabled"
WORD_FALSE = "false"
WORD_ZERO = "0"
WORD_GROUP_UNKNOWN = "\u672a\u77e5\u7fa4"
GROUP_DISABLED_MESSAGE = (
    "PCR \u529f\u80fd\u5c1a\u672a\u5728\u672c\u7fa4\u542f\u7528\uff0c"
    f"\u8bf7\u5148\u53d1\u9001 {CMD_GROUP_ENABLE}\u3002"
)
ADMIN_ONLY_MESSAGE = (
    "\u6b64 PCR \u6307\u4ee4\u53ea\u5141\u8bb8\u7ba1\u7406\u5458 QQ \u4f7f\u7528\uff0c"
    "\u6743\u9650\u53ea\u8bc6\u522b QQ \u53f7\uff0c\u4e0d\u770b\u7fa4\u6635\u79f0/\u7fa4\u540d\u7247\u3002"
)
BLOCKED_QQ_MESSAGE = "\u4f60\u5df2\u5728 PCR \u529f\u80fd\u9ed1\u540d\u5355\u4e2d\u3002"
NO_BOUND_ACCOUNT_MESSAGE = (
    "\u4f60\u6ca1\u6709\u7ed1\u5b9a\u8d26\u53f7,"
    f"\u8bf7\u79c1\u804a\u673a\u5668\u4eba {CMD_BIND} \u6e20\u9053\u670d UID <string...> \u6765\u7ed1\u5b9a"
)


def _config_get(config: AstrBotConfig, key: str, default: str) -> str:
    getter = getattr(config, "get", None)
    if callable(getter):
        return getter(key, default)
    return default


def _config_int(config: AstrBotConfig, key: str, default: str, minimum: int = 30) -> int:
    try:
        value = int(_config_get(config, key, default))
    except (TypeError, ValueError):
        value = int(default)
    return max(minimum, value)


def _config_qq_set(config: AstrBotConfig, key: str, default: str = "") -> set[str]:
    return parse_qq_list(_config_get(config, key, default))


def _message_obj(event: AstrMessageEvent):
    return getattr(event, "message_obj", None)


def _group_id(event: AstrMessageEvent):
    message_obj = _message_obj(event)
    return getattr(message_obj, "group_id", None)


def _is_private(event: AstrMessageEvent) -> bool:
    group_id = _group_id(event)
    return group_id is None or group_id == "" or str(group_id) == "0"


def _group_key(event: AstrMessageEvent) -> str:
    group_id = _group_id(event)
    if group_id is not None and group_id != "" and str(group_id) != "0":
        return str(group_id)
    origin = getattr(event, "unified_msg_origin", "")
    return str(origin or WORD_GROUP_UNKNOWN)


def _sender_id(event: AstrMessageEvent) -> str:
    numeric_sender = numeric_sender_id_from_event(event)
    if numeric_sender:
        return numeric_sender

    getter = getattr(event, "get_sender_id", None)
    if callable(getter):
        sender_id = getter()
        if sender_id is not None and str(sender_id) != "":
            return str(sender_id)

    message_obj = _message_obj(event)
    sender = getattr(message_obj, "sender", None)
    user_id = getattr(sender, "user_id", None)
    return str(user_id or "")


def _message_text(event: AstrMessageEvent) -> str:
    text = getattr(event, "message_str", None)
    if text is None:
        getter = getattr(event, "get_message_str", None)
        if callable(getter):
            text = getter()
    return str(text or "").strip()


def _normalized_text(event: AstrMessageEvent) -> str:
    return normalize_command_text(_message_text(event))


def _payload_after(event: AstrMessageEvent, command: str) -> str:
    text = _normalized_text(event)
    if text == command:
        return ""
    if text.startswith(command):
        return text[len(command):].strip()
    return text.strip()


def _payload_after_any(event: AstrMessageEvent, commands: tuple[str, ...]) -> tuple[str, str]:
    text = _normalized_text(event)
    for command in commands:
        if text == command:
            return command, ""
        if text.startswith(command + " "):
            return command, text[len(command):].strip()
    return "", text.strip()


def _arena_aliases(base_command: str) -> tuple[str, ...]:
    return tuple(
        command for command in ARENA_COMMANDS
        if arena_base_command(command) == base_command
    )


def _first_token(payload: str, default: str = "0") -> str:
    parts = payload.strip().split(maxsplit=1)
    if not parts:
        return default
    return parts[0]


def _switch_enabled(payload: str) -> bool:
    value = payload.strip().lower()
    return value not in {
        WORD_CLOSE,
        WORD_CLOSED_ALT,
        WORD_OFF,
        WORD_DISABLE,
        WORD_DISABLED,
        WORD_FALSE,
        WORD_ZERO,
    }


def _format_account(account: dict[str, str]) -> str:
    return f"{account.get('kind', '')} {mask_value(account.get('uid', ''))}"


def _format_arena_platform(platform: str) -> str:
    if platform == "bili":
        return "B\u670d"
    return "\u6e20\u9053\u670d"


def _format_arena_binding(entry: dict[str, str]) -> str:
    nickname = entry.get("nickname") or "\u672a\u547d\u540d"
    platform = _format_arena_platform(str(entry.get("platform", "channel")))
    return (
        f"{nickname} {platform} uid={entry.get('uid', '')} "
        f"\u8bbe\u7f6e:{entry.get('settings', '1100')}"
    )


def _arena_settings_with_flags(
    settings: str,
    jjc: bool | None = None,
    pjjc: bool | None = None,
) -> str:
    chars = list(normalize_arena_settings(settings or "1100"))
    if jjc is not None:
        chars[0] = "1" if jjc else "0"
    if pjjc is not None:
        chars[1] = "1" if pjjc else "0"
    return "".join(chars)


def _mark_processed(event: AstrMessageEvent) -> None:
    setattr(event, "_pcr_assistant_processed", True)


def _is_group_feature_enabled(storage: PCRStorage, event: AstrMessageEvent) -> bool:
    return _is_private(event) or storage.group_enabled(_group_key(event))


def _has_image_message(event: AstrMessageEvent) -> bool:
    getter = getattr(event, "get_messages", None)
    if not callable(getter):
        return False
    try:
        messages = getter()
    except Exception:
        return False
    for component in messages or []:
        if component.__class__.__name__ == "Image":
            return True
    return False


async def _first_image_path(event: AstrMessageEvent) -> str | None:
    getter = getattr(event, "get_messages", None)
    if not callable(getter):
        return None
    try:
        messages = getter()
    except Exception:
        return None
    for component in messages or []:
        if component.__class__.__name__ != "Image":
            continue
        converter = getattr(component, "convert_to_file_path", None)
        if not callable(converter):
            continue
        return await converter()
    return None


@register(PLUGIN_NAME, "local", PLUGIN_DESC, PLUGIN_VERSION, "")
class PCRAssistantPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.context = context
        self.config = config
        self._arena_image_lock = asyncio.Lock()
        self._arena_image_sessions = {}
        self.admin_qq = _config_get(config, "admin_qq", DEFAULT_ADMIN_QQ)
        self.admin_qqs = _config_qq_set(config, "admin_qqs", "")
        self.admin_qqs.update(parse_qq_list(self.admin_qq))
        if not self.admin_qqs:
            self.admin_qqs = {DEFAULT_ADMIN_QQ}
        self.blocked_qqs = _config_qq_set(config, "blocked_qqs", "")
        data_dir = os.path.join(os.path.dirname(__file__), "data")
        self._chara_cache = os.path.join(data_dir, 'characters.json')
        load_character_roster(self._chara_cache)
        self.storage = PCRStorage(os.path.join(data_dir, "state.json"))
        try:
            self.image_recognizer = PcrImageRecognizer(
                cache_dir=os.path.join(data_dir, "icons"),
            )
        except ImageRecognitionError as exc:
            self.image_recognizer = None
            logger.warning(f"PCR image recognizer disabled: {exc}")
        self.autopcr = AutoPCRClient(
            _config_get(config, "autopcr_base_url", DEFAULT_AUTOPCR_BASE_URL),
            _config_get(config, "autopcr_public_url", DEFAULT_AUTOPCR_PUBLIC_URL),
        )
        self.real_api_user = _config_get(config, "real_api_user", self.admin_qq)
        self.real_api = PCRRealAPIClient(
            _config_get(config, "pcr_real_api_url", DEFAULT_REAL_API_URL),
        )
        self.arena = ArenaClient(self.real_api, default_user=self.real_api_user)
        self.pcrdfans = PcrdFansClient(
            _config_get(config, "pcrdfans_api_key", ""),
            _config_get(config, "pcrdfans_search_url", DEFAULT_PCRDFANS_SEARCH_URL),
        )
        web_enabled = _config_get(config, 'pcrdfans_web_query_enabled', False)
        self.arena_web = ArenaWebQueryClient(
            enabled=web_enabled is True or str(web_enabled).lower() == 'true',
            recognizer=self.image_recognizer,
        )
        self.monitor_interval_seconds = _config_int(
            config,
            "monitor_interval_seconds",
            DEFAULT_MONITOR_INTERVAL_SECONDS,
        )
        self._monitor_task = asyncio.create_task(
            self._monitor_loop(), name="PCR real arena/clan monitor"
        )
        logger.info("PCR assistant plugin loaded")

    async def terminate(self):
        self._monitor_task.cancel()
        await asyncio.gather(self._monitor_task, return_exceptions=True)
        web_client = getattr(self, 'arena_web', None)
        if web_client:
            await web_client.close()

    def _user_allowed(self, sender_id: str) -> bool:
        return is_allowed_qq(
            sender_id,
            self.admin_qq,
            _config_get(self.config, "allowed_qqs", ""),
            self.blocked_qqs,
        )

    def _pcr_event_allowed(
        self, event: AstrMessageEvent, *, allow_private=False, manage_group=False
    ) -> bool:
        sender = numeric_sender_id_from_event(event)
        if not self._user_allowed(sender):
            return False
        if manage_group:
            return is_admin_qq(sender, self.admin_qqs, self.blocked_qqs)
        if _is_private(event):
            return allow_private
        return self.storage.group_enabled(_group_key(event))

    def _monitor_target_allowed(self, user_id: str, target: str | None) -> bool:
        if not self._user_allowed(user_id):
            return False
        target_text = str(target or "")
        if not target_text.startswith("session:"):
            return False
        parts = target_text[len("session:"):].split(":", 2)
        if len(parts) != 3 or not parts[0]:
            return False
        _, message_type, session_id = parts
        if message_type == "GroupMessage":
            return self.storage.group_enabled(session_id)
        return message_type == "FriendMessage" and session_id == str(user_id)

    def _admin_block_message(self, event: AstrMessageEvent) -> str | None:
        sender = _sender_id(event)
        if sender in self.blocked_qqs:
            return BLOCKED_QQ_MESSAGE
        if not is_admin_qq(sender, self.admin_qqs, self.blocked_qqs):
            return ADMIN_ONLY_MESSAGE
        return None

    def _blocked_message(self, event: AstrMessageEvent) -> str | None:
        sender = _sender_id(event)
        if sender in self.blocked_qqs:
            return BLOCKED_QQ_MESSAGE
        return None

    @filter.command(CMD_HELP)
    @require_pcr_access(allow_private=True)
    async def pcr_help(self, event: AstrMessageEvent):
        _mark_processed(event)
        if not _is_group_feature_enabled(self.storage, event):
            yield event.plain_result(GROUP_DISABLED_MESSAGE)
            return

        yield event.plain_result(
            "\u81ea\u7528 PCR \u52a9\u624b\u6307\u4ee4\uff1a\n"
            f"{CMD_GROUP_ENABLE}\uff1a\u5728\u672c\u7fa4\u542f\u7528 PCR \u529f\u80fd\n"
            f"{CMD_GROUP_DISABLE}\uff1a\u5728\u672c\u7fa4\u7981\u7528 PCR \u529f\u80fd\n"
            f"{CMD_GROUP_STATUS}\uff1a\u67e5\u770b\u672c\u7fa4 PCR \u72b6\u6001\n"
            f"{CMD_HELP}\uff1a\u67e5\u770b\u5e2e\u52a9\n"
            f"{CMD_DAILY}/{CMD_DAILY_CONFIG}/{CMD_DAILY_HASH}\uff1a\u67e5\u770b AutoPCR \u5165\u53e3\n"
            f"{CMD_BIND} \u6e20\u9053\u670d UID <string...>\uff1a\u79c1\u804a\u7ed1\u5b9a\u8d26\u53f7\n"
            f"{CMD_BIND} b\u670d UID access_key\uff1a\u79c1\u804a\u7ed1\u5b9a B \u670d\n"
            f"{CMD_ACCOUNT}\uff1a\u79c1\u804a\u67e5\u770b\u5df2\u7ed1\u5b9a\u8d26\u53f7\n"
            f"{CMD_UNBIND}\uff1a\u79c1\u804a\u89e3\u7ed1\u8d26\u53f7\n"
            f"{CMD_ARENA_HELP}\uff1a\u67e5\u770b\u7ade\u6280\u573a\u6307\u4ee4\n"
            f"{CMD_ARENA_BIND}/\u6e20{CMD_ARENA_BIND} UID [\u6635\u79f0]\uff1a"
            "\u7ed1\u5b9a\u6e20\u9053\u670d\u7ade\u6280\u573a UID\n"
            f"{CMD_ARENA_QUERY}/{CMD_ARENA_DETAIL_QUERY} [uid/\u5e8f\u53f7/@\u67d0\u4eba]\uff1a"
            "\u67e5\u8be2\u771f\u5b9e JJC/PJJC \u6392\u540d\n"
            f"{CMD_ARENA_SUBSCRIBE_STATUS}\uff1a\u67e5\u770b\u672c\u5730\u7ade\u6280\u573a\u8ba2\u9605\u72b6\u6001\n"
            f"{CMD_ARENA_SETTINGS} 1013 [\u5e8f\u53f7]\uff1a\u4fee\u6539\u7ade\u6280\u573a\u8bbe\u7f6e\n"
            f"{CMD_ARENA_MONITOR}/{CMD_ARENA_CANCEL_MONITOR}\uff1a"
            "\u5f00\u5173\u7ade\u6280\u573a\u67e5\u699c\u76d1\u63a7\n"
            "\u7ade\u6280\u573a\u6392\u884c\u699c1/\u516c\u4e3b\u7ade\u6280\u573a\u6392\u884c\u699c1\uff1a"
            "\u67e5\u770b\u5f53\u524d\u573a\u5206\u9875\u540d\u5355\n"
            f"{CMD_ARENA_KILLER_JJC_ON}/{CMD_ARENA_KILLER_PJJC_ON}\uff1a"
            "\u5207\u6362 JJC/PJJC \u76d1\u63a7\u4f4d\n"
            f"{CMD_ARENA_PUSH_GROUP}/{CMD_ARENA_PUSH_PRIVATE} [\u5e8f\u53f7]\uff1a"
            "\u5f00\u542f/\u4fee\u6539\u6392\u540d\u53d8\u5316\u63d0\u9192\u63a8\u9001\u76ee\u6807\n"
            "\u600e\u4e48\u62c6 \u5bab\u5b50 \u601c(\u65b0\u5e74) ...\uff1a"
            "\u67e5\u8be2 pcrdfans \u7ade\u6280\u573a\u4f5c\u4e1a\uff0c\u652f\u6301 b\u600e\u4e48\u62c6/\u53f0\u600e\u4e48\u62c6/\u65e5\u600e\u4e48\u62c6\n"
            f"{CMD_CLAN_OUT_DAMAGE_MONITOR}/{CMD_CLAN_OUT_DAMAGE_MONITOR_CLOSE}\uff1a"
            "\u7fa4\u51fa\u5200\u76d1\u63a7\u5f00\u5173\n"
            "状态：五王血量、阶段、正在挑战人数图片\n"
            "\u5f53\u524d\u6218\u62a5/\u6211\u7684\u6218\u62a5/\u4eca\u65e5\u6218\u62a5/"
            "出刀详情 history_id：查询真实会战记录图片\n"
            "\u9884\u7ea6/\u67e5\u6811/sl/\u7533\u8bf7\u51fa\u5200/\u6743\u9650\uff1a"
            "本群登记（按QQ隔离，不执行游戏操作）\n"
            "怎么拆 + 游戏原图：识别右侧防守阵容；无Key可开启网页作业图查询\n"
            "竞技场更新卡池：更新头像；#怎么拆/结束查询：连续识图开关\n"
            "\u5f00\u542f\u624b\u52a8\u62a5\u5200/\u5173\u95ed\u624b\u52a8\u62a5\u5200/"
            "\u5f00\u542f\u56fe\u7247\u6a21\u5f0f/\u5173\u95ed\u56fe\u7247\u6a21\u5f0f\uff1a"
            "\u4fdd\u5b58\u672c\u5730\u7fa4\u72b6\u6001"
        )

    @filter.command(CMD_GROUP_ENABLE)
    @require_pcr_access(manage_group=True)
    async def group_enable(self, event: AstrMessageEvent):
        _mark_processed(event)
        admin_block = self._admin_block_message(event)
        if admin_block:
            yield event.plain_result(admin_block)
            return
        if _is_private(event):
            yield event.plain_result(
                "\u8fd9\u662f\u7fa4\u8bbe\u7f6e\uff0c\u8bf7\u5728\u9700\u8981\u542f\u7528\u7684\u7fa4\u91cc\u53d1\u9001\u3002"
            )
            return

        self.storage.set_group_enabled(_group_key(event), True)
        yield event.plain_result("PCR \u529f\u80fd\u5df2\u5728\u672c\u7fa4\u542f\u7528\u3002")

    @filter.command(CMD_GROUP_DISABLE)
    @require_pcr_access(manage_group=True)
    async def group_disable(self, event: AstrMessageEvent):
        _mark_processed(event)
        admin_block = self._admin_block_message(event)
        if admin_block:
            yield event.plain_result(admin_block)
            return
        if _is_private(event):
            yield event.plain_result(
                "\u8fd9\u662f\u7fa4\u8bbe\u7f6e\uff0c\u8bf7\u5728\u9700\u8981\u7981\u7528\u7684\u7fa4\u91cc\u53d1\u9001\u3002"
            )
            return
        if (
            group_command_requires_enabled(CMD_GROUP_DISABLE, PRIVATE_ACCOUNT_COMMANDS)
            and not _is_group_feature_enabled(self.storage, event)
        ):
            yield event.plain_result(GROUP_DISABLED_MESSAGE)
            return

        self.storage.set_group_enabled(_group_key(event), False)
        yield event.plain_result("PCR \u529f\u80fd\u5df2\u5728\u672c\u7fa4\u7981\u7528\u3002")

    @filter.command(CMD_GROUP_STATUS)
    @require_pcr_access(manage_group=True)
    async def group_status(self, event: AstrMessageEvent):
        _mark_processed(event)
        if _is_private(event):
            yield event.plain_result(
                "\u79c1\u804a\u4e2d PCR \u8d26\u53f7\u529f\u80fd\u53ef\u76f4\u63a5\u4f7f\u7528\u3002"
            )
            return

        enabled = self.storage.group_enabled(_group_key(event))
        status = "\u5df2\u542f\u7528" if enabled else "\u672a\u542f\u7528"
        yield event.plain_result(f"\u672c\u7fa4 PCR \u529f\u80fd\uff1a{status}")

    @filter.command(CMD_DAILY)
    @require_pcr_access()
    async def daily_link(self, event: AstrMessageEvent):
        _mark_processed(event)
        if not _is_group_feature_enabled(self.storage, event):
            yield event.plain_result(GROUP_DISABLED_MESSAGE)
            return

        health = await self.autopcr.health_text()
        yield event.plain_result(
            f"{health}\n\u516c\u5f00\u5165\u53e3\uff1a{self.autopcr.login_url}"
        )

    @filter.command(CMD_DAILY_CONFIG)
    @require_pcr_access()
    async def daily_config_link(self, event: AstrMessageEvent):
        async for result in self.daily_link(event):
            yield result

    @filter.command(CMD_DAILY_HASH)
    @require_pcr_access()
    async def daily_hash_link(self, event: AstrMessageEvent):
        async for result in self.daily_link(event):
            yield result

    @filter.command(CMD_DAILY_CLEAR_ALL)
    @require_pcr_access()
    async def daily_clear_all_link(self, event: AstrMessageEvent):
        async for result in self.daily_link(event):
            yield result

    @filter.command(CMD_DAILY_RECORD)
    @require_pcr_access()
    async def daily_record_link(self, event: AstrMessageEvent):
        async for result in self.daily_link(event):
            yield result

    @filter.command(CMD_BIND)
    @require_pcr_access(allow_private=True)
    async def bind_account(self, event: AstrMessageEvent):
        _mark_processed(event)
        blocked = self._blocked_message(event)
        if blocked:
            yield event.plain_result(blocked)
            return
        if not _is_private(event):
            yield event.plain_result(
                "\u8d26\u53f7\u5bc6\u94a5\u53ea\u80fd\u79c1\u804a\u673a\u5668\u4eba\u7ed1\u5b9a\uff0c"
                "\u8bf7\u4e0d\u8981\u5728\u7fa4\u91cc\u53d1\u9001\u3002"
            )
            return

        try:
            parsed = parse_bind_payload(_payload_after(event, CMD_BIND))
        except ValueError:
            yield event.plain_result(
                "\u7ed1\u5b9a\u683c\u5f0f\u4e0d\u6b63\u786e\u3002"
                f"\u793a\u4f8b\uff1a{CMD_BIND} \u6e20\u9053\u670d UID <string...> "
                f"\u6216 {CMD_BIND} b\u670d UID access_key"
            )
            return

        sender = _sender_id(event)
        self.storage.set_account(sender, parsed)
        sync_warning = ""
        try:
            await self.real_api.upsert_account(sender, parsed)
        except RealAPIError as exc:
            sync_warning = f"\n\u4f46\u540c\u6b65 AutoPCR \u771f\u5b9e\u8d26\u53f7\u5931\u8d25\uff1a{exc}"
        yield event.plain_result(
            f"\u7ed1\u5b9a\u6210\u529f\uff1a{parsed['kind']} {mask_value(parsed['uid'])}"
            f"{sync_warning}"
        )

    @filter.command(CMD_ACCOUNT)
    @require_pcr_access(allow_private=True)
    async def account_status(self, event: AstrMessageEvent):
        _mark_processed(event)
        blocked = self._blocked_message(event)
        if blocked:
            yield event.plain_result(blocked)
            return
        if not _is_private(event):
            yield event.plain_result(
                "\u8d26\u53f7\u72b6\u6001\u8bf7\u79c1\u804a\u67e5\u770b\u3002"
            )
            return

        account = self.storage.get_account(_sender_id(event))
        if not account:
            yield event.plain_result("\u8fd8\u6ca1\u6709\u7ed1\u5b9a PCR \u8d26\u53f7\u3002")
            return
        yield event.plain_result(f"\u5df2\u7ed1\u5b9a\uff1a{_format_account(account)}")

    @filter.command(CMD_UNBIND)
    @require_pcr_access(allow_private=True)
    async def unbind_account(self, event: AstrMessageEvent):
        _mark_processed(event)
        blocked = self._blocked_message(event)
        if blocked:
            yield event.plain_result(blocked)
            return
        if not _is_private(event):
            yield event.plain_result(
                "\u89e3\u7ed1\u8d26\u53f7\u8bf7\u79c1\u804a\u64cd\u4f5c\u3002"
            )
            return

        self.storage.remove_account(_sender_id(event))
        yield event.plain_result(
            "\u5df2\u79fb\u9664\u672c\u63d2\u4ef6\u4fdd\u5b58\u7684\u8d26\u53f7\u7ed1\u5b9a\u3002"
        )

    @filter.command(CMD_ARENA_BIND, alias={CMD_CHANNEL_ARENA_BIND})
    @require_pcr_access()
    async def arena_bind(self, event: AstrMessageEvent):
        _mark_processed(event)
        blocked = self._arena_block_message(event)
        if blocked:
            yield event.plain_result(blocked)
            return

        command, payload = _payload_after_any(event, _arena_aliases(CMD_ARENA_BIND))
        parts = payload.split(maxsplit=1)
        if not parts or not parts[0]:
            yield event.plain_result(
                f"\u683c\u5f0f\uff1a{CMD_ARENA_BIND} UID [\u6635\u79f0]"
                f"\uff0c\u6e20\u9053\u670d\u7528 \u6e20{CMD_ARENA_BIND}"
            )
            return

        uid = parts[0]
        nickname = parts[1].strip() if len(parts) > 1 else uid
        platform = arena_command_platform(command)
        entry = bind_arena_uid(self.storage, _sender_id(event), uid, nickname, platform)
        yield event.plain_result(
            f"\u5df2\u7ed1\u5b9a\u7ade\u6280\u573a UID\uff1a{mask_value(uid)}"
            f"\uff08{nickname}\uff09\n"
            f"\u5e73\u53f0\uff1a{_format_arena_platform(platform)}\n"
            f"\u5f53\u524d\u8bbe\u7f6e\uff1a{entry.get('settings', '1100')}"
        )

    @filter.command(CMD_ARENA_QUERY, alias={CMD_CHANNEL_ARENA_QUERY})
    @require_pcr_access()
    async def arena_query(self, event: AstrMessageEvent):
        _mark_processed(event)
        blocked = self._arena_block_message(event)
        if blocked:
            yield event.plain_result(blocked)
            return

        _, payload = _payload_after_any(event, _arena_aliases(CMD_ARENA_QUERY))
        yield event.plain_result(
            await self._arena_backend_pending_reply(
                event,
                payload,
                "\u7ade\u6280\u573a\u67e5\u8be2",
            )
        )

    @filter.command(CMD_ARENA_HELP, alias={CMD_CHANNEL_ARENA_HELP})
    @require_pcr_access()
    async def arena_help(self, event: AstrMessageEvent):
        _mark_processed(event)
        blocked = self._arena_block_message(event)
        if blocked:
            yield event.plain_result(blocked)
            return

        yield event.plain_result(
            "\u7ade\u6280\u573a\u6307\u4ee4\uff1a\n"
            f"{CMD_ARENA_BIND} UID [\u6635\u79f0]\uff1a\u7ed1\u5b9a\u6e20\u9053\u670d\n"
            f"\u6e20{CMD_ARENA_BIND} UID [\u6635\u79f0]\uff1a\u540c\u4e0a\uff0c\u82b1\u821e\u517c\u5bb9\u5199\u6cd5\n"
            f"{CMD_ARENA_QUERY}/{CMD_ARENA_DETAIL_QUERY} [uid/0-8/@\u67d0\u4eba]\uff1a"
            "\u67e5\u8be2\u771f\u5b9e JJC/PJJC \u6392\u540d\n"
            f"{CMD_ARENA_SUBSCRIBE_STATUS} [0-8]\uff1a\u67e5\u770b\u672c\u5730\u72b6\u6001\n"
            f"{CMD_ARENA_SETTINGS} 1013 [0-8]\uff1a\u4fee\u6539\u8bbe\u7f6e\n"
            f"{CMD_ARENA_MONITOR}/{CMD_ARENA_CANCEL_MONITOR}\uff1a"
            "\u5f00\u5173\u7ade\u6280\u573a\u67e5\u699c\u76d1\u63a7\n"
            "\u7ade\u6280\u573a\u6392\u884c\u699c1/\u516c\u4e3b\u7ade\u6280\u573a\u6392\u884c\u699c1\uff1a"
            "\u67e5\u770b\u5f53\u524d\u573a\u5206\u9875\u540d\u5355\n"
            f"{CMD_ARENA_STATUS}/{CMD_ARENA_KILLER}\uff1a\u67e5\u770b\u771f\u5b9e\u6392\u540d\u548c\u63a8\u9001\u72b6\u6001\n"
            f"{CMD_ARENA_KILLER_JJC_ON}/{CMD_ARENA_KILLER_JJC_OFF}\uff1a\u5f00\u5173 JJC \u76d1\u63a7\n"
            f"{CMD_ARENA_KILLER_PJJC_ON}/{CMD_ARENA_KILLER_PJJC_OFF}\uff1a\u5f00\u5173 PJJC \u76d1\u63a7\n"
            f"{CMD_ARENA_RENAME} 1 \u6635\u79f0\uff1a\u4fee\u6539\u6635\u79f0\n"
            f"{CMD_ARENA_PUSH_GROUP}/{CMD_ARENA_PUSH_PRIVATE} [0-8]\uff1a\u5f00\u542f/\u4fee\u6539\u6392\u540d\u53d8\u5316\u63d0\u9192\u63a8\u9001\u76ee\u6807\n"
            f"{CMD_ARENA_RECORD}/{CMD_ARENA_DUEL_RECORD} [0-8]\uff1a"
            "\u67e5\u8be2\u771f\u5b9e\u7ade\u6280\u573a/\u516c\u4e3b\u7ade\u6280\u573a\u5386\u53f2\n"
            f"{CMD_ARENA_DELETE_BINDING} 1\uff1a\u5220\u9664\u4e00\u4e2a\u7ed1\u5b9a\n"
            f"{CMD_ARENA_CLEAR_BINDINGS}\uff1a\u6e05\u7a7a\u7ade\u6280\u573a\u7ed1\u5b9a"
        )

    @filter.command(CMD_ARENA_DELETE_BINDING, alias={CMD_CHANNEL_ARENA_DELETE_BINDING})
    @require_pcr_access()
    async def arena_delete_binding(self, event: AstrMessageEvent):
        _mark_processed(event)
        blocked = self._arena_block_message(event)
        if blocked:
            yield event.plain_result(blocked)
            return

        _, payload = _payload_after_any(
            event,
            _arena_aliases(CMD_ARENA_DELETE_BINDING),
        )
        index = _first_token(payload, "")
        if not index:
            yield event.plain_result(f"\u683c\u5f0f\uff1a{CMD_ARENA_DELETE_BINDING} 1")
            return

        try:
            deleted = delete_arena_binding(self.storage, _sender_id(event), index)
        except (ValueError, IndexError):
            yield event.plain_result("\u672a\u627e\u5230\u8be5\u7ade\u6280\u573a\u7ed1\u5b9a\u5e8f\u53f7\u3002")
            return

        yield event.plain_result(
            f"\u5df2\u5220\u9664\u7ade\u6280\u573a\u7ed1\u5b9a\uff1a"
            f"{_format_arena_binding(deleted)}"
        )

    @filter.command(CMD_ARENA_CLEAR_BINDINGS, alias={CMD_CHANNEL_ARENA_CLEAR_BINDINGS})
    @require_pcr_access()
    async def arena_clear_bindings(self, event: AstrMessageEvent):
        _mark_processed(event)
        blocked = self._arena_block_message(event)
        if blocked:
            yield event.plain_result(blocked)
            return

        deleted = clear_arena_bindings(self.storage, _sender_id(event))
        yield event.plain_result(
            f"\u5df2\u6e05\u7a7a {len(deleted)} \u4e2a\u7ade\u6280\u573a\u7ed1\u5b9a\u3002"
        )

    @filter.command(CMD_ARENA_SUBSCRIBE_STATUS, alias={CMD_CHANNEL_ARENA_SUBSCRIBE_STATUS})
    @require_pcr_access()
    async def arena_subscribe_status(self, event: AstrMessageEvent):
        _mark_processed(event)
        blocked = self._arena_block_message(event)
        if blocked:
            yield event.plain_result(blocked)
            return

        _, payload = _payload_after_any(
            event,
            _arena_aliases(CMD_ARENA_SUBSCRIBE_STATUS),
        )
        bindings, message = self._arena_selected_bindings(event, payload)
        if message:
            yield event.plain_result(message)
            return
        yield event.plain_result(
            "\u7ade\u6280\u573a\u8ba2\u9605\u72b6\u6001\uff08\u672c\u5730\uff09\uff1a\n"
            f"{describe_arena_bindings(bindings)}"
        )

    @filter.command(CMD_ARENA_RENAME, alias={CMD_CHANNEL_ARENA_RENAME})
    @require_pcr_access()
    async def arena_rename(self, event: AstrMessageEvent):
        _mark_processed(event)
        blocked = self._arena_block_message(event)
        if blocked:
            yield event.plain_result(blocked)
            return

        _, payload = _payload_after_any(event, _arena_aliases(CMD_ARENA_RENAME))
        parts = payload.split(maxsplit=1)
        if len(parts) < 2:
            yield event.plain_result(f"\u683c\u5f0f\uff1a{CMD_ARENA_RENAME} 1 \u6635\u79f0")
            return

        try:
            renamed = rename_arena_binding(
                self.storage,
                _sender_id(event),
                parts[0],
                parts[1].strip(),
            )
        except (ValueError, IndexError):
            yield event.plain_result("\u672a\u627e\u5230\u8be5\u7ade\u6280\u573a\u7ed1\u5b9a\u5e8f\u53f7\u3002")
            return

        yield event.plain_result(
            f"\u5df2\u4fee\u6539\u7ade\u6280\u573a\u6635\u79f0\uff1a"
            f"{_format_arena_binding(renamed)}"
        )

    @filter.command(CMD_ARENA_SETTINGS, alias={CMD_CHANNEL_ARENA_SETTINGS})
    @require_pcr_access()
    async def arena_settings(self, event: AstrMessageEvent):
        _mark_processed(event)
        blocked = self._arena_block_message(event)
        if blocked:
            yield event.plain_result(blocked)
            return

        _, payload = _payload_after_any(event, _arena_aliases(CMD_ARENA_SETTINGS))
        settings, index = self._parse_arena_settings_payload(payload)
        if not settings:
            yield event.plain_result(
                f"\u683c\u5f0f\uff1a{CMD_ARENA_SETTINGS} 1013 [0-8]"
            )
            return

        try:
            normalized_settings = normalize_arena_settings(settings)
        except ValueError:
            yield event.plain_result(
                "\u7ade\u6280\u573a\u8bbe\u7f6e\u5fc5\u987b\u662f 4 \u4f4d\uff1a"
                "\u524d 3 \u4f4d\u4e3a 0/1\uff0c\u6700\u540e\u4e00\u4f4d\u4e3a 0..3\u3002"
            )
            return

        try:
            updated = apply_arena_settings(
                self.storage,
                _sender_id(event),
                normalized_settings,
                index,
            )
        except ValueError:
            yield event.plain_result("\u7ade\u6280\u573a\u5e8f\u53f7\u5fc5\u987b\u662f 0..8\u3002")
            return
        except IndexError:
            yield event.plain_result("\u672a\u627e\u5230\u8be5\u7ade\u6280\u573a\u7ed1\u5b9a\u5e8f\u53f7\u3002")
            return

        if not updated:
            yield event.plain_result(
                "\u8fd8\u6ca1\u6709\u7ade\u6280\u573a\u7ed1\u5b9a\u3002"
                f"\u5148\u53d1\u9001\uff1a{CMD_ARENA_BIND} UID [\u6635\u79f0]"
            )
            return
        yield event.plain_result(
            "\u5df2\u4fee\u6539\u7ade\u6280\u573a\u8bbe\u7f6e\uff08\u672c\u5730\uff09\uff1a\n"
            f"{describe_arena_bindings(updated)}"
        )

    @filter.command(CMD_ARENA_PUSH_GROUP)
    @require_pcr_access()
    async def arena_push_group(self, event: AstrMessageEvent):
        _mark_processed(event)
        blocked = self._arena_block_message(event)
        if blocked:
            yield event.plain_result(blocked)
            return

        if _is_private(event):
            yield event.plain_result(
                "\u8fd9\u662f\u7fa4\u63a8\u9001\u8bbe\u7f6e\uff0c\u8bf7\u5728\u7fa4\u91cc\u64cd\u4f5c\u3002"
            )
            return

        _, payload = _payload_after_any(event, (CMD_ARENA_PUSH_GROUP,))
        updated, message = self._set_arena_push(
            event,
            payload,
            f"session:{getattr(event, 'unified_msg_origin', '')}",
        )
        if message:
            yield event.plain_result(message)
            return
        self.storage.set_group(_group_key(event), {"arena_push": True})
        yield event.plain_result(
            f"\u5df2\u8bbe\u7f6e {len(updated)} \u4e2a\u7ade\u6280\u573a\u7ed1\u5b9a\u5728\u672c\u7fa4\u63a8\u9001\u3002"
        )

    @filter.command(CMD_ARENA_PUSH_PRIVATE)
    @require_pcr_access(allow_private=True)
    async def arena_push_private(self, event: AstrMessageEvent):
        _mark_processed(event)
        blocked = self._arena_block_message(event)
        if blocked:
            yield event.plain_result(blocked)
            return
        if not _is_private(event):
            yield event.plain_result(
                "\u79c1\u804a\u63a8\u9001\u8bf7\u79c1\u804a\u673a\u5668\u4eba\u8bbe\u7f6e\uff0c"
                "\u6216\u5728\u7fa4\u91cc\u4f7f\u7528\u5728\u672c\u7fa4\u63a8\u9001\u3002"
            )
            return

        _, payload = _payload_after_any(event, (CMD_ARENA_PUSH_PRIVATE,))
        updated, message = self._set_arena_push(
            event,
            payload,
            f"session:{getattr(event, 'unified_msg_origin', '')}",
        )
        if message:
            yield event.plain_result(message)
            return
        yield event.plain_result(
            f"\u5df2\u8bbe\u7f6e {len(updated)} \u4e2a\u7ade\u6280\u573a\u7ed1\u5b9a\u6539\u4e3a\u79c1\u804a\u63a8\u9001\u3002"
        )

    @filter.command(CMD_ARENA_DETAIL_QUERY, alias={CMD_CHANNEL_ARENA_DETAIL_QUERY})
    @require_pcr_access()
    async def arena_detail_query(self, event: AstrMessageEvent):
        _mark_processed(event)
        blocked = self._arena_block_message(event)
        if blocked:
            yield event.plain_result(blocked)
            return

        _, payload = _payload_after_any(event, _arena_aliases(CMD_ARENA_DETAIL_QUERY))
        yield event.plain_result(
            await self._arena_backend_pending_reply(
                event,
                payload,
                "\u8be6\u7ec6\u67e5\u8be2",
            )
        )

    @filter.command(CMD_ARENA_RECORD, alias={CMD_CHANNEL_ARENA_RECORD})
    @require_pcr_access()
    async def arena_record(self, event: AstrMessageEvent):
        _mark_processed(event)
        blocked = self._arena_block_message(event)
        if blocked:
            yield event.plain_result(blocked)
            return

        yield event.plain_result(await self.arena.history("jjc", user=_sender_id(event), account="main"))

    @filter.command(CMD_ARENA_DUEL_RECORD, alias={CMD_CHANNEL_ARENA_DUEL_RECORD})
    @require_pcr_access()
    async def arena_duel_record(self, event: AstrMessageEvent):
        _mark_processed(event)
        blocked = self._arena_block_message(event)
        if blocked:
            yield event.plain_result(blocked)
            return

        yield event.plain_result(await self.arena.history("pjjc", user=_sender_id(event), account="main"))

    @filter.command(CMD_ARENA_MONITOR, alias=ARENA_MONITOR_ON_ALIASES)
    @require_pcr_access()
    async def arena_monitor_on(self, event: AstrMessageEvent):
        _mark_processed(event)
        blocked = self._arena_block_message(event)
        if blocked:
            yield event.plain_result(blocked)
            return
        command = match_plain_command(
            _normalized_text(event),
            (CMD_ARENA_MONITOR, *tuple(ARENA_MONITOR_ON_ALIASES)),
        )
        if command == CMD_ARENA_MONITOR:
            async for result in self._arena_list_monitor_start(event):
                yield result
            return
        yield event.plain_result(await self._arena_monitor_on_reply(event))

    @filter.command(CMD_ARENA_CANCEL_MONITOR, alias=ARENA_MONITOR_OFF_ALIASES)
    @require_pcr_access()
    async def arena_monitor_off(self, event: AstrMessageEvent):
        _mark_processed(event)
        blocked = self._arena_block_message(event)
        if blocked:
            yield event.plain_result(blocked)
            return
        command = match_plain_command(
            _normalized_text(event),
            (CMD_ARENA_CANCEL_MONITOR, *tuple(ARENA_MONITOR_OFF_ALIASES)),
        )
        if command == CMD_ARENA_CANCEL_MONITOR:
            self.storage.set_group(
                _group_key(event),
                {"arena_monitor": {"enabled": False, "monitor_qq": _sender_id(event)}},
            )
            yield event.plain_result("\u7ade\u6280\u573a\u67e5\u699c\u76d1\u63a7\u5df2\u5173\u95ed\u3002")
            return
        yield event.plain_result(self._arena_monitor_off_reply(event))

    @filter.command(CMD_ARENA_STATUS, alias=ARENA_STATUS_ALIASES)
    @require_pcr_access()
    async def arena_status(self, event: AstrMessageEvent):
        _mark_processed(event)
        blocked = self._arena_block_message(event)
        if blocked:
            yield event.plain_result(blocked)
            return
        yield event.plain_result(await self._arena_status_reply(event))

    @filter.command(
        CMD_ARENA_KILLER_JJC_ON,
        alias={
            CMD_ARENA_KILLER_JJC_OFF,
            CMD_ARENA_KILLER_PJJC_ON,
            CMD_ARENA_KILLER_PJJC_OFF,
        },
    )
    @require_pcr_access()
    async def arena_killer_toggle(self, event: AstrMessageEvent):
        _mark_processed(event)
        blocked = self._arena_block_message(event)
        if blocked:
            yield event.plain_result(blocked)
            return

        command = match_plain_command(
            _normalized_text(event),
            (
                CMD_ARENA_KILLER_JJC_ON,
                CMD_ARENA_KILLER_JJC_OFF,
                CMD_ARENA_KILLER_PJJC_ON,
                CMD_ARENA_KILLER_PJJC_OFF,
            ),
        )
        yield event.plain_result(self._arena_killer_toggle_reply(event, command or ""))

    def _arena_block_message(self, event: AstrMessageEvent) -> str | None:
        blocked = self._blocked_message(event)
        if blocked:
            return blocked
        if not _is_group_feature_enabled(self.storage, event):
            return GROUP_DISABLED_MESSAGE
        return None

    def _arena_selected_bindings(
        self,
        event: AstrMessageEvent,
        payload: str,
    ) -> tuple[list[dict], str | None]:
        index = _first_token(payload, "0")
        try:
            bindings = select_arena_bindings(self.storage, _sender_id(event), index)
        except ValueError:
            return [], "\u7ade\u6280\u573a\u5e8f\u53f7\u5fc5\u987b\u662f 0..8\u3002"
        except IndexError:
            return [], "\u672a\u627e\u5230\u8be5\u7ade\u6280\u573a\u7ed1\u5b9a\u5e8f\u53f7\u3002"

        if not bindings:
            return [], (
                "\u8fd8\u6ca1\u6709\u7ade\u6280\u573a\u7ed1\u5b9a\u3002"
                f"\u5148\u53d1\u9001\uff1a{CMD_ARENA_BIND} UID [\u6635\u79f0]"
            )
        return bindings, None

    def _parse_arena_settings_payload(self, payload: str) -> tuple[str | None, str]:
        settings = None
        index = "0"
        for part in payload.split():
            if len(part) == 4:
                settings = part
            else:
                index = part
        return settings, index

    def _set_arena_push(
        self,
        event: AstrMessageEvent,
        payload: str,
        target: str | None,
    ) -> tuple[list[dict], str | None]:
        index = _first_token(payload, "0")
        try:
            updated = set_arena_push_target(
                self.storage,
                _sender_id(event),
                target,
                index,
            )
        except ValueError:
            return [], "\u7ade\u6280\u573a\u5e8f\u53f7\u5fc5\u987b\u662f 0..8\u3002"
        except IndexError:
            return [], "\u672a\u627e\u5230\u8be5\u7ade\u6280\u573a\u7ed1\u5b9a\u5e8f\u53f7\u3002"

        if not updated:
            return [], (
                "\u8fd8\u6ca1\u6709\u7ade\u6280\u573a\u7ed1\u5b9a\u3002"
                f"\u5148\u53d1\u9001\uff1a{CMD_ARENA_BIND} UID [\u6635\u79f0]"
            )
        return updated, None

    async def _ensure_default_arena_binding(self, event: AstrMessageEvent) -> str | None:
        sender = _sender_id(event)
        try:
            existing = select_arena_bindings(self.storage, sender, "0")
        except (ValueError, IndexError):
            existing = []
        if existing:
            return None

        if not self.storage.get_account(sender):
            return (
                "\u8fd8\u6ca1\u6709\u7ade\u6280\u573a\u7ed1\u5b9a\uff0c"
                f"\u4e5f\u6ca1\u6709\u79c1\u804a\u7ed1\u5b9a PCR \u8d26\u53f7\u3002\u5148\u53d1\u9001\uff1a{CMD_BIND} \u6e20\u9053\u670d UID <string...>"
            )

        try:
            real_status = await self.real_api.clan_status(sender, account="main")
        except RealAPIError as exc:
            return (
                "\u8fd8\u6ca1\u6709\u7ade\u6280\u573a\u7ed1\u5b9a\uff0c"
                f"\u4e14\u65e0\u6cd5\u4ece\u771f\u5b9e\u8d26\u53f7\u8bfb\u53d6 UID\uff1a{exc}"
            )

        account = real_status.get("account") or {}
        uid = str(account.get("uid") or "").strip()
        if not uid:
            return (
                "\u8fd8\u6ca1\u6709\u7ade\u6280\u573a\u7ed1\u5b9a\u3002"
                f"\u5148\u53d1\u9001\uff1a{CMD_ARENA_BIND} UID [\u6635\u79f0]"
            )

        channel = str(account.get("channel") or "")
        platform = "channel" if "\u6e20" in channel else "bili"
        bind_arena_uid(self.storage, sender, uid, uid, platform)
        return None

    async def _arena_monitor_on_reply(self, event: AstrMessageEvent) -> str:
        if _is_private(event):
            return "\u7ade\u6280\u573a\u6392\u540d\u63d0\u9192\u8bf7\u5728\u9700\u8981\u63a8\u9001\u7684\u7fa4\u91cc\u5f00\u542f\u3002"

        ensure_message = await self._ensure_default_arena_binding(event)
        if ensure_message:
            return ensure_message

        target = f"session:{getattr(event, 'unified_msg_origin', '')}"
        _, payload = _payload_after_any(
            event,
            (CMD_ARENA_MONITOR, *tuple(ARENA_MONITOR_ON_ALIASES)),
        )
        updated, message = self._set_arena_push(event, payload, target)
        if message:
            return message

        self.storage.set_group(_group_key(event), {"arena_push": True})
        lines = ["\u7ade\u6280\u573a\u6392\u540d\u63d0\u9192\u5df2\u5f00\u542f\uff08\u672c\u7fa4\u63a8\u9001\uff09\uff1a"]
        for entry in updated:
            result = await self.arena.query(
                str(entry.get("uid", "")),
                str(entry.get("nickname", "")),
                user=_sender_id(event),
                account="main",
            )
            update_arena_entry_from_result(entry, result, pause_on_login=False)
            display_entry = self._arena_display_entry(entry, result)
            lines.append(f"{_format_arena_binding(display_entry)}\n{result.message}")
        self.storage.save()
        return "\n".join(lines)

    def _arena_monitor_off_reply(self, event: AstrMessageEvent) -> str:
        if _is_private(event):
            return "\u7ade\u6280\u573a\u6392\u540d\u63d0\u9192\u662f\u7fa4\u63a8\u9001\u5f00\u5173\uff0c\u8bf7\u5728\u7fa4\u91cc\u5173\u95ed\u3002"

        _, payload = _payload_after_any(
            event,
            (CMD_ARENA_CANCEL_MONITOR, *tuple(ARENA_MONITOR_OFF_ALIASES)),
        )
        updated, message = self._set_arena_push(event, payload, None)
        if message:
            return message

        self.storage.set_group(_group_key(event), {"arena_push": False})
        return f"\u7ade\u6280\u573a\u6392\u540d\u63d0\u9192\u5df2\u5173\u95ed\uff1a{len(updated)} \u4e2a\u7ed1\u5b9a\u5df2\u505c\u6b62\u63a8\u9001\u3002"

    async def _arena_list_monitor_start(self, event: AstrMessageEvent):
        if _is_private(event):
            yield event.plain_result("\u7ade\u6280\u573a\u76d1\u63a7\u8bf7\u5728\u9700\u8981\u67e5\u699c\u7684\u7fa4\u91cc\u5f00\u542f\u3002")
            return
        sender = _sender_id(event)
        if not self.storage.get_account(sender):
            yield event.plain_result(NO_BOUND_ACCOUNT_MESSAGE)
            return

        account = self.storage.get_account(sender) or {}
        player = account.get("nickname") or account.get("uid") or sender
        yield event.plain_result(
            "\u6b63\u5728\u767b\u5f55\u8d26\u53f7\uff0c\u8bf7\u8010\u5fc3\u7b49\u5f85\uff0c"
            f"\u5f53\u524d\u76d1\u63a7\u73a9\u5bb6\u4e3a{player}"
        )
        try:
            payload = await self.real_api.arena_ranking(
                "jjc",
                page=1,
                limit=1,
                user=sender,
                account="main",
            )
        except RealAPIError as exc:
            yield event.plain_result(f"\u7ade\u6280\u573a\u76d1\u63a7\u5f00\u542f\u5931\u8d25\uff1a{exc}")
            return

        real_account = payload.get("account") or {}
        player = real_account.get("user_name") or account.get("nickname") or account.get("uid") or sender
        group_key = _group_key(event)
        monitor_id = make_monitor_id(group_key, sender)
        self.storage.set_group(
            group_key,
            {
                "arena_monitor": {
                    "enabled": True,
                    "monitor_qq": sender,
                    "monitor_id": monitor_id,
                    "monitor_session": str(getattr(event, "unified_msg_origin", "")),
                }
            },
        )
        yield event.plain_result(
            "\u5f00\u59cb\u76d1\u63a7\u4e2d, \u53ef\u4ee5\u53d1\u9001\u3010\u53d6\u6d88\u7ade\u6280\u573a\u76d1\u63a7\u3011\u6216\u8005\u9876\u53f7\u9000\u51fa\n"
            f"#\u76d1\u63a7\u7f16\u53f7{monitor_id}"
        )

    @require_pcr_access()
    async def _arena_ranking_page(self, event: AstrMessageEvent, kind: str, page: int):
        blocked = self._arena_block_message(event)
        if blocked:
            yield event.plain_result(blocked)
            return
        sender = _sender_id(event)
        if not self.storage.get_account(sender):
            yield event.plain_result(NO_BOUND_ACCOUNT_MESSAGE)
            return
        title = "\u516c\u4e3b\u7ade\u6280\u573a" if kind == "pjjc" else "\u7ade\u6280\u573a"
        yield event.plain_result(f"\u6b63\u5728\u67e5\u8be2\uff0c\u8bf7\u7a0d\u7b49\u3002\u5f53\u524d\u4e3a{title}\u6392\u884c\u699c\u7b2c{page}\u9875")
        yield event.plain_result(
            await self.arena.ranking_text(kind, page=page, user=sender, account="main")
        )

    @require_pcr_access()
    async def _arena_solution_query(self, event: AstrMessageEvent, region: int, payload: str):
        teams = []
        image_path = None
        if _has_image_message(event):
            if self.image_recognizer is None:
                yield event.plain_result("识图组件未就绪，请使用文字角色名查询。")
                return
            yield event.plain_result("正在识别截图中的防守阵容，请稍候。")
            try:
                image_path = await _first_image_path(event)
                if not image_path:
                    raise ImageRecognitionError("未能读取图片")
                side = 'all' if payload.strip() == '全部' else 'defense'
                async with self._arena_image_lock:
                    await asyncio.to_thread(self.image_recognizer.load_cached_templates)
                    teams = await asyncio.to_thread(
                        self.image_recognizer.recognize_teams, image_path, side=side
                    )
            except (ImageRecognitionError, OSError, ValueError) as exc:
                yield event.plain_result(f"阵容识别失败：{exc}\n请发送清晰的游戏原图，或裁剪为五人头像横排。")
                return
        elif payload.strip():
            for number, text in enumerate(payload.split('#')[:4], 1):
                ids, unknown = parse_team_names(text)
                if unknown or len(ids) != 5 or len(set(ids)) != 5:
                    yield event.plain_result(f"第{number}队解析失败：需要五名不重复角色。无法识别的内容：{unknown or '-'}")
                    return
                teams.append({'ids': ids, 'label': f'防守队伍 {number}'})
        else:
            yield event.plain_result("请发送“怎么拆”并附上阵容截图，或“怎么拆 五名角色”。多队文字使用 # 分隔。")
            return
        if not teams or len(teams) > (6 if payload.strip() == '全部' else 3):
            yield event.plain_result("一次支持一至三队防守阵容；完整对战图默认读取右侧三队。")
            return

        icon_provider = self.image_recognizer.get_icon if self.image_recognizer else None
        for i, team in enumerate(teams, 1):
            label = str(team.get('label') or '')
            for prefix, translated in (('defense_', '防守队伍 '), ('attack_', '进攻队伍 '), ('team_', '队伍 ')):
                if label.startswith(prefix):
                    team['label'] = translated + label[len(prefix):]
        names = '\n'.join(
            f"{team.get('label') or f'第{i}队'}：" + ' '.join(name_for_id(cid) for cid in team['ids'])
            for i, team in enumerate(teams, 1)
        )
        yield event.plain_result(names)
        path = self._pcr_image_path('arena_recognition')
        try:
            await asyncio.to_thread(render_arena_recognition, teams, path, icon_provider)
            yield event.chain_result(MessageChain().file_image(str(path)).chain)
        except (OSError, ValueError, RuntimeError) as exc:
            logger.warning(f"PCR recognition card render failed: {type(exc).__name__}")
        recognition_only = payload.strip() == '全部' or _normalized_text(event).startswith(('识别阵容', '阵容识别'))
        if recognition_only:
            return
        if len(teams) > 1:
            async for reply in self._arena_combined_solutions(event, teams, region, icon_provider):
                yield reply
            return
        if not getattr(self.pcrdfans, 'api_key', ''):
            web_client = getattr(self, 'arena_web', None)
            if web_client and web_client.enabled:
                for number, team in enumerate(teams, 1):
                    link = pcrdfans_battle_url(team['ids'])
                    yield event.plain_result(f'正在通过作业网网页查询第{number}队，请稍候。多队查询会间隔限速。')
                    path = self._pcr_image_path('arena_web')
                    try:
                        result = await web_client.query(team['ids'], path, region=region)
                        if result.empty:
                            yield event.plain_result(f'第{number}队：作业网页没有找到相关结果。\n{link}')
                        else:
                            yield event.chain_result(MessageChain().file_image(str(result.path)).chain)
                            detail = f'展示网页前{result.count}条'
                            if result.count < 5:
                                detail = f'当前查询页仅有{result.count}条匹配作业，已全部展示'
                            yield event.plain_result(f'第{number}队作业来自 pcrdfans.com，{detail}。查询链接：\n{result.url}')
                    except ArenaWebQueryError as exc:
                        yield event.plain_result(f'第{number}队网页查询未完成：{exc}\n手动查询：{link}')
            else:
                links = '\n'.join(f"第{i}队作业：{pcrdfans_battle_url(t['ids'])}" for i,t in enumerate(teams, 1))
                yield event.plain_result("角色识别已完成。尚未配置 pcrdfans 授权 Key，网页查询也未开启。以下链接已带入识别阵容：\n" + links)
            return
        for number, team in enumerate(teams, 1):
            try:
                result = await self.pcrdfans.query(team['ids'], _sender_id(event), region=region)
            except PcrdFansError as exc:
                yield event.plain_result(f"第{number}队解法查询失败：{exc}")
                continue
            path = self._pcr_image_path('arena_solutions')
            try:
                await asyncio.to_thread(
                    render_arena_solutions, team['ids'], result.entries, path, icon_provider, region
                )
                yield event.chain_result(MessageChain().file_image(str(path)).chain)
            except (OSError, ValueError, RuntimeError):
                yield event.plain_result(result.format_text())

    async def _arena_combined_solutions(self, event, teams, region, icon_provider):
        web_client = getattr(self, 'arena_web', None)
        use_api = bool(getattr(self.pcrdfans, 'api_key', ''))
        links = '\n'.join(f"第{i}队：{pcrdfans_battle_url(team['ids'])}" for i, team in enumerate(teams, 1))
        if not use_api and not (web_client and web_client.enabled):
            yield event.plain_result('尚未开启网页查询或配置作业网 Key。\n' + links)
            return
        yield event.plain_result(f'正在统一查询{len(teams)}队并筛选不重人组合，完成后一次返回长图。网页模式需间隔限速，请稍候。')
        groups, failures = [], []
        for index, team in enumerate(teams, 1):
            if not self._pcr_event_allowed(event):
                return
            try:
                if use_api:
                    result = await self.pcrdfans.query(team['ids'], _sender_id(event), region=region)
                    candidates = []
                    for position, entry in enumerate(result.entries[:10]):
                        try:
                            ids = [id_from_unit_id(int(unit['id'] if isinstance(unit, dict) else unit))
                                   for unit in entry.get('atk', [])]
                            metadata = f"作业 #{position + 1}\n赞 {int(entry.get('up') or 0)} / 踩 {int(entry.get('down') or 0)}"
                            candidates.append({'ids': ids, 'metadata': metadata})
                        except (KeyError, TypeError, ValueError):
                            continue
                else:
                    result = await web_client.query(team['ids'], self._pcr_image_path('arena_web'),
                                                    region=region, include_candidates=True)
                    candidates = result.candidates
                    skipped = result.count - len(candidates)
                    if skipped > 0:
                        failures.append(f'第{index}队网页返回{result.count}条，其中{skipped}条头像身份无法可靠确认，未参与组合。')
                groups.append(candidates)
            except (ArenaWebQueryError, PcrdFansError) as exc:
                groups.append([])
                failures.append(f'第{index}队查询未完成：{exc}')
        if not self._pcr_event_allowed(event):
            return
        plans = build_disjoint_team_plans(groups, max_plans=10)
        counts = [len(group) for group in groups]
        path = self._pcr_image_path('arena_combined')
        try:
            payload = await asyncio.to_thread(compose_team_plans_bytes, teams, plans, icon_provider, region, counts)
            if not self._pcr_event_allowed(event):
                return
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(payload)
            yield event.chain_result(MessageChain().file_image(str(path)).chain)
        except (OSError, ValueError, RuntimeError):
            yield event.plain_result('联合解法长图生成失败，未返回不完整的逐队方案。\n' + links)
            return
        if len(plans) >= 5:
            summary = f'已汇总{len(plans)}套完整组合，每套{len(teams) * 5}个角色不重复；不同方案之间是备选关系。'
        elif plans:
            summary = f'当前候选仅能组成{len(plans)}套完整不重人方案，已全部展示，未凑数。'
        else:
            summary = '当前候选没有完整的不重人组合，不能直接组成三队。' if len(teams) == 3 else '当前候选没有完整的不重人组合。'
        summary += '\n各队候选：' + ' / '.join(map(str, counts))
        if failures:
            summary += '\n' + '\n'.join(failures)
        yield event.plain_result(summary + '\n数据来源：pcrdfans.com；网页作业组合不等于战斗模拟。\n' + links)

    def _pcr_image_path(self, category):
        return os.path.join(os.path.dirname(__file__), 'data', 'reports', f'{category}_{uuid.uuid4().hex}.png')

    @filter.command(CMD_ARENA_TEMPLATES)
    @require_pcr_access()
    async def arena_update_templates(self, event: AstrMessageEvent):
        _mark_processed(event)
        if self._admin_block_message(event):
            return
        if self.image_recognizer is None:
            yield event.plain_result("识图组件未就绪。")
            return
        yield event.plain_result("正在更新角色头像库，请稍候。")
        async with self._arena_image_lock:
            try:
                roster = await self.real_api.characters()
                extend_character_roster(roster.get('characters', []), self._chara_cache)
            except RealAPIError:
                pass
            result = await asyncio.to_thread(self.image_recognizer.warm_templates)
        yield event.plain_result(f"角色头像库更新完成：{result}")

    @filter.command(CMD_ARENA_CONTINUOUS)
    @require_pcr_access()
    async def arena_continuous_start(self, event: AstrMessageEvent):
        _mark_processed(event)
        self._arena_image_sessions[(_sender_id(event), _group_key(event))] = time.monotonic() + 600
        yield event.plain_result("已开启连续识图，十分钟内发送阵容截图即可查询。发送“结束查询”退出。")

    @filter.command(CMD_ARENA_CONTINUOUS_END)
    @require_pcr_access()
    async def arena_continuous_end(self, event: AstrMessageEvent):
        _mark_processed(event)
        self._arena_image_sessions.pop((_sender_id(event), _group_key(event)), None)
        yield event.plain_result("已结束连续识图。")

    async def _arena_status_reply(self, event: AstrMessageEvent) -> str:
        ensure_message = await self._ensure_default_arena_binding(event)
        if ensure_message:
            return ensure_message

        _, payload = _payload_after_any(
            event,
            (CMD_ARENA_STATUS, *tuple(ARENA_STATUS_ALIASES)),
        )
        bindings, message = self._arena_selected_bindings(event, payload)
        if message:
            return message

        lines = ["\u7ade\u6280\u573a\u72b6\u6001\uff1a"]
        for entry in bindings:
            result = await self.arena.query(
                str(entry.get("uid", "")),
                str(entry.get("nickname", "")),
                user=_sender_id(event),
                account="main",
            )
            display_entry = self._arena_display_entry(entry, result)
            push_status = "\u5df2\u8bbe\u7f6e" if entry.get("push_target") else "\u672a\u8bbe\u7f6e"
            lines.append(
                f"{_format_arena_binding(display_entry)}\n"
                f"\u63a8\u9001\uff1a{push_status}\n"
                f"{result.message}"
            )
        return "\n".join(lines)

    def _arena_killer_toggle_reply(self, event: AstrMessageEvent, command: str) -> str:
        if command not in {
            CMD_ARENA_KILLER_JJC_ON,
            CMD_ARENA_KILLER_JJC_OFF,
            CMD_ARENA_KILLER_PJJC_ON,
            CMD_ARENA_KILLER_PJJC_OFF,
        }:
            return "\u672a\u8bc6\u522b\u7684\u7ade\u6280\u573a\u6740\u624b\u5f00\u5173\u3002"

        _, payload = _payload_after_any(
            event,
            (
                CMD_ARENA_KILLER_JJC_ON,
                CMD_ARENA_KILLER_JJC_OFF,
                CMD_ARENA_KILLER_PJJC_ON,
                CMD_ARENA_KILLER_PJJC_OFF,
            ),
        )
        index = _first_token(payload, "0")
        bindings, message = self._arena_selected_bindings(event, index)
        if message:
            return message

        first_settings = str(bindings[0].get("settings") or "1100")
        updated_settings = _arena_settings_with_flags(
            first_settings,
            jjc=(command == CMD_ARENA_KILLER_JJC_ON)
            if command in {CMD_ARENA_KILLER_JJC_ON, CMD_ARENA_KILLER_JJC_OFF}
            else None,
            pjjc=(command == CMD_ARENA_KILLER_PJJC_ON)
            if command in {CMD_ARENA_KILLER_PJJC_ON, CMD_ARENA_KILLER_PJJC_OFF}
            else None,
        )
        try:
            updated = apply_arena_settings(
                self.storage,
                _sender_id(event),
                updated_settings,
                index,
            )
        except ValueError:
            return "\u7ade\u6280\u573a\u5e8f\u53f7\u5fc5\u987b\u662f 0..8\u3002"
        except IndexError:
            return "\u672a\u627e\u5230\u8be5\u7ade\u6280\u573a\u7ed1\u5b9a\u5e8f\u53f7\u3002"

        return (
            "\u7ade\u6280\u573a\u6740\u624b\u8bbe\u7f6e\u5df2\u66f4\u65b0\uff1a\n"
            f"{describe_arena_bindings(updated)}"
        )

    def _arena_display_entry(self, entry: dict, result) -> dict:
        display_entry = dict(entry)
        if result.nickname:
            display_entry["nickname"] = result.nickname
        if result.platform:
            display_entry["platform"] = result.platform
        return display_entry

    async def _arena_backend_pending_reply(
        self,
        event: AstrMessageEvent,
        payload: str,
        title: str,
    ) -> str:
        try:
            bindings, message = resolve_arena_query_targets(
                self.storage,
                _sender_id(event),
                payload,
            )
        except ValueError:
            return "\u7ade\u6280\u573a\u5e8f\u53f7\u5fc5\u987b\u662f 0..8\u3002"
        except IndexError:
            return "\u672a\u627e\u5230\u8be5\u7ade\u6280\u573a\u7ed1\u5b9a\u5e8f\u53f7\u3002"
        if message:
            return message

        lines = [f"{title}\uff1a"]
        for entry in bindings:
            result = await self.arena.query(
                str(entry.get("uid", "")),
                str(entry.get("nickname", "")),
                user=_sender_id(event),
                account="main",
            )
            display_entry = self._arena_display_entry(entry, result)
            lines.append(f"{_format_arena_binding(display_entry)}\n{result.message}")
        return "\n".join(lines)

    @filter.command(CMD_CLAN_OUT_DAMAGE_MONITOR, alias=set(CLAN_COMMAND_ALIASES))
    @require_pcr_access()
    async def clan_command(self, event: AstrMessageEvent):
        _mark_processed(event)
        blocked = self._blocked_message(event)
        if blocked:
            yield event.plain_result(blocked)
            return
        if not _is_group_feature_enabled(self.storage, event):
            yield event.plain_result(GROUP_DISABLED_MESSAGE)
            return

        if _is_private(event):
            yield event.plain_result(
                "\u4f1a\u6218\u548c\u51fa\u5200\u6307\u4ee4\u662f\u7fa4\u8bbe\u7f6e\uff0c"
                "\u8bf7\u5728\u7fa4\u91cc\u64cd\u4f5c\u3002"
            )
            return

        command = match_plain_command(_normalized_text(event), CLAN_PLAIN_COMMANDS)
        if not command:
            command = CMD_CLAN_OUT_DAMAGE_MONITOR

        command_key = self._clan_command_key(event, command)
        sender = _sender_id(event)
        group_key = _group_key(event)
        clan = self.storage.data.get("clan", {}).get(group_key, {})
        account_qq = clan_command_account_qq(sender, clan)
        account = self.storage.get_account(account_qq) if account_qq else None
        payload = _payload_after(event, command)
        if command_key in COORDINATION_COMMANDS:
            name = clan.get('monitor_player_name') if clan.get('monitor_qq') == sender else ''
            local_reply = handle_clan_coordination(
                command_key, payload, clan, sender,
                player_name=name or (account or {}).get('user_name', ''),
                is_admin=is_admin_qq(sender, self.admin_qqs, self.blocked_qqs),
            )
            self.storage.set_clan_state(group_key, clan)
            yield event.plain_result(local_reply)
            return
        if clan_command_needs_account(command_key) and not account:
            yield event.plain_result(NO_BOUND_ACCOUNT_MESSAGE)
            return

        if command_key == 'out_damage_monitor_on':
            yield event.plain_result('正在读取你的游戏账号与公会数据，请稍候。')
        real_status, real_mylog, real_error = await self._clan_real_payload(
            command_key,
            user=account_qq,
            account="main" if account else None,
        )
        if real_error:
            yield event.plain_result(f"读取真实会战数据失败：{real_error}")
            return

        if real_status:
            real_status = merge_clan_history(clan, real_status)
            clan['monitor_player_name'] = (real_status.get('account') or {}).get('user_name') or ''
            if command_key == 'out_damage_monitor_on':
                update_clan_damage_state(clan, real_status)
            self.storage.set_clan_state(group_key, clan)

        updates = clan_state_update_for_command(command_key, sender)
        if command_key == "out_damage_monitor_on":
            updates["monitor_session"] = str(getattr(event, "unified_msg_origin", ""))
            updates["monitor_id"] = make_monitor_id(group_key, sender)
        if updates:
            self.storage.set_clan_state(group_key, updates)
            clan = self.storage.data.get("clan", {}).get(group_key, {})

        report_commands = {
            'current_report', 'my_report', 'today_report', 'yesterday_report',
            'today_damage', 'yesterday_damage', 'damage_detail',
        }
        if real_status and command_key in report_commands:
            try:
                real_status = select_clan_report(real_status, command_key, payload)
                if command_key == 'damage_detail':
                    detail = await self.real_api.clan_history_detail(
                        real_status['report_history_id'], user=account_qq, account='main'
                    )
                    real_status['unit_damage_detail'] = detail.get('units') or []
            except (ValueError, RealAPIError) as exc:
                yield event.plain_result(str(exc))
                return
            path = self._pcr_image_path('clan_report')
            if clan.get('image_mode', True) is False and command_key != 'damage_detail':
                yield event.plain_result(build_current_report_text(real_status))
                return
            try:
                if command_key == 'damage_detail':
                    provider = self.image_recognizer.get_icon if self.image_recognizer else None
                    await asyncio.to_thread(render_clan_damage_detail, real_status, path, provider)
                else:
                    await asyncio.to_thread(render_clan_report, real_status, path, command_key)
                yield event.chain_result(MessageChain().file_image(str(path)).chain)
            except (OSError, ValueError, RuntimeError) as exc:
                logger.warning(f'PCR clan report image failed: {type(exc).__name__}')
                yield event.plain_result(build_current_report_text(real_status))
            return
        if real_status and command_key == 'status':
            if clan.get('image_mode', True) is False:
                yield event.plain_result(build_clan_status_text(real_status, clan, account))
                return
            path = self._pcr_image_path('clan_status')
            try:
                await asyncio.to_thread(render_clan_status, real_status, path, clan, account)
                yield event.chain_result(MessageChain().file_image(str(path)).chain)
            except (OSError, ValueError, RuntimeError) as exc:
                logger.warning(f'PCR clan status image failed: {type(exc).__name__}')
                yield event.plain_result(build_clan_status_text(real_status, clan, account))
            return
        if real_status and command_key == 'urge':
            today = select_clan_report(real_status, 'today_damage')
            yield event.plain_result(build_damage_count_summary(today))
            return

        reply = build_clan_command_reply(
            command_key,
            clan,
            account,
            real_status=real_status,
            real_mylog=real_mylog,
        )
        if real_error and real_status is None:
            reply = f"{reply}\n\u771f\u5b9e\u4f1a\u6218\u67e5\u8be2\u5931\u8d25\uff1a{real_error}"
        image_text = self._clan_report_image_text(command_key, real_status)
        if image_text:
            image_path = self._render_clan_report_image(group_key, command_key, image_text)
            yield event.chain_result(MessageChain().file_image(str(image_path)).chain)
            return
        yield event.plain_result(reply)

    def _clan_command_key(self, event: AstrMessageEvent, command: str) -> str:
        if command == CMD_CLAN_LEGACY_MONITOR:
            payload = _payload_after(event, command)
            if _switch_enabled(payload):
                return "out_damage_monitor_on"
            return "out_damage_monitor_off"
        if command == CMD_CLAN_LEGACY_STATUS:
            return "status"
        return CLAN_COMMAND_ACTIONS.get(command, "status")

    async def _clan_real_payload(
        self,
        command_key: str,
        user: str | None = None,
        account: str | None = None,
    ):
        status_commands = {
            'urge',
            "out_damage_monitor_on",
            "status",
            "current_report",
            "today_report",
            "today_damage",
            "damage_detail",
            "my_report",
            "yesterday_report",
            "yesterday_damage",
        }
        if command_key not in status_commands:
            return None, None, None

        try:
            real_status = await self.real_api.clan_status(user, account=account)
            real_mylog = None
            return real_status, real_mylog, None
        except RealAPIError as exc:
            return None, None, str(exc)

    def _clan_report_image_text(self, command_key: str, real_status: dict | None) -> str:
        if not real_status:
            return ""
        if command_key in {"today_damage", "today_report"}:
            return build_damage_count_summary(real_status)
        if command_key in {"current_report", "damage_detail"}:
            return build_current_report_text(real_status)
        return ""

    def _render_clan_report_image(self, group_key: str, command_key: str, text: str):
        safe_group = "".join(char for char in str(group_key) if char.isalnum())[-32:] or "group"
        path = os.path.join(
            os.path.dirname(__file__),
            "data",
            "reports",
            f"{safe_group}_{command_key}.png",
        )
        return render_text_image(text, path)

    async def _monitor_loop(self):
        await asyncio.sleep(10)
        while True:
            try:
                await self._poll_arena_monitors()
                await self._poll_clan_monitors()
            except Exception as exc:
                logger.warning(f"PCR monitor loop error: {type(exc).__name__}: {exc}")
            await asyncio.sleep(self.monitor_interval_seconds)

    async def _poll_arena_monitors(self):
        arena_data = self.storage.data.get("arena", {})
        if not isinstance(arena_data, dict):
            return

        dirty = False
        for user_id, bindings in list(arena_data.items()):
            if not self._user_allowed(user_id) or not isinstance(bindings, list):
                continue
            for entry in bindings:
                if (
                    not isinstance(entry, dict)
                    or entry.get("manual_pause")
                    or not entry.get("push_target")
                ):
                    continue
                settings = str(entry.get("settings") or "1100")
                if settings[:2] == "00" and settings[3] == "0":
                    continue
                target = entry.get("push_target")
                if not self._monitor_target_allowed(user_id, target):
                    continue
                if not self.storage.get_account(user_id):
                    entry["push_target"] = None
                    entry["manual_pause"] = True
                    entry["pause_reason"] = "account_missing"
                    dirty = True
                    await self._send_monitor_message(
                        target,
                        "\u7ade\u6280\u573a\u6392\u540d\u63d0\u9192\u5df2\u6682\u505c\uff1a\u5f53\u524d QQ \u6ca1\u6709\u7ed1\u5b9a\u8d26\u53f7\u3002",
                        at_qq=str(user_id),
                    )
                    continue
                was_paused = bool(entry.get("manual_pause"))
                result = await self.arena.query(
                    str(entry.get("uid", "")),
                    str(entry.get("nickname", "")),
                    user=str(user_id),
                    account="main",
                )
                messages = update_arena_entry_from_result(entry, result)
                dirty = True
                if (
                    entry.get("manual_pause")
                    and entry.get("pause_reason") == "game_login_detected"
                    and not was_paused
                ):
                    self._pause_clan_monitors("game_login_detected", monitor_qq=str(user_id))
                for message in messages:
                    await self._send_monitor_message(target, message, at_qq=str(user_id))

        if dirty:
            self.storage.save()

    async def _poll_clan_monitors(self):
        clan_data = self.storage.data.get("clan", {})
        if not isinstance(clan_data, dict):
            return

        dirty = False
        for group_id, clan_state in list(clan_data.items()):
            if (
                not self.storage.group_enabled(group_id)
                or not isinstance(clan_state, dict)
                or clan_state.get("manual_pause")
                or not clan_state.get("out_damage_monitor")
            ):
                continue
            target = clan_state.get("monitor_session")
            if not target:
                continue
            monitor_qq = str(clan_state.get("monitor_qq") or "").strip()
            if not self._monitor_target_allowed(monitor_qq, f"session:{target}"):
                continue
            if not monitor_qq or not self.storage.get_account(monitor_qq):
                clan_state["out_damage_monitor"] = False
                clan_state["manual_pause"] = True
                clan_state["pause_reason"] = "account_missing"
                dirty = True
                await self._send_monitor_message(
                    f"session:{target}",
                    "\u51fa\u5200\u76d1\u63a7\u5df2\u6682\u505c\uff1a\u5f53\u524d QQ \u6ca1\u6709\u7ed1\u5b9a\u8d26\u53f7\u3002",
                    user_id=monitor_qq,
                )
                continue
            try:
                real_status = await self.real_api.clan_status(monitor_qq, account="main")
            except RealAPIError as exc:
                clan_state["out_damage_monitor"] = False
                clan_state["manual_pause"] = True
                clan_state["pause_reason"] = "real_api_error"
                dirty = True
                await self._send_monitor_message(
                    f"session:{target}",
                    f"\u51fa\u5200\u76d1\u63a7\u5df2\u6682\u505c\uff1a\u771f\u5b9e\u4f1a\u6218\u8bfb\u53d6\u5931\u8d25\uff1a{exc}",
                    user_id=monitor_qq,
                )
                continue
            messages = update_clan_damage_state(clan_state, real_status)
            merge_clan_history(clan_state, real_status)
            dirty = True
            for message in messages:
                await self._send_monitor_message(f"session:{target}", message, user_id=monitor_qq)

        if dirty:
            self.storage.save()

    def _pause_clan_monitors(self, reason: str, monitor_qq: str | None = None) -> None:
        clan_data = self.storage.data.get("clan", {})
        if not isinstance(clan_data, dict):
            return
        for clan_state in clan_data.values():
            if not isinstance(clan_state, dict):
                continue
            if monitor_qq and str(clan_state.get("monitor_qq") or "") != str(monitor_qq):
                continue
            clan_state["out_damage_monitor"] = False
            clan_state["manual_pause"] = True
            clan_state["pause_reason"] = reason

    async def _send_monitor_message(
        self, target: str | None, text: str, at_qq: str | None = None,
        *, user_id: str | None = None,
    ):
        if not self._monitor_target_allowed(user_id or at_qq or "", target):
            return False
        target_text = str(target or "")
        if not target_text.startswith("session:"):
            return False
        session = target_text[len("session:"):]
        if not session:
            return False
        chain = MessageChain()
        if at_qq:
            chain.at("", at_qq).message("\n" + text)
        else:
            chain.message(text)
        return await self.context.send_message(session, chain)

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def plain_text_dispatch(self, event: AstrMessageEvent, *args, **kwargs):
        if not self._user_allowed(numeric_sender_id_from_event(event)):
            return
        text = _message_text(event)
        if bool(getattr(event, "_pcr_assistant_processed", False)):
            return

        solution_command = parse_solution_command(text)
        if solution_command is not None:
            _mark_processed(event)
            region, payload = solution_command
            async for result in self._arena_solution_query(event, region, payload):
                yield result
            return

        arena_ranking = parse_arena_ranking_command(text)
        if arena_ranking is not None:
            _mark_processed(event)
            kind, page = arena_ranking
            async for result in self._arena_ranking_page(event, kind, page):
                yield result
            return

        expires = getattr(self, '_arena_image_sessions', {}).get((_sender_id(event), _group_key(event)), 0)
        if expires > time.monotonic() and _has_image_message(event) and self._pcr_event_allowed(event):
            _mark_processed(event)
            async for result in self._arena_solution_query(event, 1, ''):
                yield result
            return

        if bool(getattr(event, 'is_at_or_wake_command', False)):
            return

        command = match_plain_command(text, PLAIN_COMMANDS)
        if not command:
            compat_match = match_compat_command(text)
            if compat_match is None:
                return
            if not self._pcr_event_allowed(event):
                return

            _mark_processed(event)
            yield event.plain_result(build_compat_reply(compat_match))
            return

        if should_ignore_disabled_plain_clan_command(
            command,
            _is_group_feature_enabled(self.storage, event),
        ):
            return

        _mark_processed(event)
        handlers = {
            CMD_ARENA_TEMPLATES: self.arena_update_templates,
            CMD_ARENA_CONTINUOUS: self.arena_continuous_start,
            CMD_ARENA_CONTINUOUS_END: self.arena_continuous_end,
            CMD_HELP: self.pcr_help,
            CMD_GROUP_ENABLE: self.group_enable,
            CMD_GROUP_DISABLE: self.group_disable,
            CMD_GROUP_STATUS: self.group_status,
            CMD_DAILY: self.daily_link,
            CMD_DAILY_CONFIG: self.daily_config_link,
            CMD_DAILY_HASH: self.daily_hash_link,
            CMD_DAILY_CLEAR_ALL: self.daily_clear_all_link,
            CMD_DAILY_RECORD: self.daily_record_link,
            CMD_BIND: self.bind_account,
            CMD_ACCOUNT: self.account_status,
            CMD_UNBIND: self.unbind_account,
            CMD_ARENA_HELP: self.arena_help,
            CMD_ARENA_BIND: self.arena_bind,
            CMD_ARENA_DELETE_BINDING: self.arena_delete_binding,
            CMD_ARENA_CLEAR_BINDINGS: self.arena_clear_bindings,
            CMD_ARENA_QUERY: self.arena_query,
            CMD_ARENA_SUBSCRIBE_STATUS: self.arena_subscribe_status,
            CMD_ARENA_RENAME: self.arena_rename,
            CMD_ARENA_RECORD: self.arena_record,
            CMD_ARENA_DUEL_RECORD: self.arena_duel_record,
            CMD_ARENA_SETTINGS: self.arena_settings,
            CMD_ARENA_PUSH_GROUP: self.arena_push_group,
            CMD_ARENA_PUSH_PRIVATE: self.arena_push_private,
            CMD_ARENA_DETAIL_QUERY: self.arena_detail_query,
            CMD_ARENA_MONITOR: self.arena_monitor_on,
            CMD_ARENA_MONITOR_HASH: self.arena_monitor_on,
            CMD_ARENA_KILLER_ENABLE: self.arena_monitor_on,
            CMD_ARENA_PUSH_BILI_ENABLE: self.arena_monitor_on,
            CMD_ARENA_PUSH_BILI_ENABLE_UPPER: self.arena_monitor_on,
            CMD_ARENA_PUSH_CHANNEL_ENABLE: self.arena_monitor_on,
            CMD_ARENA_CANCEL_MONITOR: self.arena_monitor_off,
            CMD_ARENA_CANCEL_MONITOR_HASH: self.arena_monitor_off,
            CMD_ARENA_KILLER_DISABLE: self.arena_monitor_off,
            CMD_ARENA_PUSH_BILI_DISABLE: self.arena_monitor_off,
            CMD_ARENA_PUSH_BILI_DISABLE_UPPER: self.arena_monitor_off,
            CMD_ARENA_PUSH_CHANNEL_DISABLE: self.arena_monitor_off,
            CMD_ARENA_STATUS: self.arena_status,
            CMD_ARENA_KILLER: self.arena_status,
            CMD_ARENA_KILLER_JJC_ON: self.arena_killer_toggle,
            CMD_ARENA_KILLER_JJC_OFF: self.arena_killer_toggle,
            CMD_ARENA_KILLER_PJJC_ON: self.arena_killer_toggle,
            CMD_ARENA_KILLER_PJJC_OFF: self.arena_killer_toggle,
        }
        handlers.update({
            clan_command: self.clan_command
            for clan_command in CLAN_PLAIN_COMMANDS
        })
        handler = handlers.get(command) or handlers.get(arena_base_command(command))
        if handler is None:
            return

        async for result in handler(event):
            yield result
