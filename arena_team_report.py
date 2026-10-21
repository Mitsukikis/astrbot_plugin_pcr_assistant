"""A single long report of complete, non-overlapping arena attack plans."""

import io
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw

try:
    from .pcr_cards import _font, _wrap
    from .pcr_chara import name_for_id
except ImportError:
    from pcr_cards import _font, _wrap
    from pcr_chara import name_for_id


def render_team_plans(defenses, plans, output_path, icon_provider=None, region=1, candidate_counts=()):
    payload = compose_team_plans_bytes(defenses, plans, icon_provider, region, candidate_counts)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def compose_team_plans_bytes(defenses, plans, icon_provider=None, region=1, candidate_counts=()):
    if not 2 <= len(defenses) <= 3 or len(plans) > 10:
        raise ValueError('expected two or three defense teams and at most ten plans')
    width = 1000
    measure = ImageDraw.Draw(Image.new('RGB', (width, 1), 'white'))
    headings = []
    for index, defense in enumerate(defenses, 1):
        names = ' / '.join(name_for_id(cid) for cid in defense['ids'])
        headings.extend(_wrap(measure, f'防守 {index}：{names}', _font(20), width - 56))
    top = 110 + 28 * len(headings) + 30
    row_height = 195
    plan_height = 56 + len(defenses) * row_height + 20
    height = top + (len(plans) * plan_height if plans else 230) + 100
    image = Image.new('RGB', (width, height), 'white')
    draw = ImageDraw.Draw(image)
    region_name = {1: '全部角色', 2: '国服', 3: '台服', 4: '日服'}[region]
    draw.rectangle((0, 0, width, 76), fill='#145e63')
    draw.text((28, 18), f'公主竞技场 · 联合解法 · {region_name}', font=_font(28), fill='white')
    for index, line in enumerate(headings):
        draw.text((28, 94 + index * 28), line, font=_font(20), fill='#26333d')
    for number, plan in enumerate(plans, 1):
        if len(plan) != len(defenses):
            raise ValueError('incomplete plan')
        ids = [cid for option in plan for cid in option['ids']]
        if len(ids) != 5 * len(defenses) or len(set(ids)) != len(ids):
            raise ValueError('plan reuses a character')
        y = top + (number - 1) * plan_height
        draw.rectangle((0, y, width, y + 46), fill='#edf4f4')
        draw.text((28, y + 8), f'方案 {number:02d}  ·  本套角色不重复', font=_font(23), fill='#145e63')
        for team_index, option in enumerate(plan, 1):
            _draw_attack(image, draw, option, y + 56 + (team_index - 1) * row_height,
                         team_index, icon_provider)
    if not plans:
        draw.text((28, top + 36), '当前候选中没有完整的不重人组合', font=_font(28), fill='#a24848')
        counts = ' / '.join(str(count) for count in candidate_counts)
        draw.text((28, top + 90), f'各队可确认身份的候选：{counts or "0"}', font=_font(23), fill='#26333d')
        draw.text((28, top + 132), '不会使用冲突角色或缺失队伍拼成完整方案。', font=_font(22), fill='#64727a')
    footer = image.height - 86
    draw.text((28, footer), f'来源：pcrdfans.com · 实际可用组合 {len(plans)} 套 · 各套独立选择',
              font=_font(20), fill='#64727a')
    draw.text((28, footer + 28), '网页作业组合，不是战斗模拟；点赞不等于胜率。', font=_font(19), fill='#64727a')
    draw.text((28, footer + 54), f'查询时间：{datetime.now():%Y-%m-%d %H:%M:%S}（服务器时间）',
              font=_font(17), fill='#64727a')
    output = io.BytesIO()
    image.save(output, format='PNG')
    return output.getvalue()


def _draw_attack(image, draw, option, top, index, icon_provider):
    draw.text((28, top + 38), str(index), font=_font(25), fill='#145e63')
    payload = option.get('image')
    if payload:
        if not isinstance(payload, bytes) or len(payload) > 8_000_000:
            raise ValueError('invalid attack strip payload')
        with Image.open(io.BytesIO(payload)) as source:
            if not 120 <= source.width <= 1600 or not 24 <= source.height <= 400:
                raise ValueError('invalid attack strip bounds')
            strip = source.convert('RGB')
            size = (590, min(125, round(strip.height * 590 / strip.width)))
            strip.thumbnail(size, Image.Resampling.LANCZOS)
            # Upscale small website sprites as a complete strip, preserving stars.
            if strip.width < size[0]:
                scale = min(size[0] / strip.width, size[1] / strip.height)
                strip = strip.resize((round(strip.width * scale), round(strip.height * scale)), Image.Resampling.LANCZOS)
            image.paste(strip, (70, top))
    else:
        for column, cid in enumerate(option['ids']):
            x = 70 + column * 116
            icon = icon_provider(cid) if icon_provider else None
            if icon is not None:
                image.paste(icon.convert('RGB').resize((94, 94), Image.Resampling.LANCZOS), (x, top + 5))
            else:
                draw.rectangle((x, top + 5, x + 94, top + 99), fill='#edf1f4')
    names = ' / '.join(name_for_id(cid) for cid in option['ids'])
    for line_index, line in enumerate(_wrap(draw, names, _font(18), 590)[:3]):
        draw.text((70, top + 128 + line_index * 21), line, font=_font(18), fill='#26333d')
    details = f'对应防守第 {index} 队\n' + str(option.get('metadata') or '来源：网页作业')
    lines = [wrapped for line in details.splitlines()[:5]
             for wrapped in _wrap(draw, line, _font(20), 294)]
    for line_index, line in enumerate(lines[:6]):
        draw.text((686, top + 8 + line_index * 27), line, font=_font(20), fill='#56616b')
    draw.line((28, top + 188, 972, top + 188), fill='#e0e6e9')
