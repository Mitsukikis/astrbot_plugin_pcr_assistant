import re


RANKING_COMMAND_PATTERN = re.compile(
    "^(?P<kind>"
    "\u7ade\u6280\u573a|jjc|JJC|"
    "\u516c\u4e3b\u7ade\u6280\u573a|\u516c\u4e3b|\u51fb\u5251|pjjc|PJJC"
    ")\u6392\u884c\u699c(?P<page>\\d+)$"
)


def parse_arena_ranking_command(text):
    match = RANKING_COMMAND_PATTERN.match(str(text or "").strip())
    if not match:
        return None
    kind_text = match.group("kind")
    kind = (
        "pjjc"
        if kind_text in {"\u516c\u4e3b\u7ade\u6280\u573a", "\u516c\u4e3b", "\u51fb\u5251", "pjjc", "PJJC"}
        else "jjc"
    )
    page = int(match.group("page"))
    if page < 1:
        return None
    return kind, page


def format_arena_ranking(payload):
    if not isinstance(payload, dict):
        return "\u7ade\u6280\u573a\u6392\u884c\u699c\u67e5\u8be2\u5931\u8d25\uff1a\u771f\u5b9e\u540e\u7aef\u8fd4\u56de\u5f02\u5e38\u3002"
    kind = payload.get("kind") or "jjc"
    arena = payload.get("arena") or {}
    group = arena.get("group") or "-"
    ranking = payload.get("ranking") or []
    title = "\u516c\u4e3b\u7ade\u6280\u573a" if kind == "pjjc" else "\u7ade\u6280\u573a"
    lines = [f"\u5f53\u524d\u4e3a{title}{group}\u53f7\u573a{_range_text(payload)}"]
    if not ranking:
        lines.append("\u6682\u65e0\u6392\u884c\u699c\u6570\u636e")
        return "\n".join(lines)
    for item in ranking:
        if not isinstance(item, dict):
            continue
        rank = item.get("rank") or "-"
        name = item.get("user_name") or item.get("name") or "-"
        viewer_id = item.get("viewer_id") or "-"
        lines.append(f"{rank}: {name} ({viewer_id})")
    return "\n".join(lines)


def ranking_range(page, limit=20):
    page_value = max(1, int(page or 1))
    limit_value = max(1, int(limit or 20))
    start = (page_value - 1) * limit_value + 1
    return start, start + limit_value - 1


def _range_text(payload):
    start, end = ranking_range(payload.get("page") or 1, payload.get("limit") or 20)
    return f"\uff08{start}-{end}\uff09"
