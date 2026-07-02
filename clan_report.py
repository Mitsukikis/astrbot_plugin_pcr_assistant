from collections import defaultdict
from pathlib import Path


EMPTY_DATABASE_TEXT = "\u6570\u636e\u5e93\u4e3a\u7a7a\uff0c\u8bf7\u786e\u4fdd\u5f00\u542f\u51fa\u5200\u76d1\u63a7"


def build_damage_count_summary(real_status):
    history = _damage_history(real_status)
    roster = _member_names(real_status)
    if not history and not roster:
        return EMPTY_DATABASE_TEXT

    counts = defaultdict(int)
    for item in history:
        name = _member_name(item)
        if name:
            counts[name] += 1

    for name in roster:
        counts.setdefault(name, 0)

    total = sum(counts.values())
    lines = [
        "\u4ee5\u4e0b\u662f\u51fa\u5200\u6b21\u6570\u7edf\u8ba1:",
        f"\u603b\u8ba1\u51fa\u5200: {total}",
    ]
    for count in (3, 2, 1, 0):
        names = [name for name in roster if counts.get(name, 0) == count]
        names.extend(
            name for name, value in sorted(counts.items())
            if value == count and name not in roster
        )
        if names:
            lines.extend([
                "----------",
                f"\u4ee5\u4e0b\u662f\u51fa\u4e86{count}\u5200\u7684\u6210\u5458: {'|'.join(names)}",
            ])
    if not roster:
        lines.extend([
            "----------",
            "\u672a\u8fd4\u56de\u5b8c\u6574\u516c\u4f1a\u6210\u5458\u540d\u5355\uff0c0\u5200\u6210\u5458\u65e0\u6cd5\u51ed\u7a7a\u7edf\u8ba1\u3002",
        ])
    return "\n".join(lines)


def build_current_report_text(real_status):
    rows = build_current_report_rows(real_status)
    header = "\u6392\u540d | \u6635\u79f0 | \u51fa\u5200\u6b21\u6570 | \u9020\u6210\u4f24\u5bb3 | \u5206\u6570 | \u4f24\u5bb3\u5360\u6bd4 | \u5206\u6570\u5360\u6bd4"
    if not rows:
        return EMPTY_DATABASE_TEXT
    lines = [header]
    for row in rows:
        lines.append(
            f"{row['rank']} | {row['name']} | {row['hits']} | "
            f"{row['damage']} | {row['score']} | "
            f"{row['damage_percent']} | {row['score_percent']}"
        )
    return "\n".join(lines)


def build_current_report_rows(real_status):
    history = _damage_history(real_status)
    by_name = {}
    for item in history:
        name = _member_name(item)
        if not name:
            continue
        row = by_name.setdefault(name, {"name": name, "hits": 0, "damage": 0, "score": None})
        row["hits"] += 1
        row["damage"] += _int_value(item.get("damage"))
        score = _score_value(item)
        if score is not None:
            row["score"] = (row["score"] or 0) + score

    rows = list(by_name.values())
    total_damage = sum(row["damage"] for row in rows)
    total_score = sum(row["score"] or 0 for row in rows)
    rows.sort(key=lambda row: (row["score"] or 0, row["damage"], row["hits"], row["name"]), reverse=True)

    for index, row in enumerate(rows, start=1):
        row["rank"] = index
        row["damage_percent"] = _percent(row["damage"], total_damage)
        row["score_percent"] = _percent(row["score"], total_score) if row["score"] is not None else "-"
        row["score"] = str(row["score"]) if row["score"] is not None else "-"
    return rows


def render_text_image(text, output_path, title=None):
    from PIL import Image, ImageDraw, ImageFont

    lines = []
    if title:
        lines.append(str(title))
    lines.extend(str(text or "").splitlines() or [""])
    font = _load_font(ImageFont, 28)
    title_font = _load_font(ImageFont, 34)
    padding_x = 36
    padding_y = 30
    line_gap = 12

    measure_image = Image.new("RGB", (10, 10), "#fffaf0")
    measure = ImageDraw.Draw(measure_image)
    widths = []
    heights = []
    for index, line in enumerate(lines):
        active_font = title_font if title and index == 0 else font
        bbox = measure.textbbox((0, 0), line, font=active_font)
        widths.append(bbox[2] - bbox[0])
        heights.append(bbox[3] - bbox[1] + line_gap)
    width = max(widths or [0]) + padding_x * 2
    height = sum(heights or [40]) + padding_y * 2

    image = Image.new("RGB", (max(width, 640), max(height, 240)), "#fffaf0")
    draw = ImageDraw.Draw(image)
    y = padding_y
    for index, line in enumerate(lines):
        active_font = title_font if title and index == 0 else font
        draw.text((padding_x, y), line, fill="#6b5a4a", font=active_font)
        y += heights[index]

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return path


def _damage_history(real_status):
    if not isinstance(real_status, dict):
        return []
    value = real_status.get("damage_history") or []
    return value if isinstance(value, list) else []


def _member_names(real_status):
    if not isinstance(real_status, dict):
        return []
    candidates = [
        real_status.get("members"),
        real_status.get("clan_members"),
        real_status.get("member_list"),
    ]
    clan = real_status.get("clan")
    if isinstance(clan, dict):
        candidates.extend([
            clan.get("members"),
            clan.get("clan_members"),
            clan.get("member_list"),
        ])
    names = []
    for candidate in candidates:
        if not isinstance(candidate, list):
            continue
        for item in candidate:
            name = _member_name(item)
            if name and name not in names:
                names.append(name)
    return names


def _member_name(item):
    if isinstance(item, str):
        return item.strip()
    if not isinstance(item, dict):
        return ""
    for key in ("name", "user_name", "viewer_name", "nickname"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    value = item.get("viewer_id")
    return str(value).strip() if value else ""


def _score_value(item):
    for key in ("score", "damage_score", "battle_score", "score_damage"):
        if key in item and item.get(key) is not None:
            return _int_value(item.get(key))
    return None


def _int_value(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _percent(value, total):
    if not total:
        return "-"
    return f"{value / total * 100:.2f}%"


def _load_font(image_font, size):
    candidates = [
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/wqy-microhei/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        try:
            return image_font.truetype(candidate, size)
        except OSError:
            continue
    return image_font.load_default()
