DEFAULT_ARENA_ENTRY = {
    "uid": "",
    "nickname": "",
    "settings": "1100",
    "push_target": None,
    "last_jjc_rank": None,
    "last_pjjc_rank": None,
    "last_login_time": None,
    "rank_up_count_today": 0,
    "manual_pause": False,
    "pause_reason": "",
}

ARENA_PLATFORM_BILI = "bili"
ARENA_PLATFORM_CHANNEL = "channel"
ARENA_MISSING_BINDINGS_MESSAGE = (
    "\u8fd8\u6ca1\u6709\u7ade\u6280\u573a\u7ed1\u5b9a\u3002"
    "\u5148\u53d1\u9001\uff1a\u7ade\u6280\u573a\u7ed1\u5b9a UID [\u6635\u79f0]"
)


def normalize_arena_settings(value):
    text = str(value).strip()
    if len(text) != 4 or not text.isdigit():
        raise ValueError("arena settings must be four digits")
    if any(char not in "01" for char in text[:3]):
        raise ValueError("arena settings toggles must be 0 or 1")
    if text[3] not in "0123":
        raise ValueError("online reminder setting must be 0..3")
    return text


def bind_arena_uid(store, user_id, uid, nickname="", platform=ARENA_PLATFORM_CHANNEL):
    normalized_platform = _normalize_platform(platform)
    uid_text = str(uid).strip()
    if not uid_text:
        raise ValueError("arena uid is required")

    store.bind_arena_uid(user_id, uid_text, str(nickname or uid_text).strip())
    bindings = _bindings(store, user_id)
    for binding in bindings:
        if str(binding.get("uid", "")) == uid_text:
            binding["platform"] = normalized_platform
            store.save()
            return _normalize_entry(binding)
    raise IndexError("arena binding index does not exist")


def resolve_arena_query_targets(store, user_id, payload):
    text = str(payload or "").strip()
    if not text:
        return _query_targets_or_missing(select_arena_bindings(store, user_id, "0"))

    tokens = text.split()
    first = tokens[0]
    if not first.startswith("@"):
        if _is_index_token(first):
            return _query_targets_or_missing(select_arena_bindings(store, user_id, first))
        return [_normalize_entry({"uid": first, "nickname": first})], None

    return [], (
        "\u5c1a\u672a\u652f\u6301\u4ece\u7eaf\u6587\u672c @ \u89e3\u6790"
        "\u4ed6\u4eba\u7684\u672c\u5730\u7ed1\u5b9a\u3002\u8bf7\u76f4\u63a5"
        "\u586b\u5199 UID\uff0c\u6216\u67e5\u8be2\u81ea\u5df1\u7684\u7ed1"
        "\u5b9a\u5e8f\u53f7\u3002\u771f\u5b9e\u6392\u540d/\u5386\u53f2"
        "\u540e\u7aef\u5c1a\u672a\u63a5\u5165\u3002"
    )


def _query_targets_or_missing(bindings):
    if not bindings:
        return [], ARENA_MISSING_BINDINGS_MESSAGE
    return bindings, None


def select_arena_bindings(store, user_id, index):
    bindings = _bindings(store, user_id)
    selected_indexes = _selected_indexes(index, len(bindings), allow_all=True)
    return [_normalize_entry(bindings[item_index]) for item_index in selected_indexes]


def rename_arena_binding(store, user_id, index, nickname):
    bindings = _bindings(store, user_id)
    item_index = _single_index(index, len(bindings))
    bindings[item_index] = _normalize_entry(bindings[item_index])
    bindings[item_index]["nickname"] = nickname
    store.save()
    return bindings[item_index]


def apply_arena_settings(store, user_id, settings, index="0"):
    normalized_settings = normalize_arena_settings(settings)
    bindings = _bindings(store, user_id)
    selected_indexes = _selected_indexes(index, len(bindings), allow_all=True)
    updated = []
    for item_index in selected_indexes:
        bindings[item_index] = _normalize_entry(bindings[item_index])
        bindings[item_index]["settings"] = normalized_settings
        updated.append(bindings[item_index])
    store.save()
    return updated


def delete_arena_binding(store, user_id, index):
    bindings = _bindings(store, user_id)
    item_index = _single_index(index, len(bindings))
    deleted = _normalize_entry(bindings.pop(item_index))
    store.save()
    return deleted


def clear_arena_bindings(store, user_id):
    deleted = [_normalize_entry(binding) for binding in _bindings(store, user_id)]
    store.data["arena"][str(user_id)] = []
    store.save()
    return deleted


def set_arena_push_target(store, user_id, target, index="0"):
    bindings = _bindings(store, user_id)
    selected_indexes = _selected_indexes(index, len(bindings), allow_all=True)
    updated = []
    for item_index in selected_indexes:
        bindings[item_index] = _normalize_entry(bindings[item_index])
        bindings[item_index]["push_target"] = target
        if target:
            bindings[item_index]["manual_pause"] = False
            bindings[item_index]["pause_reason"] = ""
        else:
            bindings[item_index]["manual_pause"] = True
            bindings[item_index]["pause_reason"] = "manual_off"
        updated.append(bindings[item_index])
    store.save()
    return updated


def describe_arena_bindings(bindings, index="0"):
    rows = []
    for offset, binding in enumerate(bindings, start=1):
        entry = _normalize_entry(binding)
        rows.append(_describe_entry(offset, entry))
    if not rows:
        return "\u672a\u7ed1\u5b9a\u7ade\u6280\u573a\u8d26\u53f7"
    return "\n".join(rows)


def _bindings(store, user_id):
    user_key = str(user_id)
    if not isinstance(store.data.get("arena"), dict):
        store.data["arena"] = {}
    bindings = _normalize_bindings(store.data["arena"].get(user_key, []))
    store.data["arena"][user_key] = bindings
    return bindings


def _normalize_bindings(value):
    if isinstance(value, dict):
        return [_normalize_entry(value)]
    if isinstance(value, list):
        bindings = []
        for item in value:
            if isinstance(item, dict):
                bindings.append(_normalize_entry(item))
        return bindings[:8]
    return []


def _normalize_entry(entry):
    normalized = dict(DEFAULT_ARENA_ENTRY)
    normalized.update(entry)
    normalized["uid"] = str(normalized.get("uid", ""))
    normalized["nickname"] = normalized.get("nickname") or ""
    try:
        normalized["settings"] = normalize_arena_settings(normalized.get("settings", "1100"))
    except ValueError:
        normalized["settings"] = "1100"
    if normalized.get("rank_up_count_today") is None:
        normalized["rank_up_count_today"] = 0
    return normalized


def _normalize_platform(platform):
    text = str(platform or ARENA_PLATFORM_CHANNEL).strip().lower()
    if text in {ARENA_PLATFORM_BILI, ARENA_PLATFORM_CHANNEL}:
        return text
    raise ValueError("arena platform must be bili or channel")


def _is_index_token(value):
    text = str(value).strip()
    return text in {str(index) for index in range(0, 9)}


def _single_index(index, length):
    indexes = _selected_indexes(index, length, allow_all=False)
    return indexes[0]


def _selected_indexes(index, length, allow_all):
    try:
        value = int(str(index).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError("arena index must be 0..8") from exc

    if value == 0 and allow_all:
        return list(range(length))
    if value < 1 or value > 8:
        raise ValueError("arena index must be 1..8")
    item_index = value - 1
    if item_index >= length:
        raise IndexError("arena binding index does not exist")
    return [item_index]


def _describe_entry(index, entry):
    settings = entry["settings"]
    jjc = _enabled_text(settings[0])
    pjjc = _enabled_text(settings[1])
    rank_up = _enabled_text(settings[2])
    online = {
        "0": "\u5173",
        "1": "JJC",
        "2": "PJJC",
        "3": "JJC/PJJC",
    }[settings[3]]
    nickname = entry["nickname"] or "\u672a\u547d\u540d"
    platform = _platform_text(entry.get("platform", ARENA_PLATFORM_CHANNEL))
    push_target = _push_target_text(entry.get("push_target"))
    return (
        f"{index}. {nickname} {platform} uid={entry['uid']} "
        f"\u8bbe\u7f6e:{settings} "
        f"JJC:{jjc} PJJC:{pjjc} "
        f"\u6392\u540d\u4e0a\u5347:{rank_up} "
        f"\u4e0a\u7ebf\u63d0\u9192:{online} "
        f"\u63a8\u9001:{push_target}"
    )


def _enabled_text(value):
    if value == "1":
        return "\u5f00"
    return "\u5173"


def _platform_text(platform):
    if platform == ARENA_PLATFORM_CHANNEL:
        return "\u6e20\u9053\u670d"
    return "B\u670d"


def _push_target_text(push_target):
    if not push_target:
        return "\u672a\u8bbe\u7f6e"
    text = str(push_target)
    if text.startswith("group:"):
        return "\u672c\u7fa4"
    if text.startswith("private:"):
        return "\u79c1\u804a"
    return text
