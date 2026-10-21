from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

try:
    from .pcr_chara import id_from_unit_id, name_for_id
except ImportError:
    from pcr_chara import id_from_unit_id, name_for_id


def _font(size):
    for path in (
        'C:/Windows/Fonts/msyh.ttc',
        '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _wrap(draw, text, font, width):
    lines, line = [], ''
    for char in str(text):
        if line and draw.textlength(line + char, font=font) > width:
            lines.append(line)
            line = ''
        line += char
    if line:
        lines.append(line)
    return lines or ['']


def _unit(draw, image, chara_id, x, y, icon_provider, size=90):
    icon = icon_provider(int(chara_id)) if icon_provider else None
    if icon is not None:
        icon = icon.convert('RGB').resize((size, size), Image.Resampling.LANCZOS)
        image.paste(icon, (x, y))
    else:
        draw.rectangle((x, y, x + size, y + size), fill='#edf1f4')
        draw.text((x + 8, y + 30), '暂无头像', font=_font(17), fill='#56616b')
    draw.rectangle((x, y, x + size, y + size), outline='#cdd6dd', width=1)
    font = _font(18)
    for index, line in enumerate(_wrap(draw, name_for_id(int(chara_id)), font, size + 12)[:3]):
        draw.text((x, y + size + 8 + index * 23), line, font=font, fill='#26333d')


def _save(image, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format='PNG')
    return path


def render_arena_recognition(teams, output_path, icon_provider=None):
    width, row_height = 760, 225
    image = Image.new('RGB', (width, 108 + len(teams) * row_height + 42), 'white')
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, 79), fill='#145e63')
    draw.text((30, 21), '竞技场 · 阵容识别', font=_font(30), fill='white')
    for number, team in enumerate(teams):
        top = 100 + number * row_height
        draw.text((30, top), team.get('label') or f'防守队伍 {number + 1}', font=_font(21), fill='#145e63')
        for column, chara_id in enumerate(team['ids']):
            _unit(draw, image, chara_id, 30 + column * 145, top + 37, icon_provider)
        draw.line((30, top + row_height - 8, width - 30, top + row_height - 8), fill='#e0e6e9')
    draw.text((30, image.height - 32), '角色头像与名称按识别结果展示', font=_font(16), fill='#64727a')
    return _save(image, output_path)


def render_arena_solutions(defender_ids, entries, output_path, icon_provider=None, region=1):
    entries = list(entries or [])[:10]
    width, row_height = 900, 194
    image = Image.new('RGB', (width, 290 + max(1, len(entries)) * row_height + 52), 'white')
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, 76), fill='#145e63')
    region_name = {1: '全服', 2: '国服', 3: '台服', 4: '日服'}.get(region, '全服')
    draw.text((28, 18), f'竞技场作业 · {region_name}', font=_font(30), fill='white')
    draw.text((28, 91), '防守阵容', font=_font(21), fill='#145e63')
    for column, chara_id in enumerate(defender_ids):
        _unit(draw, image, chara_id, 28 + column * 145, 126, icon_provider, 82)
    for number, entry in enumerate(entries):
        top = 290 + number * row_height
        if number % 2 == 0:
            draw.rectangle((0, top, width, top + row_height), fill='#f3f6f8')
        draw.text((22, top + 14), f'{number + 1:02d}', font=_font(22), fill='#145e63')
        for column, unit in enumerate((entry.get('atk') or [])[:5]):
            unit_id = unit.get('id') if isinstance(unit, dict) else unit
            try:
                chara_id = id_from_unit_id(int(unit_id))
            except (TypeError, ValueError):
                continue
            x = 72 + column * 130
            _unit(draw, image, chara_id, x, top + 16, icon_provider, 80)
            if isinstance(unit, dict) and unit.get('star'):
                draw.text((x + 4, top + 74), f"{unit['star']}星", font=_font(15), fill='#145e63', stroke_width=1, stroke_fill='white')
        up = int(entry.get('up') or 0)
        down = int(entry.get('down') or 0)
        draw.text((750, top + 26), f'赞  {up}', font=_font(20), fill='#147b54')
        draw.text((750, top + 60), f'踩  {down}', font=_font(20), fill='#a24848')
        draw.text((750, top + 102), str(entry.get('qkey') or ''), font=_font(18), fill='#64727a')
    if not entries:
        draw.text((30, 326), '未找到该防守阵容的作业', font=_font(26), fill='#64727a')
    draw.text((28, image.height - 36), '数据来源：pcrdfans.com · 用户提交的作业不代表必胜', font=_font(18), fill='#64727a')
    return _save(image, output_path)


def render_clan_damage_detail(status, output_path, icon_provider=None):
    history = status.get('damage_history') or []
    record = history[0] if history else {}
    units = list(status.get('unit_damage_detail') or [])[:10]
    width, row_height = 900, 94
    image = Image.new('RGB', (width, 260 + max(1, len(units)) * row_height + 52), 'white')
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, 76), fill='#145e63')
    draw.text((28, 18), '会战 · 出刀详情', font=_font(30), fill='white')
    title = str(record.get('name') or record.get('viewer_id') or '玩家名未知')
    for line_no, line in enumerate(_wrap(draw, title, _font(25), width - 56)[:2]):
        draw.text((28, 90 + line_no * 32), line, font=_font(25), fill='#26333d')
    draw.text((28, 160), f"记录 #{record.get('history_id', '-')} · {record.get('lap_num', '-')}周目{record.get('order_num', '-')}王", font=_font(23), fill='#64727a')
    damage = record.get('damage')
    draw.text((28, 202), '总伤害：' + (f'{int(damage):,}' if damage is not None else '未返回'), font=_font(23), fill='#26333d')
    for index, unit in enumerate(units):
        y = 260 + index * row_height
        cid = id_from_unit_id(int(unit.get('unit_id') or 100001))
        icon = icon_provider(cid) if icon_provider else None
        if icon is not None:
            image.paste(icon.convert('RGB').resize((72,72), Image.Resampling.LANCZOS), (28,y+10))
        name = name_for_id(cid)
        name_font = _font(23)
        while draw.textlength(name, font=name_font) > width - 400 and name_font.size > 12:
            name_font = _font(name_font.size - 1)
        for line_no, line in enumerate(_wrap(draw, name, name_font, width - 400)[:2]):
            draw.text((120,y+8+line_no*24), line, font=name_font, fill='#26333d')
        value = unit.get('damage')
        draw.text((width-30,y+12), f'{int(value):,}' if value is not None else '未返回', anchor='ra', font=_font(24), fill='#26333d')
        draw.rectangle((120,y+60,width-30,y+70),fill='#e0e6e9')
        if value is not None and damage and int(damage)>0:
            ratio = min(1,max(0,int(value)/int(damage)))
            draw.rectangle((120,y+60,120+(width-150)*ratio,y+70),fill='#258c6a')
    if not units:
        draw.text((28,285),'接口未返回角色伤害明细。',font=_font(24),fill='#64727a')
    draw.text((28,image.height-36),'角色伤害来自该出刀记录的游戏战报。',font=_font(18),fill='#64727a')
    return _save(image, output_path)
