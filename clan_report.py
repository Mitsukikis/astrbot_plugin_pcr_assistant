from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path


EMPTY_DATABASE_TEXT = "\u6570\u636e\u5e93\u4e3a\u7a7a\uff0c\u8bf7\u786e\u4fdd\u5f00\u542f\u51fa\u5200\u76d1\u63a7"
UNKNOWN = "\u672a\u77e5"
REPORT_TITLES = {
    "current_report": "\u5f53\u524d\u6218\u62a5", "today_report": "\u4eca\u65e5\u6218\u62a5",
    "yesterday_report": "\u6628\u65e5\u6218\u62a5", "my_report": "\u6211\u7684\u6218\u62a5",
    "damage_detail": "\u51fa\u5200\u8be6\u60c5", "today_damage": "\u4eca\u65e5\u51fa\u5200",
    "yesterday_damage": "\u6628\u65e5\u51fa\u5200",
}


def build_damage_count_summary(real_status):
    rows = build_current_report_rows(real_status)
    if not rows:
        return EMPTY_DATABASE_TEXT
    total = sum(row["hits"] for row in rows)
    lines = ["\u4ee5\u4e0b\u662f\u51fa\u5200\u6b21\u6570\u7edf\u8ba1:", f"\u603b\u8ba1\u51fa\u5200: {_count_text(total)}"]
    groups = defaultdict(list)
    duplicates = Counter(row["name"] for row in rows)
    for row in rows:
        name = row["name"]
        if duplicates[name] > 1:
            name += f" [ID:{row['viewer_id'] or UNKNOWN}]"
        groups[row["hits"]].append(name)
    for count in sorted(groups, reverse=True):
        lines.extend(["----------", f"\u4ee5\u4e0b\u662f\u51fa\u4e86{_count_text(count)}\u5200\u7684\u6210\u5458: {'|'.join(groups[count])}"])
    lines.extend(_report_notes(real_status, rows))
    return "\n".join(lines)


def build_current_report_text(real_status):
    rows = build_current_report_rows(real_status)
    if not rows:
        return EMPTY_DATABASE_TEXT
    # Retain legacy header and '-' values for existing text consumers.
    lines = ["\u6392\u540d | \u6635\u79f0 | \u51fa\u5200\u6b21\u6570 | \u9020\u6210\u4f24\u5bb3 | \u5206\u6570 | \u4f24\u5bb3\u5360\u6bd4 | \u5206\u6570\u5360\u6bd4"]
    duplicates = Counter(row["name"] for row in rows)
    for row in rows:
        name = row["name"]
        if duplicates[name] > 1:
            name += f" [ID:{row['viewer_id'] or UNKNOWN}]"
        damage = row["damage"] if row["damage_complete"] else "-"
        lines.append(
            f"{row['rank']} | {name} | {_count_text(row['hits'])} | "
            f"{damage} | {row['score']} | "
            f"{row['damage_percent']} | {row['score_percent']}"
        )
    lines.extend(_report_notes(real_status, rows))
    return "\n".join(lines)


def build_current_report_rows(real_status):
    """Aggregate by viewer_id. Legacy score_percent uses known complete scores.

    score_percent_complete indicates whether the denominator covers every hit.
    Missing scores are never inferred from damage or treated as zero.
    """
    status = real_status if isinstance(real_status, dict) else {}
    by_identity = {}

    def ensure(item):
        viewer_id, name = _viewer_id(item), _member_name(item)
        if not viewer_id and not name:
            return None
        identity = ("id", viewer_id) if viewer_id else ("name", name)
        if identity not in by_identity:
            by_identity[identity] = {
                "viewer_id": viewer_id, "name": name or f"\u73a9\u5bb6{viewer_id}",
                "hits": 0, "records": 0, "damage": 0, "damage_records": 0,
                "known_score": 0, "score_records": 0,
                "score_complete": True, "damage_complete": True,
                "compensation_records": 0,
            }
        return by_identity[identity]

    # Current roster names take precedence over historical names after a rename.
    for member in _members(status):
        row = ensure(member)
        if row is not None and _member_name(member):
            row["name"] = _member_name(member)
    for item in _damage_history(status):
        row = ensure(item)
        if row is None:
            continue
        weight = _hit_weight(item)
        row["hits"] += weight
        row["records"] += 1
        row["compensation_records"] += int(weight == 0.5)
        damage = _number(item.get("damage", item.get("total_damage")))
        if damage is None or damage < 0:
            row["damage_complete"] = False
        else:
            row["damage"] += damage
            row["damage_records"] += 1
        score = _score_value(item)
        if score is None or score < 0:
            row["score_complete"] = False
        else:
            row["known_score"] += score
            row["score_records"] += 1

    rows = list(by_identity.values())
    for row in rows:
        row["score_complete"] = row["score_complete"] and row["records"] > 0
    scores_complete = all(row["score_complete"] for row in rows if row["records"])
    damage_complete = all(row["damage_complete"] for row in rows)
    total_damage = sum(row["damage"] for row in rows)
    total_score = sum(row["known_score"] for row in rows if row["score_complete"])
    rows.sort(key=lambda row: (
        -(row["known_score"] if scores_complete else row["damage"]),
        -row["damage"], -row["hits"], row["name"], row["viewer_id"] or "",
    ))
    for index, row in enumerate(rows, 1):
        row["rank"] = index
        row["damage_percent"] = _percent(row["damage"], total_damage) if damage_complete else "-"
        row["score_percent"] = _percent(row["known_score"], total_score) if row["score_complete"] else "-"
        row["score_percent_complete"] = scores_complete
        row["score"] = str(row["known_score"]) if row["score_complete"] else "-"
    return rows


def prepare_clan_report(real_status, command_key="current_report", real_mylog=None):
    """Return a non-mutating, explicitly scoped presentation payload."""
    if command_key not in REPORT_TITLES:
        raise ValueError(f"Unsupported clan report command: {command_key}")
    status = dict(real_status) if isinstance(real_status, dict) else {}
    if status.get('report_command') == command_key:
        return status
    battle = status.get("clan_battle")
    battle = battle if isinstance(battle, dict) else {}
    history, notes = _damage_history(status, current_period_only=False), []
    if command_key == "my_report":
        payload = real_mylog if isinstance(real_mylog, dict) else {}
        for key in ("damage_history_complete", "history_complete"):
            status[key] = payload.get(key) is True
        status["history_scope"] = payload.get("history_scope") or "\u6211\u7684\u6b63\u5f0f\u51fa\u5200\uff08\u5df2\u8fd4\u56de\u8bb0\u5f55\uff09"
        logs = payload.get("actual_logs")
        logs = logs if isinstance(logs, list) else []
        account = payload.get("account") or status.get("account") or {}
        account = account if isinstance(account, dict) else {}
        history = []
        for log in logs:
            if not isinstance(log, dict):
                continue
            item = dict(log)
            item.setdefault("damage", item.get("total_damage"))
            if not _viewer_id(item) and _viewer_id(account):
                item["viewer_id"] = _viewer_id(account)
            if not _member_name(item):
                item["name"] = _member_name(account) or "\u76d1\u63a7\u73a9\u5bb6\uff08\u6e38\u620f\u540d\u672a\u77e5\uff09"
            history.append(item)
        roster_keys = {"members", "clan_members", "member_list", "clan_member_list"}
        for key in roster_keys:
            status.pop(key, None)
        clan = status.get("clan")
        status["clan"] = {key: value for key, value in clan.items() if key not in roster_keys} if isinstance(clan, dict) else {}
        notes.append("\u4ec5\u7edf\u8ba1\u6211\u7684\u6b63\u5f0f\u51fa\u5200\u8bb0\u5f55\uff1b\u4e0d\u5305\u542b\u6a21\u62df\u3001\u8bad\u7ec3\u6216\u5176\u4ed6\u6210\u5458\u3002")

    filtered = [item for item in history if _same_period(item, battle)]
    if len(filtered) != len(history):
        notes.append(f"\u5df2\u6392\u9664{len(history) - len(filtered)}\u6761\u5176\u4ed6\u4f1a\u6218\u6216\u5176\u4ed6\u671f\u8bb0\u5f55\u3002")
    history = filtered
    if command_key in {"today_report", "today_damage", "yesterday_report", "yesterday_damage"}:
        # CN game days begin at 05:00 UTC+8; explicit metadata can override the hour.
        tz = timezone(timedelta(hours=8))
        now = _timestamp(status.get("server_time") or status.get("reference_time")) or datetime.now(tz)
        hour = _number(status.get("day_start_hour"))
        hour = hour if hour is not None and 0 <= hour <= 23 else 5
        start = now.astimezone(tz).replace(hour=hour, minute=0, second=0, microsecond=0)
        if now < start:
            start -= timedelta(days=1)
        if command_key.startswith("yesterday"):
            start -= timedelta(days=1)
        end = start + timedelta(days=1)
        selected, missing = [], 0
        for item in history:
            timestamp = _item_time(item)
            if timestamp is None:
                missing += 1
            elif start <= timestamp < end:
                selected.append(item)
        history = selected
        notes.append(f"\u6e38\u620f\u65e5\u8303\u56f4\uff1a{start:%Y-%m-%d %H:%M} \u81f3 {end:%Y-%m-%d %H:%M}\uff08UTC+8\uff09\u3002")
        if missing:
            notes.append(f"{missing}\u6761\u8bb0\u5f55\u7f3a\u5c11\u53ef\u8bc6\u522b\u65f6\u95f4\uff0c\u65e0\u6cd5\u5f52\u5165\u8be5\u6e38\u620f\u65e5\uff0c\u672a\u8ba1\u5165\u3002")
    status["damage_history"] = history
    status["presentation_notes"] = notes
    return status


def render_clan_report(real_status, path, command_key="current_report", real_mylog=None) -> Path:
    """Render a bounded-width white table without network access."""
    from PIL import Image, ImageDraw, ImageFont

    status = prepare_clan_report(real_status, command_key, real_mylog)
    rows = build_current_report_rows(status)
    width, margin = 1280, 32
    columns = [72, 244, 112, 216, 216, 164, 192]
    fonts = {size: _load_font(ImageFont, size) for size in (22, 24, 26, 28, 40)}
    measure = ImageDraw.Draw(Image.new("RGB", (width, 1), "white"))
    duplicates = Counter(row["name"] for row in rows)
    name_lines, heights = [], []
    for row in rows:
        lines = [(line, fonts[28]) for line in _wrap_text(measure, row["name"], fonts[28], columns[1] - 28)]
        if duplicates[row["name"]] > 1:
            lines.extend((line, fonts[22]) for line in _wrap_text(measure, f"ID: {row['viewer_id'] or UNKNOWN}", fonts[22], columns[1] - 28))
        name_lines.append(lines)
        heights.append(max(92, len(lines) * 38 + 24))
    clan = status.get("clan")
    clan = clan if isinstance(clan, dict) else {}
    battle = status.get("clan_battle")
    battle = battle if isinstance(battle, dict) else {}
    subtitle = f"{clan.get('clan_name') or '\u516c\u4f1a\u540d\u672a\u77e5'}  |  \u4f1a\u6218 {battle.get('id') or UNKNOWN}  |  \u7b2c{battle.get('period') or UNKNOWN}\u671f"
    subtitle_lines = _wrap_text(measure, subtitle, fonts[26], width - 2 * margin)
    scope_lines = _wrap_text(measure, _scope_line(status), fonts[24], width - 2 * margin)
    scope_top = 84 + len(subtitle_lines) * 36 + 8
    totals_top = scope_top + len(scope_lines) * 34 + 24
    table_top = totals_top + 104
    header_height = 68
    notes = _report_notes(status, rows)
    note_lines = [line for note in notes for line in _wrap_text(measure, note, fonts[24], width - 2 * margin)]
    footer_top = table_top + header_height + sum(heights) + (96 if not rows else 0)
    image = Image.new("RGB", (width, footer_top + 56 + len(note_lines) * 34), "white")
    draw = ImageDraw.Draw(image)
    ink, muted, grid = "#20262c", "#606a73", "#dce2e7"
    draw.rectangle((0, 0, width, 8), fill="#17785b")
    draw.text((margin, 26), REPORT_TITLES[command_key], font=fonts[40], fill=ink)
    for index, line in enumerate(subtitle_lines):
        draw.text((margin, 84 + index * 36), line, font=fonts[26], fill=muted)
    for index, line in enumerate(scope_lines):
        draw.text((margin, scope_top + index * 34), line, font=fonts[24], fill=muted)
    totals = [
        ("\u51fa\u5200\u6b21\u6570", _count_text(sum(row["hits"] for row in rows))),
        ("\u603b\u4f24\u5bb3" if all(row["damage_complete"] for row in rows) else "\u5df2\u77e5\u4f24\u5bb3",
         f"{sum(row['damage'] for row in rows):,}" if any(row["damage_records"] for row in rows) or not any(row["records"] for row in rows) else UNKNOWN),
        ("\u5df2\u77e5\u5206\u6570", f"{sum(row['known_score'] for row in rows):,}" if any(row["score_records"] for row in rows) else UNKNOWN),
    ]
    for index, (label, value) in enumerate(totals):
        x, y = margin + index * 405, totals_top
        draw.text((x, y), label, font=fonts[24], fill=muted)
        draw.text((x, y + 36), value, font=_fit_font(draw, value, ImageFont, 34, 390), fill=ink)
    draw.rectangle((margin, table_top, width - margin, table_top + header_height), fill="#edf2f4")
    headers = ["\u6392\u540d", "\u6e38\u620f\u540d", "\u51fa\u5200\u6b21\u6570", "\u603b\u4f24\u5bb3", "\u5206\u6570", "\u4f24\u5bb3\u5360\u6bd4", "\u5206\u6570\u5360\u6bd4"]
    x = margin
    for column, header in zip(columns, headers):
        _draw_cell(draw, header, x, table_top, column, header_height, fonts[26], ink)
        x += column
    y = table_top + header_height
    for index, row in enumerate(rows):
        height = heights[index]
        if index % 2:
            draw.rectangle((margin, y, width - margin, y + height), fill="#f8fafb")
        draw.line((margin, y + height, width - margin, y + height), fill=grid)
        values = [str(row["rank"]), row["name"], _count_text(row["hits"]),
                  f"{row['damage']:,}" if row["damage_complete"] else UNKNOWN,
                  f"{int(row['score']):,}" if row["score"] != "-" else UNKNOWN,
                  row["damage_percent"], row["score_percent"] if row["score_percent_complete"] else UNKNOWN]
        x = margin
        for col_index, (column, value) in enumerate(zip(columns, values)):
            if col_index == 1:
                lines = name_lines[index]
                top = y + (height - len(lines) * 38) // 2
                for line_index, (line, font) in enumerate(lines):
                    draw.text((x + 14, top + line_index * 38), line, font=font, fill=ink)
            elif col_index == 5 and row["damage_percent"] != "-":
                _draw_cell(draw, value, x, y + 10, column, height - 30, fonts[28], ink)
                left, right = x + 18, x + column - 18
                draw.rectangle((left, y + height - 20, right, y + height - 14), fill="#e1e9e5")
                fraction = float(value.rstrip("%")) / 100
                if fraction > 0:
                    draw.rectangle((left, y + height - 20, left + (right - left) * fraction, y + height - 14), fill="#258c6a")
            else:
                value = UNKNOWN if value == "-" else value
                font = _fit_font(draw, value, ImageFont, 28, column - 20)
                _draw_cell(draw, value, x, y, column, height, font, muted if value == UNKNOWN else ink)
            x += column
        y += height
    if not rows:
        draw.text((margin + 16, y + 28), "\u672c\u8303\u56f4\u6682\u65e0\u53ef\u7edf\u8ba1\u7684\u771f\u5b9e\u51fa\u5200\u8bb0\u5f55\u3002", font=fonts[28], fill=muted)
    x = margin
    for column in [0] + columns:
        x += column
        draw.line((x, table_top, x, footer_top), fill=grid)
    draw.line((margin, footer_top, width - margin, footer_top), fill=grid)
    for index, line in enumerate(note_lines):
        draw.text((margin, footer_top + 24 + index * 34), line, font=fonts[24], fill=muted)
    return _save_image(image, path)


def render_clan_status(real_status, path, clan_state=None, account=None) -> Path:
    """Render five unframed boss rows using the same data as the text reply."""
    from PIL import Image, ImageDraw, ImageFont

    try:
        from .clan_state import _challenge_text, _real_header_lines, build_clan_status_rows
    except ImportError:
        from clan_state import _challenge_text, _real_header_lines, build_clan_status_rows

    status = real_status if isinstance(real_status, dict) else {}
    width, margin, row_height = 1280, 32, 184
    fonts = {size: _load_font(ImageFont, size) for size in (24, 28, 30, 34, 40)}
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1), "white"))
    header_lines = [line for text in _real_header_lines(clan_state or {}, account, status)
                    for line in _wrap_text(measure, text, fonts[28], width - 2 * margin)]
    table_top = 96 + len(header_lines) * 40 + 20
    rows = build_clan_status_rows(status)
    image = Image.new("RGB", (width, table_top + len(rows) * row_height + 44), "white")
    draw = ImageDraw.Draw(image)
    ink, muted, grid = "#20262c", "#606a73", "#dce2e7"
    draw.rectangle((0, 0, width, 8), fill="#17785b")
    draw.text((margin, 26), "\u4f1a\u6218\u72b6\u6001", font=fonts[40], fill=ink)
    for index, line in enumerate(header_lines):
        draw.text((margin, 88 + index * 40), line, font=fonts[28], fill=ink)
    for index, row in enumerate(rows):
        y = table_top + index * row_height
        if index % 2:
            draw.rectangle((margin, y, width - margin, y + row_height), fill="#f8fafb")
        draw.line((margin, y, width - margin, y), fill=grid)
        draw.text((margin + 16, y + 18), f"{row['order_num']}\u738b", font=fonts[34], fill=ink)
        lap = f"{row['lap_num']}\u5468\u76ee" if row["lap_num"] is not None else "\u5468\u76ee\u672a\u77e5"
        phase = f"{row['phase']}\u9636\u6bb5" if row["phase"] is not None else "\u9636\u6bb5\u672a\u77e5"
        _draw_cell(draw, lap, margin + 132, y + 10, 220, 60,
                   _fit_font(draw, lap, ImageFont, 30, 208), ink)
        _draw_cell(draw, phase, margin + 352, y + 10, 188, 60,
                   _fit_font(draw, phase, ImageFont, 28, 176), ink)
        challenge = _challenge_text(row["can_challenge"])
        draw.text((margin + 560, y + 24), challenge, font=fonts[28],
                  fill="#b34b43" if row["can_challenge"] is False else muted)
        active = f"\u5f53\u524d{row['attacking_count']}\u4eba\u51fa\u5200" if row["attacking_count"] is not None else "\u51fa\u5200\u4eba\u6570\u672a\u77e5"
        draw.text((width - margin - 16, y + 24), active, font=fonts[28], fill=muted, anchor="ra")
        hp = f"{row['current_hp']:,}" if row["current_hp"] is not None else UNKNOWN
        maximum = f"{row['max_hp']:,}" if row["max_hp"] is not None else UNKNOWN
        health = f"\u5f53\u524dHP {hp} / \u6700\u5927HP {maximum}"
        draw.text((margin + 16, y + 80), health,
                  font=_fit_font(draw, health, ImageFont, 28, 960), fill=ink)
        draw.text((width - margin - 16, y + 84), row["hp_percent"], font=fonts[28], fill=muted, anchor="ra")
        left, right = margin + 16, width - margin - 16
        draw.rectangle((left, y + 140, right, y + 154), fill="#e4e9eb")
        if row["hp_percent"] != UNKNOWN:
            fraction = max(0, min(1, row["current_hp"] / row["max_hp"]))
            if fraction:
                draw.rectangle((left, y + 140, left + (right - left) * fraction, y + 154), fill="#258c6a")
    draw.line((margin, table_top + len(rows) * row_height, width - margin,
               table_top + len(rows) * row_height), fill=grid)
    return _save_image(image, path)


def render_text_image(text, output_path, title=None):
    from PIL import Image, ImageDraw, ImageFont

    width, padding, gap = 1280, 36, 12
    font, title_font = _load_font(ImageFont, 28), _load_font(ImageFont, 36)
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1), "white"))
    lines = []
    if title:
        lines.extend((line, title_font) for line in _wrap_text(measure, str(title), title_font, width - 2 * padding))
    lines.extend((line, font) for line in _wrap_text(measure, str(text or ""), font, width - 2 * padding))
    heights = [active_font.getbbox("Ag\u56fd")[3] + gap for _, active_font in lines]
    image = Image.new("RGB", (width, max(240, sum(heights) + padding * 2)), "white")
    draw = ImageDraw.Draw(image)
    y = padding
    for (line, active_font), height in zip(lines, heights):
        draw.text((padding, y), line, fill="#20262c", font=active_font)
        y += height
    return _save_image(image, output_path)


def _report_notes(status, rows):
    status = status if isinstance(status, dict) else {}
    history = _damage_history(status)
    notes = list(status.get("presentation_notes") or [])
    notes.append(_scope_line(status))
    complete = status.get("damage_history_complete") is True or status.get("history_complete") is True
    if complete:
        notes.append(f"\u7edf\u8ba1\u8303\u56f4\uff1a\u63a5\u53e3\u660e\u786e\u8fd4\u56de\u7684\u5b8c\u6574\u5386\u53f2\uff0c\u5171{len(history)}\u6761\uff1b\u4e0d\u81ea\u52a8\u7b49\u540c\u5168\u6708\u3002")
    else:
        notes.append(f"\u7edf\u8ba1\u8303\u56f4\uff1a\u4ec5\u63a5\u53e3\u5df2\u8fd4\u56de\u7684{len(history)}\u6761\u8bb0\u5f55\uff0c\u5386\u53f2\u5b8c\u6574\u6027\u672a\u786e\u8ba4\uff0c\u4e0d\u4ee3\u8868\u5168\u6708\u7edf\u8ba1\u3002")
    if not _members(status):
        notes.append("\u672a\u8fd4\u56de\u5b8c\u6574\u516c\u4f1a\u6210\u5458\u540d\u5355\uff0c0\u5200\u6210\u5458\u65e0\u6cd5\u51ed\u7a7a\u7edf\u8ba1\u3002")
    else:
        notes.append("0\u5200\u4ec5\u8868\u793a\u672c\u7edf\u8ba1\u8303\u56f4\u672a\u89c1\u51fa\u5200\uff1b\u6210\u5458\u540d\u5355\u6309\u63a5\u53e3\u8fd4\u56de\u5c55\u793a\u3002")
    if any(row["records"] and not row["score_complete"] for row in rows):
        notes.append("\u5206\u6570\u672a\u5b8c\u6574\u8fd4\u56de\uff1a\u672a\u77e5\u4e0d\u4f5c0\uff1b\u6587\u672c\u5206\u6570\u5360\u6bd4\u4ec5\u6309\u5df2\u77e5\u5b8c\u6574\u5206\u6570\u8ba1\u7b97\uff0c\u56fe\u7247\u4e0d\u663e\u793a\u5168\u4f1a\u5206\u6570\u5360\u6bd4\u3002")
        notes.append("\u6392\u540d\u6309\u672c\u8303\u56f4\u4f24\u5bb3\u6392\u5e8f\uff1b\u5206\u6570\u5b8c\u6574\u65f6\u6309\u5206\u6570\u6392\u5e8f\u3002")
    if any(row["compensation_records"] for row in rows):
        notes.append("\u51fa\u5200\u6b21\u6570\uff1a\u4ec5\u660e\u786e\u8865\u507f\u6807\u8bb0\u8ba10.5\u5200\uff0c\u5176\u4f59\u8bb0\u5f55\u8ba11\u5200\uff1bkill\u6216finish_time\u4e0d\u4f5c\u4e3a\u8865\u507f\u4f9d\u636e\u3002")
    else:
        notes.append("\u51fa\u5200\u6b21\u6570\u6309\u5df2\u8fd4\u56de\u8bb0\u5f55\u8ba1\u6570\uff1b\u65e0\u660e\u786e\u8865\u507f\u6807\u8bb0\u4e0d\u6298\u5200\uff0ckill\u4e0d\u7b49\u540c\u8865\u507f\uff0c\u4e0d\u80fd\u636e\u6b64\u63a8\u7b97\u5b8c\u6574\u5200\u6d88\u8017\u3002")
    if any(not row["viewer_id"] for row in rows):
        notes.append("\u90e8\u5206\u8bb0\u5f55\u65e0viewer_id\uff0c\u4ec5\u6309\u539f\u59cb\u6e38\u620f\u540d\u5f52\u7ec4\uff0c\u8eab\u4efd\u672a\u786e\u8ba4\uff0c\u4e0d\u4e0e\u6709ID\u73a9\u5bb6\u5408\u5e76\u3002")
    if any(not row["damage_complete"] for row in rows):
        notes.append("\u90e8\u5206\u4f24\u5bb3\u672a\u8fd4\u56de\uff0c\u672a\u77e5\u4e0d\u4f5c0\uff0c\u603b\u89c8\u4ec5\u5217\u51fa\u5df2\u77e5\u4f24\u5bb3\u3002")
    notes.append("\u5206\u6570\u53ca\u4f24\u5bb3\u5747\u6765\u81ea\u63a5\u53e3\uff1b\u6587\u672c\u4e2d\u7684 - \u8868\u793a\u672a\u77e5\u6216\u65e0\u53ef\u7528\u5206\u6bcd\u3002")
    return notes


def _scope_line(status):
    scope = status.get("history_scope")
    scope = _clean_text(scope) if isinstance(scope, str) else ""
    return f"\u7edf\u8ba1\u8303\u56f4\uff1a{scope or '\u4ec5\u5df2\u91c7\u96c6\u8bb0\u5f55'} | \u672c\u8868{len(_damage_history(status))}\u6761\u8bb0\u5f55"


def _damage_history(real_status, current_period_only=True):
    if not isinstance(real_status, dict):
        return []
    value = real_status.get("damage_history")
    if not isinstance(value, list):
        return []
    result, seen = [], set()
    battle = real_status.get("clan_battle")
    battle = battle if isinstance(battle, dict) else {}
    for item in value:
        if not isinstance(item, dict):
            continue
        if current_period_only and not real_status.get("report_command") and not _same_period(item, battle):
            continue
        identifier = next(((key, str(item[key])) for key in ("history_id", "battle_log_id", "mylog_id")
                           if item.get(key) is not None and str(item[key]).strip()), None)
        identity = (
            str(item.get("clan_battle_id", battle.get("id"))),
            str(item.get("period", battle.get("period"))),
            str(item.get("period_id", battle.get("period_id"))),
            identifier,
        )
        if identifier is not None and identity in seen:
            continue
        if identifier is not None:
            seen.add(identity)
        result.append(item)
    return result


def _members(real_status):
    if not isinstance(real_status, dict):
        return []
    sources = [real_status]
    if isinstance(real_status.get("clan"), dict):
        sources.append(real_status["clan"])
    members = []
    for source in sources:
        for key in ("members", "clan_members", "member_list", "clan_member_list"):
            if isinstance(source.get(key), list):
                members.extend(source[key])
    return members


def _member_names(real_status):
    return list(dict.fromkeys(_member_name(item) for item in _members(real_status) if _member_name(item)))


def _viewer_id(item):
    if not isinstance(item, dict):
        return None
    for key in ("viewer_id", "player_viewer_id"):
        value = item.get(key)
        if value is not None and str(value).strip() not in {"", "0"}:
            return str(value).strip()
    return None


def _member_name(item):
    if isinstance(item, str):
        return _clean_text(item)
    if not isinstance(item, dict):
        return ""
    for key in ("name", "user_name", "viewer_name", "nickname"):
        value = item.get(key)
        if value is not None and str(value).strip():
            return _clean_text(str(value))
    return ""


def _clean_text(value):
    return " ".join(value.split())


def _score_value(item):
    for key in ("score", "damage_score", "battle_score", "score_damage"):
        value = _number(item.get(key))
        if value is not None:
            return value
    return None


def _number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = Decimal(str(value))
        if number.is_finite() and number == number.to_integral_value():
            return int(number)
    except (InvalidOperation, TypeError, ValueError, OverflowError):
        pass
    return None


def _int_value(value):
    value = _number(value)
    return value if value is not None else 0


def _flag(value):
    if value is True or value == 1 or (isinstance(value, str) and value.lower() in {"true", "1"}):
        return True
    if value is False or value == 0 or (isinstance(value, str) and value.lower() in {"false", "0"}):
        return False
    return None


def _hit_weight(item):
    if any(_flag(item.get(key)) is True for key in ("is_extra_time", "is_compensation")):
        return 0.5
    return 1


def _count_text(value):
    return f"{value:g}"


def _percent(value, total):
    if not total:
        return "-"
    return f"{value / total * 100:.2f}%"


def _same_period(item, battle):
    for actual_key, current_key in (("clan_battle_id", "id"), ("period", "period"), ("period_id", "period_id")):
        actual, current = item.get(actual_key), battle.get(current_key)
        if actual is not None and current is not None and str(actual) != str(current):
            return False
    return True


def _timestamp(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
        if number > 100_000_000_000:
            number /= 1000
        if number < 946_684_800:
            return None
        return datetime.fromtimestamp(number, timezone.utc)
    except (ValueError, TypeError, OverflowError, OSError):
        pass
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result if result.tzinfo else result.replace(tzinfo=timezone(timedelta(hours=8)))
    except (ValueError, TypeError):
        return None


def _item_time(item):
    for key in ("create_time", "battle_end_time", "end_time", "battle_time", "timestamp"):
        value = _timestamp(item.get(key))
        if value is not None:
            return value
    return None


def _wrap_text(draw, text, font, max_width):
    lines = []
    for paragraph in str(text).splitlines() or [""]:
        line = ""
        for character in paragraph.expandtabs(4):
            if line and draw.textlength(line + character, font=font) > max_width:
                lines.append(line)
                line = ""
            line += character
        lines.append(line)
    return lines


def _fit_font(draw, text, image_font, size, max_width):
    font = _load_font(image_font, size)
    while size > 8 and draw.textlength(str(text), font=font) > max_width:
        size -= 1
        font = _load_font(image_font, size)
    return font


def _draw_cell(draw, text, x, y, width, height, font, fill):
    draw.text((x + width / 2, y + height / 2), str(text), font=font, fill=fill, anchor="mm")


def _save_image(image, output_path):
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return path


def _load_font(image_font, size):
    candidates = [
        "C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/wqy-microhei/wqy-microhei.ttc",
    ]
    for candidate in candidates:
        try:
            return image_font.truetype(candidate, size)
        except OSError:
            continue
    raise RuntimeError("\u672a\u627e\u5230\u4e2d\u6587\u5b57\u4f53\uff0c\u8bf7\u5b89\u88c5\u6587\u6cc9\u9a7f\u6b63\u9ed1\u6216\u5fae\u8f6f\u96c5\u9ed1\u5b57\u4f53\u3002")
