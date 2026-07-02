import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CompatCommand:
    command: str
    module: str
    title: str
    note: str


@dataclass(frozen=True)
class CompatCommandMatch:
    command: str
    module: str
    title: str
    note: str
    text: str
    payload: str


DEFAULT_PENDING_NOTE = (
    "对应私有后端、实时游戏数据、外部排行/图片资源或本地玩法逻辑未接入。"
)


def _entry(module: str, commands: tuple[str, ...], note: str = DEFAULT_PENDING_NOTE):
    return tuple(
        CompatCommand(command=command, module=module, title=command, note=note)
        for command in commands
    )


def _rank_commands() -> tuple[str, ...]:
    bases = (
        "查询分段",
        "查询历史分段",
        "查询分段趋势",
        "查询排名",
        "查询历史排名",
        "查询公会",
        "查会长",
    )
    prefixes = ("台", "台一", "台二", "渠")
    return (*bases, *(prefix + command for prefix in prefixes for command in bases))


COMPAT_COMMANDS = (
    *_entry(
        "精准助战/box",
        (
            "启用 精准助战",
            "禁用 精准助战",
            "刷新box缓存",
            "box查询",
            "公会box查询",
            "刷新助战缓存",
            "精确助战",
            "上公会战支援",
            "上地下城支援",
            "上关卡支援",
            "我的助战",
            "公会深域查询",
        ),
    ),
    *_entry(
        "自动报刀",
        (
            "启用 你只需要好好出刀",
            "禁用 你只需要好好出刀",
            "启用 自动报刀2",
            "禁用 自动报刀2",
            "绑定账号",
            "bcr账号",
            "bcr密码",
            "渠绑定账号",
            "启用肃正协议",
            "修正出刀",
            "查看等效出刀数",
            "账号权限变更",
            "绑定本群公会",
            "删除本群公会绑定",
            "退出公会",
            "会战KPI",
            "kpi调整",
            "清空kpi",
            "删除kpi",
        ),
    ),
    *_entry(
        "手动报刀",
        (
            "开启手动报刀",
            "禁用 你只需要好好出刀",
            "禁用 自动报刀2",
            "手动添加群记录",
        ),
    ),
    *_entry("会战排名", _rank_commands()),
    *_entry(
        "会战报告",
        (
            "生成会战报告",
            "生成离职报告",
            "设置工会api",
            "查看工会api",
            "清除工会api",
        ),
    ),
    *_entry("合刀/尾刀计算", ("尾刀计算", "合刀", "cal")),
    *_entry("转秒", ("启用 转秒", "禁用 转秒", "转秒")),
    *_entry(
        "分刀查轴",
        (
            "启用 分刀",
            "禁用 分刀",
            "查轴",
            "分刀",
            "自动分刀",
            "添加角色黑名单",
            "删除角色黑名单",
            "添加角色缺失",
            "删除角色缺失",
            "添加作业黑名单",
            "删除作业黑名单",
            "查看角色缺失",
            "查看角色黑名单",
            "查看作业黑名单",
        ),
    ),
    *_entry(
        "会战排行榜",
        (
            "启用 clanbattle_rank",
            "禁用 clanbattle_rank",
            "查公会",
            "分数线",
        ),
    ),
    *_entry(
        "自动清日常",
        (
            "启用 自动清日常",
            "禁用 自动清日常",
            "#日常报告",
            "#定时日志",
            "#定时状态",
            "#定时统计",
            "#查角色",
            "#查缺角色",
            "#查缺称号",
            "#查box",
            "#刷新box",
            "#查心碎",
            "#查纯净碎片",
            "#查记忆碎片",
            "#查兑换角色碎片",
            "#查装备",
            "#查ex装备",
            "#刷图推荐",
            "#编队",
            "#一键编队",
            "#公会支援",
            "#查探险编队",
            "#查深域",
            "#查公会深域",
            "#卡池",
            "#免费十连",
            "#来发十连",
            "#识图",
            "#半月刊",
            "#运行状态",
            "#查禁用",
            "#查群禁用",
            "#查内鬼",
            "#清内鬼",
            "导出#查装备",
            "导出#查box",
            "导出#查记忆碎片",
            "群#清日常",
            "群#查装备",
            "#帮助",
            "#帮助自动清日常",
        ),
    ),
    *_entry(
        "pcr-arena",
        (
            "启用 pcr-arena",
            "禁用 pcr-arena",
            "jjc评论开",
            "jjc评论关",
            "bjjc",
            "pjjc",
            "testjjc",
        ),
    ),
    *_entry(
        "竞技场提醒/路径/买药水",
        (
            "启用 pcr-arena-reminder-tw",
            "禁用 pcr-arena-reminder-tw",
            "启用 pcr-arena-reminder-jp",
            "禁用 pcr-arena-reminder-jp",
            "启用 击剑路径计算",
            "禁用 击剑路径计算",
            "路径计算",
            "路线计算",
            "启用 buy_potion_reminder",
            "禁用 buy_potion_reminder",
        ),
    ),
    *_entry(
        "竞技场推送",
        (
            "启用 b服竞技场推送",
            "禁用 b服竞技场推送",
            "启用 B服竞技场推送",
            "禁用 B服竞技场推送",
            "启用 渠服竞技场推送",
            "禁用 渠服竞技场推送",
            "启用渠道服竞技场推送",
            "禁用渠道服竞技场推送",
        ),
    ),
    *_entry(
        "环奈竞技场",
        (
            "启用 huannai_arena",
            "禁用 huannai_arena",
            "怎么拆",
            "b怎么拆",
            "台怎么拆",
            "日怎么拆",
            "竞技场模拟",
            "竞技场建议",
            "#竞技场建议",
            "竞技场矩阵",
            "作业网查询",
            "#怎么拆",
            "结束查询",
            "竞技场更新卡池",
            "竞技场模拟练度",
            "竞技场对战帮助",
        ),
    ),
    *_entry("台服竞技场", ("台竞技场帮助",)),
    *_entry(
        "竞技场杀手",
        (
            "启用 竞技场杀手",
            "禁用 竞技场杀手",
            "竞技场监控",
            "#竞技场监控",
            "竞技场状态",
            "竞技场杀手开启竞技场",
            "竞技场杀手关闭竞技场",
            "竞技场杀手开启公主竞技场",
            "竞技场杀手关闭公主竞技场",
            "取消竞技场监控",
            "#取消竞技场监控",
            "竞技场清次数",
            "公主竞技场清次数",
            "竞技场排行榜",
            "公主竞技场排行榜",
            "竞技场查防守",
            "公主竞技场查防守",
            "竞技场查ID",
            "公主竞技场查ID",
        ),
    ),
    *_entry(
        "PCR 资料查询",
        (
            "公会战信息",
            "公会战信息2",
            "日程",
            "满补线",
            "pcr速查",
            "bcr速查",
            "黄骑充电表",
            "谁是霸瞳",
        ),
    ),
    *_entry(
        "战力查询",
        (
            "启用战力查询",
            "禁用战力查询",
            "战力查询帮助",
            "战力排行",
            "查询战力",
            "查看战力排行榜",
            "查询公会成员",
            "查询ID",
            "查询成员ID",
        ),
    ),
    *_entry(
        "角色卡片",
        (
            "角色卡片",
            "日服角色卡片",
            "角色1卡片",
            "角色2卡片",
            "角色3卡片",
        ),
    ),
    *_entry(
        "生日查询",
        (
            "谁的生日是",
            "角色生日",
        ),
    ),
    *_entry(
        "pcr_calendar",
        (
            "启用 pcr_calendar",
            "禁用 pcr_calendar",
            "日历",
            "国服日历",
            "台服日历",
            "日服日历",
        ),
    ),
    *_entry(
        "扭蛋模拟",
        (
            "启用 gacha",
            "禁用 gacha",
            "环奈来发十连",
            "环奈来发单抽",
            "环奈来发一井",
            "查看卡池",
            "切换卡池",
        ),
    ),
    *_entry(
        "猜角色",
        (
            "猜角色",
            "猜角色排行榜",
            "猜头像",
            "猜头像排行",
        ),
    ),
    *_entry("官网新闻", ("台服官网新闻", "B服官网新闻")),
    *_entry(
        "PCR 娱乐/杂项",
        (
            "签到",
            "切噜一下",
            "切噜语翻译",
            "测试赛跑",
            "赛跑排行榜",
            "重置赛跑",
            "启用 pcr_almanac",
            "禁用 pcr_almanac",
            "抽签",
            "来点音乐",
            "cygames",
        ),
    ),
    *_entry(
        "贵族决斗",
        (
            "启用 pcr-duel",
            "禁用 pcr-duel",
            "贵族决斗帮助",
            "贵族帮助",
            "贵族指令",
            "创建贵族",
            "查询贵族",
            "贵族查询",
            "我的贵族",
            "本群贵族状态",
            "查询本群贵族",
            "本群贵族",
            "贵族签到",
            "领金币",
            "领取金币",
            "查金币",
            "查询金币",
            "查看金币",
            "dlc帮助",
            "DLC帮助",
            "dlc指令",
            "DLC指令",
            "加载dlc",
            "卸载dlc",
            "dlc列表",
            "DLC列表",
            "dlc介绍",
            "DLC介绍",
            "招募女友",
            "贵族舞会",
            "升级爵位",
            "升级贵族",
            "贵族升级",
            "贵族决斗",
            "接受",
            "拒绝",
            "开枪",
            "接受交易",
            "拒绝交易",
            "重置交易",
            "每日约会",
            "女友约会",
            "贵族约会",
            "接受交换",
            "拒绝交换",
            "声望换金币",
            "金币排行榜",
            "金币排行",
            "重置金币",
            "免费招募",
            "声望招募",
            "增加容量",
            "增加女友上限",
            "重置决斗",
            "查女友",
            "查询女友",
            "查看女友",
            "分手",
            "好感系统帮助",
            "礼物系统帮助",
            "好感帮助",
            "礼物帮助",
            "查好感",
            "查询好感",
            "送礼物",
            "送礼",
            "赠送礼物",
            "批量送礼",
            "一键送礼",
            "抽礼物",
            "买礼物",
            "购买礼物",
            "我的礼物",
            "礼物仓库",
            "查询礼物",
            "礼物列表",
            "购买情报",
            "买情报",
            "好感列表",
            "女友好感列表",
            "重置礼物交换",
            "声望系统帮助",
            "声望帮助",
            "开启声望系统",
            "查询声望",
            "加冕称帝",
            "加冕仪式",
            "飞升成神",
            "成神飞升",
            "皇室婚礼",
            "确认离婚",
            "声望排行榜",
            "声望排行",
            "女友排行榜",
            "女友排行",
            "时装系统帮助",
            "时装帮助",
            "时装商城",
            "购买时装",
            "买时装",
            "穿戴时装",
            "穿时装",
            "我的女友",
            "还原穿戴",
            "取消穿戴",
            "发送红包",
            "领取红包",
            "查询庆典",
            "庆典状况",
            "当前庆典",
            "初始化本群庆典",
            "重置角色",
            "确认重开",
        ),
    ),
    *_entry(
        "大乱斗",
        (
            "大乱斗规则",
            "大乱斗角色",
            "角色详情",
            "结束大乱斗",
            "创建大乱斗",
            "加入大乱斗",
            "开始大乱斗",
            "丢色子",
            "查看属性",
            "投降",
            "认输",
        ),
    ),
    *_entry(
        "道具仓库",
        (
            "查看仓库",
            "合成",
            "一键合成",
            "赠送",
            "交换",
            "确认交换",
        ),
    ),
    *_entry("猜语音", ("猜语音排行",)),
    *_entry(
        "猜立绘",
        (
            "猜立绘",
            "猜立绘群排行",
            "猜立绘重置",
        ),
    ),
    *_entry(
        "猜群友",
        (
            "猜群友",
            "猜群友排行",
            "重置猜群友",
        ),
    ),
    *_entry("完美配对", (".完美配对", ".完美配对排行榜")),
    *_entry("神经衰弱", ("神经衰弱", "神经衰弱排行榜")),
)


def _normalize_text(text: str) -> str:
    return " ".join(str(text or "").strip().split())


def _build_exact_index() -> tuple[CompatCommand, ...]:
    seen = set()
    indexed = []
    for command in COMPAT_COMMANDS:
        if command.command in seen:
            continue
        seen.add(command.command)
        indexed.append(command)
    return tuple(sorted(indexed, key=lambda item: len(item.command), reverse=True))


EXACT_COMMANDS = _build_exact_index()
BIRTHDAY_PREFIX = "谁的生日是"
BIRTHDAY_ROLE_MARKER = "的生日是"
BIRTHDAY_PREFIX_COMMAND = CompatCommand(
    command=BIRTHDAY_PREFIX,
    module="生日查询",
    title=BIRTHDAY_PREFIX,
    note=DEFAULT_PENDING_NOTE,
)
BIRTHDAY_ROLE_COMMAND = CompatCommand(
    command="角色...的生日是...",
    module="生日查询",
    title="角色生日",
    note=DEFAULT_PENDING_NOTE,
)
DUEL_PATTERN_COMMANDS = (
    (re.compile(r"^加载dlc.+$"), "加载DLC"),
    (re.compile(r"^卸载dlc.+$"), "卸载DLC"),
    (re.compile(r"^支持[12]号.+金币$"), "支持1/2号"),
    (re.compile(r"^梭哈支持[12]号$"), "梭哈支持"),
    (re.compile(r"^分手.+$"), "分手"),
    (re.compile(r"^以.+金币上架女友.+$"), "上架女友"),
    (re.compile(r"^用.+金币与@.+交易女友.+$"), "女友交易"),
    (re.compile(r"^皇室婚礼.+$"), "皇室婚礼"),
    (re.compile(r"^用.+声望兑换金币$"), "声望换金币"),
    (re.compile(r"^为@.+转账.+金币$"), "转账"),
    (re.compile(r"^重置金币.+$"), "重置金币"),
    (re.compile(r"^重置角色.+$"), "重置角色"),
)


def match_compat_command(text: str) -> CompatCommandMatch | None:
    normalized = _normalize_text(text)
    if not normalized or normalized.startswith("/"):
        return None

    birthday_match = _match_birthday_prefix(normalized)
    if birthday_match is not None:
        return birthday_match

    for command in EXACT_COMMANDS:
        if normalized == command.command:
            return _to_match(command, normalized, "")
        if normalized.startswith(command.command + " "):
            payload = normalized[len(command.command):].strip()
            return _to_match(command, normalized, payload)

    duel_match = _match_duel_pattern(normalized)
    if duel_match is not None:
        return duel_match
    return None


def build_compat_reply(match: CompatCommandMatch) -> str:
    return "\n".join(
        (
            f"指令已识别：{match.title}",
            f"来源模块：{match.module}",
            f"兼容说明：{match.note}",
            "当前不会返回伪造结果；待接入真实后端或完成本地实现后再提供结果。",
        )
    )


def _match_birthday_prefix(normalized: str) -> CompatCommandMatch | None:
    if normalized.startswith(BIRTHDAY_PREFIX):
        payload = normalized[len(BIRTHDAY_PREFIX):].strip()
        return _to_match(BIRTHDAY_PREFIX_COMMAND, normalized, payload)
    if normalized.startswith("角色") and BIRTHDAY_ROLE_MARKER in normalized[2:]:
        return _to_match(BIRTHDAY_ROLE_COMMAND, normalized, normalized)
    return None


def _match_duel_pattern(normalized: str) -> CompatCommandMatch | None:
    for pattern, title in DUEL_PATTERN_COMMANDS:
        if pattern.match(normalized):
            command = CompatCommand(
                command=title,
                module="贵族决斗",
                title=title,
                note=DEFAULT_PENDING_NOTE,
            )
            return _to_match(command, normalized, normalized)
    return None


def _to_match(
    command: CompatCommand,
    normalized_text: str,
    payload: str,
) -> CompatCommandMatch:
    return CompatCommandMatch(
        command=command.command,
        module=command.module,
        title=command.title,
        note=command.note,
        text=normalized_text,
        payload=payload,
    )
