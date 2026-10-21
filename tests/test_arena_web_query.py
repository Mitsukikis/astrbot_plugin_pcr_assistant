"""Offline contract tests: capture is mocked and all image bytes are synthetic."""

import asyncio
import io
import sys
from collections import Counter
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from PIL import Image

import arena_web_query as web


DEFENDERS = [1001, 1002, 1003, 1004, 1005]
RESULT_URL = 'https://www.pcrdfans.com/battle'
REAL_CAPTURE = web.ArenaWebQueryClient._capture


def card_bytes(size=(320, 80), color=(34, 139, 93), mode='RGB'):
    with Image.new(mode, size, color) as image:
        output = io.BytesIO()
        image.save(output, format='PNG')
        return output.getvalue()


def empty_result():
    return web.ArenaWebResult(path=None, url=RESULT_URL, count=0, empty=True)


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    clock = SimpleNamespace(now=1000.0, delays=[])

    async def sleep(delay):
        clock.delays.append(delay)
        clock.now += delay

    monkeypatch.setattr(web, 'time', SimpleNamespace(monotonic=lambda: clock.now))
    monkeypatch.setattr(web, 'asyncio', SimpleNamespace(**vars(asyncio)))
    monkeypatch.setattr(web.asyncio, 'sleep', sleep)
    return clock


@pytest.fixture(autouse=True)
def capture(monkeypatch):
    mock = AsyncMock(side_effect=AssertionError('real browser capture is forbidden in offline tests'))
    monkeypatch.setattr(web.ArenaWebQueryClient, '_capture', mock)
    return mock


def test_default_client_is_disabled_without_capture_or_output(tmp_path, capture):
    async def run():
        client = web.ArenaWebQueryClient()
        output = tmp_path / 'disabled.png'
        try:
            with pytest.raises(web.ArenaWebQueryError):
                await client.query(DEFENDERS, output)
            capture.assert_not_awaited()
            assert not output.exists()
            assert not client._lock.locked()
        finally:
            await client.close()

    asyncio.run(run())


@pytest.mark.parametrize('defenders', [
    None,
    [],
    [1001, 1002, 1003, 1004],
    [1001, 1002, 1003, 1004, 1005, 1006],
    [1001, 1002, 1003, 1004, 1004],
    [1000, 1002, 1003, 1004, 1005],
    [2000, 1002, 1003, 1004, 1005],
    [-1001, 1002, 1003, 1004, 1005],
    [True, 1002, 1003, 1004, 1005],
    [1001.0, 1002, 1003, 1004, 1005],
    ['1001', 1002, 1003, 1004, 1005],
    [None, 1002, 1003, 1004, 1005],
    [[1001], 1002, 1003, 1004, 1005],
    '1001,1002,1003,1004,1005',
])
def test_invalid_defenders_fail_before_capture(tmp_path, capture, defenders):
    async def run():
        client = web.ArenaWebQueryClient(enabled=True)
        try:
            with pytest.raises(web.ArenaWebQueryError):
                await client.query(defenders, tmp_path / 'invalid.png')
            capture.assert_not_awaited()
            assert not list(tmp_path.iterdir())
            assert not client._lock.locked()
        finally:
            await client.close()

    asyncio.run(run())


@pytest.mark.parametrize('region', [0, 5, -1, None, True, 1.0, '1'])
def test_invalid_regions_fail_before_capture(tmp_path, capture, region):
    async def run():
        client = web.ArenaWebQueryClient(enabled=True)
        try:
            with pytest.raises(web.ArenaWebQueryError):
                await client.query(DEFENDERS, tmp_path / 'invalid.png', region=region)
            capture.assert_not_awaited()
            assert not list(tmp_path.iterdir())
            assert not client._lock.locked()
        finally:
            await client.close()

    asyncio.run(run())


@pytest.mark.parametrize('region', [1, 2, 3, 4])
def test_valid_boundary_ids_and_regions_reach_capture(tmp_path, capture, region):
    async def run():
        client = web.ArenaWebQueryClient(enabled=True, min_interval_seconds=0)
        output = tmp_path / 'result.png'
        defenders = [1001, 1002, 1500, 1998, 1999]
        result = web.ArenaWebResult(path=output, url=RESULT_URL, count=2)
        capture.side_effect = None
        capture.return_value = result
        try:
            actual = await client.query(defenders, output, region=region)
            assert actual == result
            assert actual.path == output
            assert not actual.empty
            capture.assert_awaited_once_with(defenders, output, region)
            assert defenders == [1001, 1002, 1500, 1998, 1999]
            assert not client._lock.locked()
        finally:
            await client.close()

    asyncio.run(run())


def test_empty_results_create_no_image_and_are_not_cached(tmp_path, capture):
    async def run():
        client = web.ArenaWebQueryClient(enabled=True, min_interval_seconds=0)
        capture.side_effect = None
        capture.return_value = empty_result()
        try:
            for _ in range(2):
                result = await client.query(DEFENDERS, tmp_path / 'empty.png')
                assert result.empty
                assert result.count == 0
                assert result.path is None
                assert not list(tmp_path.iterdir())
            assert capture.await_count == 2
            assert not client._lock.locked()
        finally:
            await client.close()

    asyncio.run(run())


def test_concurrent_query_fails_fast_without_second_capture(tmp_path, capture):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        client = web.ArenaWebQueryClient(enabled=True, min_interval_seconds=0)

        async def held_capture(*args):
            entered.set()
            await release.wait()
            return empty_result()

        capture.side_effect = held_capture
        first = asyncio.create_task(client.query(DEFENDERS, tmp_path / 'first.png'))
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            with pytest.raises(web.ArenaWebQueryError):
                await asyncio.wait_for(
                    client.query(DEFENDERS, tmp_path / 'second.png'), timeout=.5)
            assert capture.await_count == 1
            assert not first.done()
            release.set()
            assert (await asyncio.wait_for(first, timeout=2)).empty
            assert not client._lock.locked()
        finally:
            release.set()
            first.cancel()
            await asyncio.gather(first, return_exceptions=True)
            await client.close()

    asyncio.run(run())


def test_capture_cancellation_releases_lock_and_allows_next_query(tmp_path, capture):
    async def run():
        entered, stopped = asyncio.Event(), asyncio.Event()
        client = web.ArenaWebQueryClient(enabled=True, min_interval_seconds=0)

        async def held_capture(*args):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        capture.side_effect = held_capture
        task = asyncio.create_task(client.query(DEFENDERS, tmp_path / 'cancelled.png'))
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=2)
            assert stopped.is_set()
            assert not client._lock.locked()
            assert not list(tmp_path.iterdir())
            capture.side_effect = None
            capture.return_value = empty_result()
            assert (await client.query(DEFENDERS, tmp_path / 'next.png')).empty
            assert capture.await_count == 2
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await client.close()

    asyncio.run(run())


def test_close_cancels_active_capture_and_is_idempotent(tmp_path, capture):
    async def run():
        entered, stopped = asyncio.Event(), asyncio.Event()
        client = web.ArenaWebQueryClient(enabled=True, min_interval_seconds=0)

        async def held_capture(*args):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        capture.side_effect = held_capture
        task = asyncio.create_task(client.query(DEFENDERS, tmp_path / 'closed.png'))
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            await asyncio.wait_for(client.close(), timeout=2)
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=2)
            assert stopped.is_set()
            assert not client._lock.locked()
            assert not list(tmp_path.iterdir())
            await asyncio.wait_for(client.close(), timeout=2)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await client.close()

    asyncio.run(run())


def test_capture_failure_releases_lock_and_does_not_cache(tmp_path, capture):
    async def run():
        client = web.ArenaWebQueryClient(enabled=True, min_interval_seconds=0)
        capture.side_effect = web.ArenaWebQueryError('synthetic capture failure')
        try:
            with pytest.raises(web.ArenaWebQueryError):
                await client.query(DEFENDERS, tmp_path / 'failed.png')
            assert not client._lock.locked()
            assert not list(tmp_path.iterdir())
            capture.side_effect = None
            capture.return_value = empty_result()
            assert (await client.query(DEFENDERS, tmp_path / 'retry.png')).empty
            assert capture.await_count == 2
        finally:
            await client.close()

    asyncio.run(run())


def test_timeout_cancels_capture_before_unlocking_and_allows_retry(tmp_path, capture):
    async def run():
        client = web.ArenaWebQueryClient(enabled=True)
        client.timeout_seconds = .02
        entered, stopped = asyncio.Event(), asyncio.Event()

        async def held_capture(*args):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        capture.side_effect = held_capture
        try:
            with pytest.raises(web.ArenaWebQueryError) as error:
                await asyncio.wait_for(
                    client.query(DEFENDERS, tmp_path / 'timeout.png'), timeout=2)
            assert isinstance(error.value.__cause__, asyncio.TimeoutError)
            assert entered.is_set() and stopped.is_set()
            assert not client._lock.locked()
            assert client._task is None
            assert not list(tmp_path.iterdir())
            capture.side_effect = None
            capture.return_value = empty_result()
            assert (await client.query(DEFENDERS, tmp_path / 'retry.png')).empty
            assert capture.await_count == 2
        finally:
            await client.close()

    asyncio.run(run())


def test_successful_results_are_fresh_instead_of_cached(tmp_path, capture):
    async def run():
        client = web.ArenaWebQueryClient(enabled=True)
        first = web.ArenaWebResult(tmp_path / 'first.png', RESULT_URL, 1)
        second = web.ArenaWebResult(tmp_path / 'second.png', RESULT_URL, 3)
        capture.side_effect = [first, second]
        try:
            assert await client.query(DEFENDERS, first.path) == first
            assert await client.query(DEFENDERS, second.path) == second
            assert capture.await_count == 2
        finally:
            await client.close()

    asyncio.run(run())


def test_minimum_interval_waits_before_capture_without_result_caching(tmp_path, capture, clock):
    async def run():
        client = web.ArenaWebQueryClient(enabled=True, min_interval_seconds=0)
        starts = []

        async def record_capture(*args):
            starts.append(clock.now)
            return empty_result()

        capture.side_effect = record_capture
        try:
            await client.query(DEFENDERS, tmp_path / 'first.png')
            assert starts == [1000.0]
            assert clock.delays == []
            clock.now += 7
            await client.query(DEFENDERS, tmp_path / 'second.png')
            assert clock.delays == [23.0]
            assert starts == [1000.0, 1030.0]
            assert capture.await_count == 2
            assert client._last_started == 1030.0
            clock.now += 40
            await client.query(DEFENDERS, tmp_path / 'third.png')
            assert clock.delays == [23.0]
            assert starts == [1000.0, 1030.0, 1070.0]
        finally:
            await client.close()

    asyncio.run(run())


@pytest.mark.parametrize('cancel_by_close', [False, True])
def test_cancelling_interval_wait_never_starts_capture(
        tmp_path, capture, clock, monkeypatch, cancel_by_close):
    async def run():
        client = web.ArenaWebQueryClient(enabled=True)
        capture.side_effect = None
        capture.return_value = empty_result()
        await client.query(DEFENDERS, tmp_path / 'first.png')
        waiting, stopped = asyncio.Event(), asyncio.Event()
        delays = []
        original_sleep = web.asyncio.sleep

        async def held_sleep(delay):
            delays.append(delay)
            waiting.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        monkeypatch.setattr(web.asyncio, 'sleep', held_sleep)
        task = asyncio.create_task(client.query(DEFENDERS, tmp_path / 'waiting.png'))
        try:
            await asyncio.wait_for(waiting.wait(), timeout=2)
            assert capture.await_count == 1
            assert client._last_started == 1000.0
            with pytest.raises(web.ArenaWebQueryError):
                await asyncio.wait_for(
                    client.query(DEFENDERS, tmp_path / 'busy.png'), timeout=.5)
            if cancel_by_close:
                await asyncio.wait_for(client.close(), timeout=2)
            else:
                task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=2)
            assert stopped.is_set()
            assert delays == [30.0]
            assert capture.await_count == 1
            assert not client._lock.locked()
            assert client._task is None
            assert client._last_started == 1000.0
            assert not list(tmp_path.iterdir())
            if not cancel_by_close:
                monkeypatch.setattr(web.asyncio, 'sleep', original_sleep)
                assert (await client.query(DEFENDERS, tmp_path / 'retry.png')).empty
                assert clock.delays == [30.0]
                assert capture.await_count == 2
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await client.close()

    asyncio.run(run())


def test_blocked_capture_stops_retries_until_cooldown_expires(tmp_path, capture, clock):
    async def run():
        client = web.ArenaWebQueryClient(enabled=True)
        capture.side_effect = web.ArenaWebQueryBlocked('synthetic verification page')
        try:
            with pytest.raises(web.ArenaWebQueryBlocked):
                await client.query(DEFENDERS, tmp_path / 'blocked.png')
            assert client._blocked_until == 1600.0
            assert not client._lock.locked()
            capture.side_effect = None
            capture.return_value = empty_result()
            clock.now = 1599.0
            with pytest.raises(web.ArenaWebQueryBlocked):
                await client.query(DEFENDERS, tmp_path / 'too-soon.png')
            assert capture.await_count == 1
            assert clock.delays == []
            assert not list(tmp_path.iterdir())
            clock.now = 1601.0
            assert (await client.query(DEFENDERS, tmp_path / 'retry.png')).empty
            assert capture.await_count == 2
        finally:
            await client.close()

    asyncio.run(run())


def test_closed_client_cannot_start_a_new_capture(tmp_path, capture):
    async def run():
        client = web.ArenaWebQueryClient(enabled=True)
        await client.close()
        with pytest.raises(web.ArenaWebQueryError):
            await client.query(DEFENDERS, tmp_path / 'closed.png')
        capture.assert_not_awaited()
        assert not client._lock.locked()

    asyncio.run(run())


def test_real_capture_empty_page_never_screenshots_or_composes(tmp_path, monkeypatch):
    async def run():
        screenshot = AsyncMock(side_effect=AssertionError('empty result must not screenshot'))
        results = Mock()
        results.count = AsyncMock(return_value=0)
        results.nth.return_value = SimpleNamespace(screenshot=screenshot)
        body = SimpleNamespace(inner_text=AsyncMock(return_value='synthetic empty results'))
        empty = Mock()
        empty.filter.return_value = empty
        empty.count = AsyncMock(return_value=1)
        absent = SimpleNamespace(count=AsyncMock(return_value=0))

        def locator(selector):
            return {'body': body, web.RESULT_SELECTOR: results,
                    '.battle_search_result_ctn': empty,
                    '.ant-modal-content': absent,
                    '.battle_search_button.ant-btn-loading, .battle_search_button[aria-busy="true"]': absent}[selector]

        page = SimpleNamespace(
            url=RESULT_URL, locator=Mock(side_effect=locator), set_default_timeout=Mock(),
            goto=AsyncMock(return_value=SimpleNamespace(status=200)))
        context = SimpleNamespace(new_page=AsyncMock(return_value=page))
        browser = SimpleNamespace(new_context=AsyncMock(return_value=context), close=AsyncMock())
        chromium = SimpleNamespace(launch=AsyncMock(return_value=browser))
        manager = MagicMock()
        manager.__aenter__ = AsyncMock(return_value=SimpleNamespace(chromium=chromium))
        manager.__aexit__ = AsyncMock(return_value=False)
        api = ModuleType('playwright.async_api')
        api.async_playwright = Mock(return_value=manager)
        api.Error = type('SyntheticBrowserError', (Exception,), {})
        package = ModuleType('playwright')
        package.__path__ = []
        monkeypatch.setitem(sys.modules, 'playwright', package)
        monkeypatch.setitem(sys.modules, 'playwright.async_api', api)
        monkeypatch.setattr(web.ArenaWebQueryClient, '_capture', REAL_CAPTURE)
        compose = Mock(side_effect=AssertionError('empty result must not compose an image'))
        monkeypatch.setattr(web, 'compose_web_result', compose)
        client = web.ArenaWebQueryClient(enabled=True)
        monkeypatch.setattr(client, '_check_region_and_defenders', AsyncMock())
        try:
            result = await client.query(DEFENDERS, tmp_path / 'empty.png')
            assert result.empty and result.count == 0 and result.path is None
            assert result.url == web.pcrdfans_battle_url(DEFENDERS)
            screenshot.assert_not_awaited()
            results.nth.assert_not_called()
            compose.assert_not_called()
            assert not list(tmp_path.iterdir())
            chromium.launch.assert_awaited_once_with(headless=True)
            browser.new_context.assert_awaited_once_with(
                viewport={'width': 1280, 'height': 1000}, locale='zh-CN')
            browser.close.assert_awaited_once_with()
            manager.__aexit__.assert_awaited_once()
        finally:
            await client.close()

    asyncio.run(run())


@pytest.mark.parametrize('url', [
    'https://www.pcrdfans.com/battle',
    'https://pcrdfans.com/battle',
    'https://www.pcrdfans.com:443/battle',
])
def test_only_expected_https_hosts_are_accepted(url):
    web._check_location(url)


@pytest.mark.parametrize('url', [
    'http://www.pcrdfans.com/battle',
    'https://example.com/battle',
    'https://pcrdfans.com.example.com/battle',
    'https://other.pcrdfans.com/battle',
    'https://www.pcrdfans.com@evil.example/battle',
    'https://user:password@www.pcrdfans.com/battle',
    'https://www.pcrdfans.com:8443/battle',
    'file:///tmp/battle',
    '//www.pcrdfans.com/battle',
    'https://www.pcrdfans.com/login',
    'https://www.pcrdfans.com/signin',
    'https://www.pcrdfans.com/captcha',
    'https://www.pcrdfans.com/challenge',
])
def test_untrusted_or_verification_locations_fail_closed(url):
    with pytest.raises(web.ArenaWebQueryBlocked):
        web._check_location(url)


@pytest.mark.parametrize('status', [401, 403, 429])
def test_navigation_stops_on_access_rejection_without_retry(status):
    async def run():
        page = SimpleNamespace(url=RESULT_URL,
                               goto=AsyncMock(return_value=SimpleNamespace(status=status)))
        client = web.ArenaWebQueryClient(enabled=True)
        try:
            with pytest.raises(web.ArenaWebQueryBlocked):
                await client._navigate(page, RESULT_URL)
            page.goto.assert_awaited_once_with(
                RESULT_URL, wait_until='domcontentloaded', timeout=25000)
        finally:
            await client.close()

    asyncio.run(run())


@pytest.mark.parametrize('text', [
    'VERIFY YOU ARE HUMAN', 'Verification Required', 'Access Denied', 'Too Many Requests',
])
def test_result_wait_stops_on_visible_verification_or_rate_limit(text, clock):
    async def run():
        body = SimpleNamespace(inner_text=AsyncMock(return_value=text))
        page = SimpleNamespace(url=RESULT_URL, locator=Mock(return_value=body))
        client = web.ArenaWebQueryClient(enabled=True)
        try:
            with pytest.raises(web.ArenaWebQueryBlocked):
                await asyncio.wait_for(client._wait_for_result(page), timeout=2)
            page.locator.assert_called_once_with('body')
            assert clock.delays == []
        finally:
            await client.close()

    asyncio.run(run())


def test_composition_preserves_all_synthetic_cards_and_their_order(tmp_path):
    colors = [(219, 36, 53), (22, 164, 112), (39, 104, 223)]
    cards = [card_bytes((320, 80), color) for color in colors]
    output = tmp_path / 'composed.png'
    result = web.compose_web_result(cards, output, DEFENDERS, region=1)
    assert isinstance(result, Path)
    assert result == output
    with Image.open(result) as image:
        assert image.format == 'PNG'
        image.load()
        rgb = image.convert('RGB')
        counts = Counter(rgb.getdata())
        for color in colors:
            assert counts[color] >= 100
        first_rows = [next(y for y in range(rgb.height)
                           if color in {rgb.getpixel((x, y)) for x in range(rgb.width)})
                      for color in colors]
        assert first_rows == sorted(first_rows)
        assert len(set(first_rows)) == len(colors)


def test_composition_accepts_different_card_sizes_and_rgba(tmp_path):
    cards = [card_bytes((280, 80), (219, 36, 53)),
             card_bytes((320, 100), (22, 164, 112, 255), mode='RGBA')]
    output = web.compose_web_result(cards, tmp_path / 'mixed.png', DEFENDERS, region=4)
    with Image.open(output) as image:
        image.load()
        assert image.width >= 280
        assert image.height >= 180


@pytest.mark.parametrize('cards', [[], [b''], [b'not a PNG'], [b'\x89PNG\r\n\x1a\n']])
def test_composition_rejects_empty_or_corrupt_cards_without_output(tmp_path, cards):
    output = tmp_path / 'invalid.png'
    with pytest.raises(web.ArenaWebQueryError):
        web.compose_web_result(cards, output, DEFENDERS)
    assert not output.exists()


@pytest.mark.parametrize('size', [(32768, 8), (8, 32768)])
def test_composition_rejects_oversized_card_dimensions(tmp_path, size):
    output = tmp_path / 'oversized.png'
    with pytest.raises(web.ArenaWebQueryError):
        web.compose_web_result([card_bytes(size)], output, DEFENDERS)
    assert not output.exists()


def test_composition_rejects_oversized_encoded_card(tmp_path):
    output = tmp_path / 'oversized.png'
    payload = card_bytes() + b'\0' * (20 * 1024 * 1024)
    with pytest.raises(web.ArenaWebQueryError):
        web.compose_web_result([payload], output, DEFENDERS)
    assert not output.exists()


@pytest.mark.parametrize('payload', [None, 'not bytes', bytearray(b'not bytes')])
def test_composition_rejects_non_bytes_payloads(tmp_path, payload):
    output = tmp_path / 'invalid.png'
    with pytest.raises(web.ArenaWebQueryError):
        web.compose_web_result([payload], output, DEFENDERS)
    assert not output.exists()


def test_composition_rejects_more_than_five_cards(tmp_path):
    output = tmp_path / 'too-many.png'
    with pytest.raises(web.ArenaWebQueryError):
        web.compose_web_result([card_bytes()] * 6, output, DEFENDERS)
    assert not output.exists()


@pytest.mark.parametrize('size', [(249, 80), (320, 69), (1601, 80), (320, 1601)])
def test_composition_rejects_cards_outside_documented_source_bounds(tmp_path, size):
    output = tmp_path / 'invalid-bounds.png'
    with pytest.raises(web.ArenaWebQueryError):
        web.compose_web_result([card_bytes(size)], output, DEFENDERS)
    assert not output.exists()


def test_invalid_later_card_does_not_overwrite_existing_output(tmp_path):
    output = tmp_path / 'existing.png'
    previous = card_bytes()
    output.write_bytes(previous)
    with pytest.raises(web.ArenaWebQueryError):
        web.compose_web_result([card_bytes(), b'corrupt second card'], output, DEFENDERS)
    assert output.read_bytes() == previous


def test_modal_is_checked_before_stale_result_nodes():
    async def run():
        results = SimpleNamespace(count=AsyncMock(return_value=10))
        modal = SimpleNamespace(count=AsyncMock(return_value=1))
        body = SimpleNamespace(inner_text=AsyncMock(return_value='synthetic query error'))
        page = SimpleNamespace(url=RESULT_URL, locator=Mock(side_effect=lambda selector:
            {'body':body,'.ant-modal-content':modal,web.RESULT_SELECTOR:results}[selector]))
        client = web.ArenaWebQueryClient(enabled=True)
        with pytest.raises(web.ArenaWebQueryError):
            await client._wait_for_result(page)
        results.count.assert_not_awaited()
    asyncio.run(run())


def test_loading_old_results_are_not_returned_before_query_finishes(clock):
    async def run():
        loading = SimpleNamespace(count=AsyncMock(side_effect=[1,0]))
        absent = SimpleNamespace(count=AsyncMock(return_value=0))
        results = SimpleNamespace(count=AsyncMock(return_value=10))
        body = SimpleNamespace(inner_text=AsyncMock(return_value='synthetic results'))
        page = SimpleNamespace(url=RESULT_URL, locator=Mock(side_effect=lambda selector:
            {'body':body,'.ant-modal-content':absent,web.RESULT_SELECTOR:results,
             '.battle_search_button.ant-btn-loading, .battle_search_button[aria-busy="true"]':loading}[selector]))
        client = web.ArenaWebQueryClient(enabled=True)
        await client._wait_for_result(page)
        assert clock.delays == [.4]
        results.count.assert_awaited_once()
    asyncio.run(run())


@pytest.mark.parametrize('actual',[[1001,1002,1003,1004,1005],[1001,1002,1003,1004,1006]])
def test_actual_website_avatar_identity_must_match_requested_team(actual):
    async def run():
        selection = SimpleNamespace(
            locator=Mock(return_value=SimpleNamespace(count=AsyncMock(return_value=5))),
            screenshot=AsyncMock(return_value=card_bytes()))
        wrapper = SimpleNamespace(filter=Mock(return_value=SimpleNamespace(first=selection)))
        radio = SimpleNamespace(filter=Mock(return_value=SimpleNamespace(
            locator=Mock(return_value=SimpleNamespace(is_checked=AsyncMock(return_value=True))))))
        page = SimpleNamespace(locator=Mock(side_effect=lambda selector:
            radio if selector == 'label' else wrapper))
        recognizer = SimpleNamespace(recognize_file=Mock(return_value=actual))
        client = web.ArenaWebQueryClient(enabled=True,recognizer=recognizer)
        client._wait_for_artwork = AsyncMock()
        if actual == DEFENDERS:
            await client._check_region_and_defenders(page,1,DEFENDERS)
        else:
            with pytest.raises(web.ArenaWebQueryError,match='请求阵容不同'):
                await client._check_region_and_defenders(page,1,DEFENDERS)
        recognizer.recognize_file.assert_called_once()
    asyncio.run(run())


def test_composition_worker_returns_bytes_without_writing_files(tmp_path):
    payload = web._compose_web_result_bytes([card_bytes()], DEFENDERS)
    assert isinstance(payload,bytes) and payload.startswith(b'\x89PNG')
    assert not list(tmp_path.iterdir())
