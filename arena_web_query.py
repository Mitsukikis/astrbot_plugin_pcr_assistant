"""Low-frequency anonymous browser queries of the public arena website.

Only normal page navigation and visible controls are used. No private search
API, signatures, saved login sessions, captcha solving or proxy rotation.
"""

import asyncio
import io
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image, ImageDraw

try:
    from .arena_solution import pcrdfans_battle_url
    from .pcr_cards import _font, _wrap
    from .pcr_chara import name_for_id
except ImportError:
    from arena_solution import pcrdfans_battle_url
    from pcr_cards import _font, _wrap
    from pcr_chara import name_for_id


HOSTS = frozenset({'www.pcrdfans.com', 'pcrdfans.com'})
REGIONS = {1: '全部角色', 2: '国服', 3: '台服', 4: '日服'}
RESULT_SELECTOR = '.battle_search_single_result_ctn'
BLOCK_MARKERS = (
    'verify you are human', 'verification required', 'checking your browser',
    'just a moment...', '确认您是真人', '验证您是人类', '人机验证',
    '请先登录', '请登录后', '需要登录后', 'too many requests',
    '请求过于频繁', '操作过于频繁', '访问受限', 'access denied',
)


class ArenaWebQueryError(RuntimeError):
    pass


class ArenaWebQueryBlocked(ArenaWebQueryError):
    pass


@dataclass
class ArenaWebResult:
    path: Path | None
    url: str
    count: int
    empty: bool = False


def _validate(defender_ids, region):
    if not isinstance(defender_ids, (list, tuple)) or len(defender_ids) != 5:
        raise ArenaWebQueryError('网页查询需要五名不重复角色。')
    if any(type(cid) is not int or not 1001 <= cid < 2000 for cid in defender_ids):
        raise ArenaWebQueryError('角色编号无效。')
    if len(set(defender_ids)) != 5 or type(region) is not int or region not in REGIONS:
        raise ArenaWebQueryError('角色重复或服务器选项无效。')


def _check_location(url):
    location = urlparse(url)
    if (location.scheme != 'https' or location.hostname not in HOSTS or
            location.username or location.password or location.port not in (None, 443)):
        raise ArenaWebQueryBlocked('网页跳转到了非预期地址，已停止查询。')
    if any(part in location.path.lower() for part in ('login', 'signin', 'captcha', 'challenge')):
        raise ArenaWebQueryBlocked('网站要求登录或验证，已停止自动查询。')


def compose_web_result(cards, output_path, defender_ids, region=1):
    payload = _compose_web_result_bytes(cards, defender_ids, region)
    return _save_result(payload, output_path)


def _save_result(payload, output_path):
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _compose_web_result_bytes(cards, defender_ids, region=1):
    _validate(defender_ids, region)
    if not cards or len(cards) > 5:
        raise ArenaWebQueryError('网页没有可展示的完整作业。')
    images = []
    for payload in cards:
        if not isinstance(payload, bytes) or len(payload) > 8_000_000:
            raise ArenaWebQueryError('网页作业图片大小异常。')
        try:
            with Image.open(io.BytesIO(payload)) as source:
                if not (250 <= source.width <= 1600 and 70 <= source.height <= 1600):
                    raise ValueError('invalid card bounds')
                image = source.convert('RGB')
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            raise ArenaWebQueryError('网页作业图片无法读取。') from exc
        if image.width > 944:
            image = image.resize((944, round(image.height * 944 / image.width)), Image.Resampling.LANCZOS)
        images.append(image)
    width = 1000
    measure = ImageDraw.Draw(Image.new('RGB', (width, 1), 'white'))
    names = '防守：' + ' / '.join(name_for_id(cid) for cid in defender_ids)
    lines = _wrap(measure, names, _font(22), width - 56)
    header = 118 + len(lines) * 30
    height = header + sum(im.height + 18 for im in images) + 70
    image = Image.new('RGB', (width, height), 'white')
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, 76), fill='#145e63')
    draw.text((28, 18), f'竞技场网页作业 · {REGIONS[region]}', font=_font(30), fill='white')
    for index, line in enumerate(lines):
        draw.text((28, 90 + index * 30), line, font=_font(22), fill='#26333d')
    y = header
    for card in images:
        image.paste(card, ((width - card.width) // 2, y))
        y += card.height + 18
    draw.text((28, height - 60), f'来源：pcrdfans.com · 网页前 {len(images)} 条 · 非战斗模拟', font=_font(19), fill='#64727a')
    draw.text((28, height - 32), f'查询时间：{datetime.now():%Y-%m-%d %H:%M:%S}（服务器时间）', font=_font(17), fill='#64727a')
    output = io.BytesIO()
    image.save(output, format='PNG')
    return output.getvalue()


class ArenaWebQueryClient:
    def __init__(self, enabled=False, timeout_seconds=60, min_interval_seconds=30, max_results=5, recognizer=None):
        self.enabled = enabled is True
        self.timeout_seconds = max(20, min(90, float(timeout_seconds)))
        self.min_interval_seconds = max(30, float(min_interval_seconds))
        self.max_results = max(1, min(5, int(max_results)))
        self.recognizer = recognizer
        self._lock = asyncio.Lock()
        self._last_started = None
        self._blocked_until = 0.0
        self._task = None
        self._closed = False

    async def query(self, defender_ids, output_path, region=1):
        _validate(defender_ids, region)
        if not self.enabled or self._closed:
            raise ArenaWebQueryError('网页查询未启用。')
        if time.monotonic() < self._blocked_until:
            raise ArenaWebQueryBlocked('网站刚刚要求验证或限制访问，已暂停网页查询，请使用链接手动查询。')
        if self._lock.locked():
            raise ArenaWebQueryError('已有网页查询正在进行，请稍后再试。')
        async with self._lock:
            self._task = asyncio.create_task(self._run(defender_ids, output_path, region))
            try:
                return await self._task
            except ArenaWebQueryBlocked:
                self._blocked_until = time.monotonic() + 600
                raise
            finally:
                self._task = None

    async def _run(self, defender_ids, output_path, region):
        if self._last_started is not None:
            delay = self._last_started + self.min_interval_seconds - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
        self._last_started = time.monotonic()
        try:
            return await asyncio.wait_for(self._capture(defender_ids, output_path, region), self.timeout_seconds)
        except asyncio.TimeoutError as exc:
            raise ArenaWebQueryError('作业网页查询超时，请通过链接手动查看。') from exc

    async def close(self):
        self._closed = True
        task = self._task
        if task and task is not asyncio.current_task() and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _capture(self, defender_ids, output_path, region):
        try:
            from playwright.async_api import async_playwright, Error as BrowserError
        except ImportError as exc:
            raise ArenaWebQueryError('服务器缺少 Playwright 浏览器组件，请使用查询链接。') from exc
        url = pcrdfans_battle_url(defender_ids)
        async with async_playwright() as p:
            browser = None
            try:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(viewport={'width': 1280, 'height': 1000}, locale='zh-CN')
                page = await context.new_page()
                page.set_default_timeout(10000)
                await self._navigate(page, url)
                await self._wait_for_result(page)
                if region != 1:
                    await page.get_by_text(REGIONS[region], exact=True).click()
                    await self._check_region_and_defenders(page, region, defender_ids)
                    await page.locator('button.battle_search_button').click()
                    await self._wait_for_result(page)
                await self._check_region_and_defenders(page, region, defender_ids)
                results = page.locator(RESULT_SELECTOR)
                count = min(await results.count(), self.max_results)
                if not count:
                    return ArenaWebResult(None, url, 0, empty=True)
                cards = []
                for index in range(count):
                    card = results.nth(index)
                    await self._wait_for_artwork(card)
                    cards.append(await card.screenshot(animations='disabled',
                        style=RESULT_SELECTOR + '{background:#fff !important;}'))
                try:
                    # The worker is pure. Only commit the file after awaiting it,
                    # so a cancelled query cannot leave a late image on disk.
                    payload = await asyncio.to_thread(_compose_web_result_bytes, cards, defender_ids, region)
                    path = _save_result(payload, output_path)
                except (OSError, ValueError, RuntimeError) as exc:
                    raise ArenaWebQueryError('网页作业图片生成失败，请打开查询链接。') from exc
                return ArenaWebResult(path, url, count)
            except ArenaWebQueryError:
                raise
            except BrowserError as exc:
                raise ArenaWebQueryError('网页浏览器加载失败或页面结构变化，请通过链接手动查询。') from exc
            finally:
                if browser:
                    try:
                        await asyncio.wait_for(browser.close(), timeout=5)
                    except (BrowserError, asyncio.TimeoutError):
                        pass

    async def _navigate(self, page, url):
        response = await page.goto(url, wait_until='domcontentloaded', timeout=25000)
        _check_location(page.url)
        if response is None or response.status >= 400:
            if response is not None and response.status in (401, 403, 429):
                raise ArenaWebQueryBlocked('作业网站拒绝或限制了访问，已停止自动查询。')
            raise ArenaWebQueryError('作业网站暂时不可用，请通过链接重试。')

    async def _wait_for_result(self, page):
        while True:
            _check_location(page.url)
            text = (await page.locator('body').inner_text())[:16000].lower()
            if any(marker in text for marker in BLOCK_MARKERS):
                raise ArenaWebQueryBlocked('网站要求登录、验证或限制访问，已停止自动查询。')
            if await page.locator('.ant-modal-content').count():
                raise ArenaWebQueryError('网站返回了查询提示，已停止自动查询，请打开链接查看。')
            loading = page.locator('.battle_search_button.ant-btn-loading, .battle_search_button[aria-busy="true"]')
            if await loading.count():
                await asyncio.sleep(0.4)
                continue
            if await page.locator(RESULT_SELECTOR).count():
                return
            empty = page.locator('.battle_search_result_ctn').filter(has_text='没有找到相关结果')
            if await empty.count():
                return
            await asyncio.sleep(0.4)

    async def _check_region_and_defenders(self, page, region, defender_ids):
        label = page.locator('label').filter(has_text=re.compile('^' + re.escape(REGIONS[region]) + '$'))
        if not await label.locator('input').is_checked():
            raise ArenaWebQueryError('网页服务器筛选未生效，未返回可能不适用的作业。')
        selection = page.locator('.battle_search_select').filter(has_text='防守方').first
        if await selection.locator('[style*="background-image"]').count() != 5:
            raise ArenaWebQueryError('作业网页未能完整带入五名角色，请打开链接核对。')
        if self.recognizer is None:
            raise ArenaWebQueryError('未能校验网页实际选中的角色，请更新角色头像库后重试。')
        await self._wait_for_artwork(selection)
        payload = await selection.screenshot(animations='disabled')
        try:
            with tempfile.TemporaryDirectory(prefix='pcr-web-defenders-') as directory:
                path = Path(directory) / 'selection.png'
                path.write_bytes(payload)
                actual = await asyncio.to_thread(self.recognizer.recognize_file, path)
        except (RuntimeError, OSError, ValueError) as exc:
            raise ArenaWebQueryError('网页实际角色识别不确定，请更新头像库或打开链接核对。') from exc
        if set(actual) != set(defender_ids) or len(actual) != 5:
            raise ArenaWebQueryError('网页实际选择与请求阵容不同，未返回可能错误的作业。')

    async def _wait_for_artwork(self, card):
        ready = await card.evaluate('''async root => {
            const images = [...root.querySelectorAll('img')];
            const urls = new Set([...root.querySelectorAll('[style]')].flatMap(el => {
                const image = getComputedStyle(el).backgroundImage;
                return [...image.matchAll(/url\\(["']?([^"')]+)["']?\\)/g)].map(x => x[1]);
            }));
            const pending = [...images.map(img => img.complete
                ? Promise.resolve(img.naturalWidth > 0)
                : new Promise(resolve => {img.addEventListener('load', () => resolve(true), {once:true});
                    img.addEventListener('error', () => resolve(false), {once:true});})),
                ...[...urls].map(url => new Promise(resolve => {
                    const img = new Image(); img.onload = () => resolve(true);
                    img.onerror = () => resolve(false); img.src = url;
                }))];
            return Promise.race([Promise.all(pending).then(items => items.every(Boolean)),
                new Promise(resolve => setTimeout(() => resolve(false), 8000))]);
        }''')
        if not ready:
            raise ArenaWebQueryError('网页角色图片未能完整加载，请打开链接查看。')
