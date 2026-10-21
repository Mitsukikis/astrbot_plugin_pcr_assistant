"""Offline fixtures only: never bundle screenshots or fetch artwork in tests."""

import asyncio
import io
import time
from threading import Lock

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFilter

import pcr_image_recognizer as recognition
from pcr_image_recognizer import ImageRecognitionError, PcrImageRecognizer


def portrait(seed):
    rng = np.random.default_rng(seed)
    image = Image.fromarray(rng.integers(30, 220, (8, 8, 3), dtype=np.uint8)).resize((80, 80))
    draw = ImageDraw.Draw(image)
    draw.ellipse((12, 8, 65, 72), outline=tuple(rng.integers(0, 255, 3)), width=3)
    for _ in range(12):
        x, y = rng.integers(12, 60, 2)
        draw.rectangle((int(x), int(y), int(x + 8), int(y + 6)),
                       fill=tuple(rng.integers(0, 255, 3)))
    return image


@pytest.fixture
def templates():
    return {1001 + i: portrait(i) for i in range(30)}


def layout(tmp_path, templates, *, rows=1, paired=False, size=64, blur=0,
           duplicate=False, unknown=False, padding=(47, 73)):
    x0, y0 = padding
    pitch, row_pitch = size + 8, size + 43
    column_pitch = pitch * 5 + 75
    width = x0 * 2 + pitch * 5 - 8 + (column_pitch if paired else 0)
    image = Image.new('RGB', (width, y0 * 2 + (rows - 1) * row_pitch + size), (240, 243, 247))
    draw = ImageDraw.Draw(image)
    expected = []
    for row in range(rows):
        for column in range(2 if paired else 1):
            ids, boxes = [], []
            for slot in range(5):
                index = (row * (2 if paired else 1) + column) * 5 + slot
                chara_id = 1001 + (0 if duplicate and index == 4 else index)
                icon = portrait(999) if unknown and index == 4 else templates[chara_id]
                icon = icon.resize((size, size), Image.Resampling.LANCZOS)
                if blur:
                    icon = icon.filter(ImageFilter.GaussianBlur(blur))
                x, y = x0 + column * column_pitch + slot * pitch, y0 + row * row_pitch
                draw.rectangle((x - 2, y - 2, x + size + 1, y + size + 1), fill=(55, 59, 62))
                image.paste(icon, (x, y))
                ids.append(chara_id)
                boxes.append([x, y, x + size, y + size])
            expected.append((ids, boxes))
    path = tmp_path / 'layout.png'
    image.save(path)
    return path, expected


@pytest.mark.parametrize('rows,paired', [(1, False), (3, False), (1, True), (3, True)])
def test_layout_and_original_boxes(tmp_path, templates, rows, paired):
    path, expected = layout(tmp_path, templates, rows=rows, paired=paired)
    recognizer = PcrImageRecognizer(templates=templates)
    teams = recognizer.recognize_teams(path, side='all')
    assert [t['ids'] for t in teams] == [e[0] for e in expected]
    for team, (_, boxes) in zip(teams, expected):
        assert len(team['scores']) == 5
        assert min(team['scores']) >= recognizer.threshold
        for actual, wanted in zip(team['boxes'], boxes):
            assert max(abs(a - b) for a, b in zip(actual, wanted)) <= 4
    defense = recognizer.recognize_teams(path)
    assert [t['ids'] for t in defense] == [e[0] for e in (expected[1::2] if paired else expected)]
    if paired:
        assert [t['label'] for t in defense] == [f'defense_{i + 1}' for i in range(rows)]
        assert [t['ids'] for t in recognizer.recognize_teams(path, 'attack')] == [e[0] for e in expected[::2]]
    if rows == 1:
        assert recognizer.recognize_file(path) == defense[0]['ids']
    else:
        with pytest.raises(ImageRecognitionError, match='多队'):
            recognizer.recognize_file(path)


@pytest.mark.parametrize('size', [28, 40, 96, 128])
def test_resized_avatars(tmp_path, templates, size):
    path, expected = layout(tmp_path, templates, size=size)
    assert PcrImageRecognizer(templates=templates).recognize_file(path) == expected[0][0]


@pytest.mark.parametrize('options', [dict(blur=5), dict(duplicate=True), dict(unknown=True)])
def test_rejects_bad_selected_team(tmp_path, templates, options):
    path, _ = layout(tmp_path, templates, **options)
    with pytest.raises(ImageRecognitionError):
        PcrImageRecognizer(templates=templates).recognize_teams(path)


def test_ambiguous_templates_are_not_forced_to_unique_ids(tmp_path, templates):
    path, _ = layout(tmp_path, templates)
    templates[2001] = templates[1001].copy()
    with pytest.raises(ImageRecognitionError, match='歧义'):
        PcrImageRecognizer(templates=templates).recognize_file(path)


def test_blurred_right_half_cannot_become_own_left_teams(tmp_path, templates):
    path, expected = layout(tmp_path, templates, rows=3, paired=True)
    with Image.open(path) as source:
        image = source.copy()
    x = expected[1][1][0][0] - 10
    image.paste(image.crop((x, 0, image.width, image.height)).filter(
        ImageFilter.GaussianBlur(12)), (x, 0))
    image.save(path)
    with pytest.raises(ImageRecognitionError):
        PcrImageRecognizer(templates=templates).recognize_teams(path)


def test_variants_compete_per_character_not_per_image(tmp_path, templates):
    path, expected = layout(tmp_path, templates)
    templates[1001] = [portrait(1234), templates[1001], templates[1001].copy()]
    assert PcrImageRecognizer(templates=templates).recognize_file(path) == expected[0][0]


def test_empty_invalid_and_incomplete_images(tmp_path, templates):
    recognizer = PcrImageRecognizer(templates=templates)
    path = tmp_path / 'blank.png'
    Image.new('RGB', (800, 400), 'white').save(path)
    with pytest.raises(ImageRecognitionError, match='未找到'):
        recognizer.recognize_file(path)
    with pytest.raises(ImageRecognitionError, match='读取'):
        recognizer.recognize_file(tmp_path / 'missing.png')
    with pytest.raises(ValueError, match='side'):
        recognizer.recognize_teams(path, 'left-ish')
    with pytest.raises(ImageRecognitionError, match='模板库为空'):
        PcrImageRecognizer().recognize_file(path)
    path, _ = layout(tmp_path, templates)
    with Image.open(path) as source:
        source.crop((0, 0, source.width - 110, source.height)).save(tmp_path / 'partial.png')
    with pytest.raises(ImageRecognitionError):
        recognizer.recognize_file(tmp_path / 'partial.png')


def test_no_network_on_recognition_or_get_icon(tmp_path, templates, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('recognition must never perform network I/O')
    monkeypatch.setattr(recognition, 'urlopen', forbidden)
    recognizer = PcrImageRecognizer(cache_dir=tmp_path, templates=templates)
    path, _ = layout(tmp_path, templates)
    recognizer.recognize_file(path)
    assert recognizer.get_icon(9999) is None
    icon = recognizer.get_icon(1001)
    icon.paste('black', (0, 0, icon.width, icon.height))
    assert recognizer.get_icon(1001).getpixel((20, 20)) != (0, 0, 0)
    with pytest.raises(ImageRecognitionError, match='模板库为空'):
        PcrImageRecognizer(cache_dir=tmp_path).recognize_file(path)


def test_local_cache_variants_legacy_and_corrupt(tmp_path, templates):
    templates[1001].save(tmp_path / '100161.webp', lossless=True)
    templates[1002].save(tmp_path / '100231.webp', lossless=True)
    templates[1003].save(tmp_path / '1003.webp', lossless=True)
    (tmp_path / '100411.webp').write_bytes(b'not an image')
    r = PcrImageRecognizer(cache_dir=tmp_path)
    assert set(r.templates) == {1001, 1002, 1003}
    assert r.load_templates() == 0
    templates[1004].save(tmp_path / '100411.webp', lossless=True)
    assert r.load_templates([1004]) == 1
    assert r.get_icon(1004) is not None


def test_warmup_bounded_cached_and_offline(tmp_path, templates, monkeypatch):
    calls, active, peak = [], 0, 0
    lock = Lock()

    def fake_fetch(chara_id, variant, timeout, max_bytes, deadline):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            calls.append((chara_id, variant))
        time.sleep(.01)
        with lock:
            active -= 1
        return templates[chara_id].copy() if chara_id != 1003 else None

    monkeypatch.setattr(recognition, '_fetch_icon', fake_fetch)
    r = PcrImageRecognizer(cache_dir=tmp_path)
    report = asyncio.run(r.warmup(range(1001, 1020), concurrency=2, max_characters=3))
    assert len(calls) == 9
    assert peak == 2
    assert report == dict(loaded=6, downloaded=6, failed=3, pending=0, timed_out=False)
    assert r.warm_templates(max_workers=2, chara_ids=range(1001, 1004), retry_failed=False) == dict(loaded=2, failed=1, total=3)
    assert len(calls) == 9
    assert len(list(tmp_path.glob('*.webp'))) == 6
    assert not list(tmp_path.glob('*.tmp'))
    reloaded = PcrImageRecognizer(cache_dir=tmp_path)
    assert len(reloaded._bank) == 6
    asyncio.run(r.warmup([1003], variants=(11,), retry_failed=True))
    assert len(calls) == 10


def test_warmup_timeout_does_not_install_late_results(tmp_path, templates, monkeypatch):
    def slow(*args):
        time.sleep(.04)
        return templates[1001]
    monkeypatch.setattr(recognition, '_fetch_icon', slow)

    async def run():
        r = PcrImageRecognizer(cache_dir=tmp_path)
        report = await r.warmup([1001, 1002], total_timeout=.005, concurrency=1)
        assert report['timed_out'] and report['pending'] == 6
        await asyncio.sleep(.06)
        assert r.get_icon(1001) is None
        assert not list(tmp_path.glob('*.webp'))
    asyncio.run(run())


def test_load_cached_discovers_new_character_ids_without_network(tmp_path, templates, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('local cache loading must never fetch')
    monkeypatch.setattr(recognition, 'urlopen', forbidden)
    r = PcrImageRecognizer(cache_dir=tmp_path)
    templates[1001].save(tmp_path / '129931.webp', lossless=True)
    templates[1002].save(tmp_path / '129961.webp', lossless=True)
    assert r.load_cached_templates() == 2
    assert r.get_icon(1299) is not None
    assert r.load_cached_templates() == 0
    assert PcrImageRecognizer(cache_dir=tmp_path).get_icon(1299) is not None


def test_sync_warm_templates_works_in_to_thread(templates, monkeypatch):
    monkeypatch.setattr(recognition, '_fetch_icon', lambda *a: templates[1001].copy())

    async def run():
        r = PcrImageRecognizer()
        result = await asyncio.to_thread(r.warm_templates, max_workers=2, chara_ids=[1299])
        assert result == dict(loaded=1, failed=0, total=1)
        assert r.get_icon(1299) is not None
        with pytest.raises(RuntimeError, match='synchronous'):
            r.warm_templates()
    asyncio.run(run())


@pytest.mark.parametrize('kwargs', [dict(concurrency=0), dict(max_characters=0),
                                   dict(max_bytes=2_000_000), dict(timeout=0),
                                   dict(total_timeout=float('nan')), dict(variants=(99,))])
def test_warmup_limits(kwargs):
    with pytest.raises(ValueError):
        asyncio.run(PcrImageRecognizer().warmup([1001], **kwargs))


def test_download_rejects_oversized_invalid_and_timeout(monkeypatch, templates):
    class Response(io.BytesIO):
        headers = {}
    payload = io.BytesIO()
    templates[1001].save(payload, format='PNG')
    responses = [payload.getvalue(), b'x' * 65537, b'invalid']
    for data, expected in zip(responses, [True, False, False]):
        monkeypatch.setattr(recognition, 'urlopen', lambda *a, **k: Response(data))
        image = recognition._fetch_icon(1001, 61, 1, 65536, time.monotonic() + 1)
        assert (image is not None) == expected
    monkeypatch.setattr(recognition, 'urlopen', lambda *a, **k: (_ for _ in ()).throw(TimeoutError()))
    assert recognition._fetch_icon(1001, 61, 1, 2048, time.monotonic() + 1) is None


@pytest.mark.parametrize('rows', [1, 3])
def test_tightly_packed_borderless_exports(tmp_path, templates, rows):
    image = Image.new('RGB', (320, 64 * rows))
    ids = list(templates)[:5 * rows]
    for i, chara_id in enumerate(ids):
        image.paste(templates[chara_id].resize((64, 64)), ((i % 5) * 64, (i // 5) * 64))
    path = tmp_path / 'packed.png'
    image.save(path)
    result = PcrImageRecognizer(templates=templates).recognize_teams(path)
    assert [t['ids'] for t in result] == [ids[i * 5:(i + 1) * 5] for i in range(rows)]


def test_level_stars_compression_and_brightness(tmp_path, templates):
    path, expected = layout(tmp_path, templates, rows=3, paired=True, size=48)
    with Image.open(path) as original:
        image = original.copy()
    draw = ImageDraw.Draw(image)
    for _, boxes in expected:
        for x1, y1, x2, y2 in boxes:
            draw.rectangle((x1, y1, x2 - 1, y1 + 5), fill='white')
            draw.text((x1, y1), 'Lv368', fill='black')
            draw.rectangle((x1, y2 - 6, x2 - 1, y2 - 1), fill=(220, 185, 20))
            draw.rectangle((x2 - 8, y2 - 12, x2 - 1, y2 - 1), fill=(80, 190, 230))
    image = Image.fromarray((np.asarray(image).astype(float) * .8 + 8).astype('uint8'))
    path = tmp_path / 'compressed.jpg'
    image.save(path, quality=80)
    result = PcrImageRecognizer(templates=templates).recognize_teams(path, 'all')
    assert [t['ids'] for t in result] == [e[0] for e in expected]


def test_only_selected_side_is_matched(tmp_path, templates):
    path, expected = layout(tmp_path, templates, paired=True, unknown=True)
    r = PcrImageRecognizer(templates=templates)
    assert r.recognize_teams(path)[0]['ids'] == expected[1][0]
    with pytest.raises(ImageRecognitionError):
        r.recognize_teams(path, 'all')


def test_duplicates_across_teams_on_same_side_fail(tmp_path, templates):
    path, expected = layout(tmp_path, templates, rows=3)
    with Image.open(path) as original:
        image = original.copy()
    x1, y1, x2, y2 = expected[1][1][0]
    image.paste(templates[1001].resize((x2 - x1, y2 - y1)), (x1, y1))
    image.save(path)
    with pytest.raises(ImageRecognitionError, match='重复角色'):
        PcrImageRecognizer(templates=templates).recognize_teams(path)


def test_incomplete_row_never_silently_becomes_one_team(tmp_path, templates):
    path, expected = layout(tmp_path, templates, rows=3)
    with Image.open(path) as original:
        image = original.copy()
    draw = ImageDraw.Draw(image)
    for x1, y1, x2, y2 in expected[1][1][3:]:
        draw.rectangle((x1 - 3, y1 - 3, x2 + 3, y2 + 3), fill=(240, 243, 247))
    image.save(path)
    with pytest.raises(ImageRecognitionError):
        PcrImageRecognizer(templates=templates).recognize_teams(path)


def test_broken_contour_frames_recover_from_other_rows(tmp_path, templates, monkeypatch):
    path, expected = layout(tmp_path, templates, rows=3, paired=True)
    original = recognition._icon_boxes

    def missing_one(rgb):
        boxes = original(rgb)
        target = expected[2][1][3]
        return [b for b in boxes if recognition._overlap(b, target) < .8]

    monkeypatch.setattr(recognition, '_icon_boxes', missing_one)
    result = PcrImageRecognizer(templates=templates).recognize_teams(path, 'all')
    assert [t['ids'] for t in result] == [e[0] for e in expected]


def test_production_flat_cache_never_reports_perfect_correlation(tmp_path):
    Image.new('RGB', (128, 128), (120, 120, 120)).save(tmp_path / '100131.webp')
    r = PcrImageRecognizer(cache_dir=tmp_path)
    assert r.get_icon(1001) is None
    assert not r._bank


def test_download_limits_headers_dimensions_and_deadline(monkeypatch):
    class Response(io.BytesIO):
        headers = {'Content-Length': '99999999'}

        def read1(self, size):
            pytest.fail('oversized content must not be read')

    monkeypatch.setattr(recognition, 'urlopen', lambda *a, **k: Response(b'oversize'))
    assert recognition._fetch_icon(1001, 61, 1, 2048, time.monotonic() + 1) is None
    Response.headers = {}
    payload = io.BytesIO()
    Image.new('RGB', (600, 600)).save(payload, 'PNG')
    Response.read1 = io.BytesIO.read1
    monkeypatch.setattr(recognition, 'urlopen', lambda *a, **k: Response(payload.getvalue()))
    assert recognition._fetch_icon(1001, 61, 1, 65536, time.monotonic() + 1) is None

    def expired(*args, **kwargs):
        pytest.fail('expired requests must not be opened')
    monkeypatch.setattr(recognition, 'urlopen', expired)
    assert recognition._fetch_icon(1001, 61, 1, 2048, time.monotonic() - 1) is None


def test_blur_is_explicit_not_an_arbitrary_identity(templates):
    r = PcrImageRecognizer(templates=templates)
    with pytest.raises(ImageRecognitionError, match='模糊'):
        r._match_segment(templates[1001].filter(ImageFilter.GaussianBlur(5)))


def test_warmup_overlap_and_cancellation_are_safe(tmp_path, templates, monkeypatch):
    def slow(*args):
        time.sleep(.04)
        return templates[1001]
    monkeypatch.setattr(recognition, '_fetch_icon', slow)

    async def run():
        r = PcrImageRecognizer(cache_dir=tmp_path)
        task = asyncio.create_task(r.warmup([1001], concurrency=1))
        while not r._warming:
            await asyncio.sleep(0)
        with pytest.raises(ImageRecognitionError, match='正在预热'):
            await r.warmup([1001])
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(.06)
        assert not r._warming and r.get_icon(1001) is None
        assert not list(tmp_path.glob('*.webp'))
    asyncio.run(run())
