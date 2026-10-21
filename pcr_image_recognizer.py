"""Offline PCR icon recognition; prefetch only on an explicit update command.

Integration: ``load_cached_templates()`` is local-only;
``await asyncio.to_thread(recognizer.warm_templates, max_workers=8)`` updates
the pool on demand. Recognition and result-card get_icon never use the network.

References checked 2026-10-21 (design references, no source code copied):
* https://github.com/Alive24/PCRJJCAnalyzer/blob/master/util.py (GPL-3.0):
  OpenCV template matching of avatar crops, including history teams.
* https://github.com/Ice9Coffee/HoshinoBot/tree/master/hoshino/modules/priconne/arena
* https://github.com/zzbslayer/KokkoroBot/tree/master/hoshino/modules/priconne/arena
  Both GPL-3.0; text-team validation/query references, NOT image detectors.
  Hoshino's priconne/chara.py confirms the 61/31/11 icon naming convention.
* https://docs.opencv.org/4.x/d4/dc6/tutorial_py_template_matching.html
  OpenCV normalized correlation, with explicit zero-variance rejection here.

Game artwork from redive.estertion.win remains its owners' property, not GPL
artwork. No icons or user screenshots are distributed with this module.
Scores are correlations, not calibrated probabilities. Names and recommended
solutions belong to the caller's roster/arena query layer.
"""

from __future__ import annotations

import asyncio
import io
import math
import os
import re
import threading
import time
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen
from uuid import uuid4

try:
    import cv2
    import numpy as np
    from PIL import Image, ImageOps
except ImportError:  # pragma: no cover
    cv2 = np = Image = ImageOps = None

try:
    from .pcr_chara_data import CHARA_NAME
except ImportError:
    from pcr_chara_data import CHARA_NAME


ICON_URL_VARIANTS = tuple(
    "https://redive.estertion.win/icon/unit/{chara_id}" + str(v) + ".webp"
    for v in (61, 31, 11)
)
_VARIANTS = (61, 31, 11)
_MAX_CHARACTERS = 1024
_MAX_IMAGE_PIXELS = 20_000_000
_MAX_ICON_BYTES = 1_048_576
_CACHE_NAME = re.compile(r"([1-9][0-9]{3})(61|31|11)?\.webp")


class ImageRecognitionError(RuntimeError):
    pass


@dataclass(frozen=True)
class _Template:
    chara_id: int
    image: object
    gray: object
    edge: object
    patches: tuple


def _rgb(image):
    if min(image.size) < 16 or image.width * image.height > _MAX_IMAGE_PIXELS:
        raise ValueError("invalid icon dimensions")
    return ImageOps.fit(image.convert("RGB"), (64, 64), method=Image.Resampling.LANCZOS)


def _features(image):
    rgb = np.asarray(_rgb(image))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    dx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    dy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    return gray.astype(np.float32), cv2.magnitude(dx, dy)


def _decode_icon(payload):
    with Image.open(io.BytesIO(payload)) as image:
        if min(image.size) < 24 or max(image.size) > 512:
            raise ValueError("invalid downloaded icon dimensions")
        image.load()
        return image.convert("RGB")


def _fetch_icon(chara_id, variant, timeout, max_bytes, deadline):
    """One bounded request, no retries and no filesystem or shared-state writes."""
    url = ICON_URL_VARIANTS[_VARIANTS.index(variant)].format(chara_id=chara_id)
    deadline = min(deadline, time.monotonic() + timeout)
    try:
        remaining = min(timeout, deadline - time.monotonic())
        if remaining <= 0:
            return None
        request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "image/*"})
        with urlopen(request, timeout=remaining) as response:
            length = response.headers.get("Content-Length")
            if length and int(length) > max_bytes:
                return None
            chunks, size = [], 0
            read = getattr(response, "read1", response.read)
            while time.monotonic() < deadline:
                chunk = read(min(16384, max_bytes + 1 - size))
                if not chunk:
                    return _decode_icon(b"".join(chunks))
                chunks.append(chunk)
                size += len(chunk)
                if size > max_bytes:
                    return None
    except (OSError, URLError, ValueError, Image.DecompressionBombError):
        pass
    return None


class PcrImageRecognizer:
    def __init__(self, cache_dir: str | os.PathLike | None = None,
                 templates: dict[int, object] | None = None, threshold: float = 0.72):
        if Image is None:
            raise ImageRecognitionError("当前环境缺少 OpenCV/numpy/Pillow，无法识别阵容图片")
        if not math.isfinite(threshold) or not 0 < threshold <= 1:
            raise ValueError("threshold must be in (0, 1]")
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.threshold = float(threshold)
        self.templates = {}
        self._icons = {}
        self._bank = ()
        self._lock = threading.RLock()
        self._warming = False
        self._attempted = set()
        # Keep the old explicitly injected EXACT constant-image fixture only.
        # Never correlate flat templates: OpenCV would incorrectly return 1.0.
        injected = {}
        for raw_id, images in (templates or {}).items():
            images = images if isinstance(images, (list, tuple)) else [images]
            for variant, image in enumerate(images):
                injected[(int(raw_id), -variant)] = image.copy().convert("RGB")
        self._flat_fixture = bool(injected) and all(
            np.asarray(_rgb(im)).std(axis=(0, 1)).max() < 0.01
            for im in injected.values()
        )
        for (chara_id, variant), image in injected.items():
            self._install(chara_id, variant, image)
        self.load_cached_templates()

    def _install(self, chara_id, variant, image):
        gray, edge = _features(image)
        if gray[12:50, 10:54].std() < 3 and not self._flat_fixture:
            return False
        patches = tuple((cv2.resize(gray[12:50, 10:54], (round(44 * s), round(38 * s))),
                         cv2.resize(edge[12:50, 10:54], (round(44 * s), round(38 * s))))
                        for s in (0.82, 0.88, 0.94, 1.0, 1.06))
        entry = _Template(chara_id, image.copy(), gray, edge, patches)
        with self._lock:
            self._icons[(chara_id, variant)] = entry
            self._bank = tuple(self._icons.values())
            self.templates.setdefault(chara_id, image.copy())
        return True

    def _ids(self, chara_ids, max_characters):
        if not 1 <= max_characters <= _MAX_CHARACTERS:
            raise ValueError("max_characters must be in [1, 1024]")
        source = chara_ids if chara_ids is not None else CHARA_NAME
        ids = list(dict.fromkeys(int(i) for i in islice(source, max_characters + 1)
                                 if int(i) > 0 and int(i) != 1000))
        return ids[:max_characters]

    def load_templates(self, chara_ids=None, *, max_characters=512) -> int:
        """Load bounded local 100161.webp/100131.webp/100111.webp variants.

        Legacy 1001.webp is accepted. No network, including in __init__. Call
        again explicitly after an external cache update. Returns new variants.
        """
        ids = self._ids(chara_ids, max_characters)
        loaded = 0
        if self.cache_dir is None:
            return loaded
        for chara_id in ids:
            for variant in (*_VARIANTS, 0):
                if (chara_id, variant) in self._icons:
                    continue
                filename = f"{chara_id}{variant}.webp" if variant else f"{chara_id}.webp"
                path = self.cache_dir / filename
                try:
                    if path.stat().st_size > _MAX_ICON_BYTES:
                        continue
                    image = _decode_icon(path.read_bytes())
                    loaded += int(self._install(chara_id, variant, image))
                except (OSError, ValueError, Image.DecompressionBombError):
                    continue
        return loaded

    def load_cached_templates(self) -> int:
        """Local-only reload; returns the number of newly loaded variants.

        Also discovers newer four-digit character IDs absent from CHARA_NAME.
        At most 4096 directory entries / 1024 characters are examined per call.
        Missing/corrupt files are ignored. No cache directory is created.
        """
        if self.cache_dir is None:
            return 0
        ids = set()
        try:
            for path in islice(self.cache_dir.iterdir(), 4096):
                match = _CACHE_NAME.fullmatch(path.name)
                if match and int(match[1]) != 1000:
                    ids.add(int(match[1]))
                if len(ids) >= _MAX_CHARACTERS:
                    break
        except OSError:
            return 0
        return self.load_templates(sorted(ids), max_characters=_MAX_CHARACTERS)

    async def warmup(self, chara_ids=None, *, concurrency=6, max_characters=512,
                     timeout=5.0, total_timeout=120.0, max_bytes=524288,
                     variants=(61, 31, 11), retry_failed=False) -> dict:
        """Explicit startup prefetch with bounded workers, bytes and wall time.

        Returns {loaded, downloaded, failed, pending, timed_out}. ``loaded`` is
        the total in-memory variant count; others describe this call. Failures
        are negatively cached until retry_failed=True or a new instance. Overlap
        is rejected. Cancellation never installs or writes late thread results.
        Recognition/get_icon never fetch, even when the cache is empty.
        """
        if not 1 <= concurrency <= 16 or not 1 <= max_bytes <= _MAX_ICON_BYTES:
            raise ValueError("invalid concurrency or max_bytes")
        if (not math.isfinite(timeout) or not math.isfinite(total_timeout)
                or not 0 < timeout <= 30 or not 0 < total_timeout <= 600):
            raise ValueError("invalid timeout")
        variants = tuple(dict.fromkeys(variants))
        if not variants or any(v not in _VARIANTS for v in variants):
            raise ValueError("variants must contain 61, 31 or 11")
        ids = self._ids(chara_ids, max_characters)
        if self._warming:
            raise ImageRecognitionError("头像模板正在预热")
        self._warming = True
        tasks = []
        downloaded = failed = 0
        timed_out = False
        jobs = []
        try:
            await asyncio.to_thread(self.load_templates, ids, max_characters=max_characters)
            jobs = [(i, v) for i in ids for v in variants if (i, v) not in self._icons
                    and (retry_failed or (i, v) not in self._attempted)]
            iterator = iter(jobs)
            deadline = time.monotonic() + total_timeout

            async def worker():
                nonlocal downloaded, failed
                for chara_id, variant in iterator:
                    if time.monotonic() >= deadline:
                        return
                    image = await asyncio.to_thread(
                        _fetch_icon, chara_id, variant, timeout, max_bytes, deadline)
                    self._attempted.add((chara_id, variant))
                    if image is None or not self._install(chara_id, variant, image):
                        failed += 1
                        continue
                    downloaded += 1
                    if self.cache_dir is not None:
                        # Install complete images; readers never see half a file.
                        with io.BytesIO() as buffer:
                            image.save(buffer, format="WEBP", lossless=True)
                            payload = buffer.getvalue()
                        if len(payload) <= _MAX_ICON_BYTES:
                            path = self.cache_dir / f"{chara_id}{variant}.webp"
                            temporary = path.with_name(f".{path.stem}.{uuid4().hex}.tmp")
                            try:
                                self.cache_dir.mkdir(parents=True, exist_ok=True)
                                temporary.write_bytes(payload)
                                temporary.replace(path)
                            except OSError:
                                pass  # Memory cache works on read-only disks too.
                            finally:
                                try:
                                    temporary.unlink(missing_ok=True)
                                except OSError:
                                    pass

            tasks = [asyncio.create_task(worker()) for _ in range(min(concurrency, len(jobs)))]
            try:
                await asyncio.wait_for(asyncio.gather(*tasks), total_timeout)
            except asyncio.TimeoutError:
                timed_out = True
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            self._warming = False
        pending = len(jobs) - downloaded - failed
        return dict(loaded=len(self._bank), downloaded=downloaded, failed=failed,
                    pending=pending, timed_out=timed_out or pending > 0)

    def warm_templates(self, max_workers=8, *, chara_ids=None, **kwargs) -> dict:
        """Synchronous explicit pool update, suitable for asyncio.to_thread.

        Returns exactly {loaded, failed, total}, counting CHARACTERS, not rarity
        variants: loaded means at least one valid icon is available, including
        cache hits. A missing six-star variant alone is not a failed character.
        Explicit updates retry failed downloads; cached valid variants are kept.
        Remaining kwargs are warmup options. New-character IDs can be supplied
        explicitly; the default pool is CHARA_NAME (not an online roster).
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError("warm_templates is synchronous; use asyncio.to_thread or await warmup()")
        ids = self._ids(chara_ids, kwargs.get('max_characters', 512))
        kwargs.setdefault('retry_failed', True)
        asyncio.run(self.warmup(ids, concurrency=max_workers, **kwargs))
        with self._lock:
            loaded = sum(chara_id in self.templates for chara_id in ids)
        return dict(loaded=loaded, failed=len(ids) - loaded, total=len(ids))

    def get_icon(self, chara_id: int) -> Image.Image | None:
        """Return an independent PIL RGB image, or None immediately; no I/O."""
        with self._lock:
            image = self.templates.get(int(chara_id))
            return image.copy() if image is not None else None

    def recognize_file(self, image_path: str | os.PathLike) -> list[int]:
        """Legacy single-team API. Multi-team input is explicitly ambiguous."""
        teams = self.recognize_teams(image_path)
        if len(teams) != 1:
            raise ImageRecognitionError("图片包含多队，请使用 recognize_teams 选择防守队")
        return teams[0]["ids"]

    def recognize_slots(self, images) -> list[int]:
        """Match exactly five known avatar frames in order, without I/O.

        Accept a list/tuple of PIL images with each dimension in 24..512.
        Use one locked bank snapshot and the existing strict slot matcher;
        any invalid, uncertain or repeated identity aborts the whole result.
        Caller images are neither modified nor closed.
        """
        if not isinstance(images, (list, tuple)) or len(images) != 5:
            raise ImageRecognitionError("头像槽位必须是恰好五张图片的 list 或 tuple")
        for index, image in enumerate(images, 1):
            if not isinstance(image, Image.Image):
                raise ImageRecognitionError(f"第 {index} 个头像槽位不是 PIL 图片")
            if min(image.size) < 24 or max(image.size) > 512:
                raise ImageRecognitionError(f"第 {index} 个头像槽位的尺寸必须在 24 至 512 像素之间")
        with self._lock:
            bank = self._bank
        if not bank:
            raise ImageRecognitionError("头像模板库为空，请先发送「竞技场更新卡池」更新头像模板")

        ids = []
        for index, image in enumerate(images, 1):
            try:
                chara_id, score = self._match_segment(image.convert("RGB"), bank)
            except ImageRecognitionError as exc:
                raise ImageRecognitionError(f"第 {index} 个头像槽位：{exc}") from exc
            except (OSError, ValueError, Image.DecompressionBombError) as exc:
                raise ImageRecognitionError(f"无法读取第 {index} 个头像槽位：{exc}") from exc
            if type(chara_id) is not int or not 1001 <= chara_id < 2000:
                raise ImageRecognitionError(f"第 {index} 个头像槽位匹配到非标准角色 ID")
            if not math.isfinite(score) or score < self.threshold:
                raise ImageRecognitionError(f"第 {index} 个头像槽位的匹配置信度过低")
            if chara_id in ids:
                raise ImageRecognitionError(f"头像槽位含重复角色 {chara_id}，请检查图片")
            ids.append(chara_id)
        return ids

    def recognize_teams(self, image_path: str | os.PathLike, side='defense') -> list[dict]:
        """Recognize 1/3 rows, or left/right 1/3-row history panels.

        ``side`` is defense (right), attack (left), or all. Single-column crops
        use team_1..3 labels; paired panels use attack_1/defense_1 etc. ``all``
        is row-major (left then right). Boxes are original-image half-open
        [x1,y1,x2,y2], in left-to-right avatar order. Any selected bad slot
        aborts the entire result. Cross-team duplicates on one side also fail.
        """
        if side not in ('defense', 'attack', 'all'):
            raise ValueError("side must be defense, attack or all")
        with self._lock:
            bank = self._bank
        if not bank:
            raise ImageRecognitionError("头像模板库为空，请先发送「竞技场更新卡池」更新头像模板")
        try:
            with Image.open(image_path) as source:
                if source.width * source.height > _MAX_IMAGE_PIXELS:
                    raise ValueError("image too large")
                if source.getexif().get(274, 1) != 1:
                    raise ValueError("rotated EXIF image; export upright first")
                image = source.convert("RGB")
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            raise ImageRecognitionError(f"无法读取阵容图片：{exc}") from exc
        rows = _team_rows(np.asarray(image))
        paired = len(rows[0]) == 10
        results, used = [], {'attack': set(), 'defense': set(), 'team': set()}
        for row_index, row in enumerate(rows, 1):
            for column in range(2 if paired else 1):
                kind = ('attack' if column == 0 else 'defense') if paired else 'team'
                if paired and side != 'all' and side != kind:
                    continue
                boxes = row[column * 5:(column + 1) * 5]
                label = f"{kind}_{row_index}"
                ids, scores = [], []
                for box in boxes:
                    try:
                        chara_id, score = self._match_segment(image.crop(tuple(box)), bank)
                    except ImageRecognitionError as exc:
                        raise ImageRecognitionError(f"{label} 第 {len(ids) + 1} 个头像：{exc}") from exc
                    if chara_id in used[kind]:
                        raise ImageRecognitionError(f"{label} 含重复角色 {chara_id}，请检查图片")
                    used[kind].add(chara_id)
                    ids.append(chara_id)
                    scores.append(round(score, 4))
                results.append(dict(ids=ids, boxes=[list(b) for b in boxes],
                                    scores=scores, label=label))
        return results

    def _match_segment(self, segment, bank=None) -> tuple[int, float]:
        bank = self._bank if bank is None else bank
        if not bank:
            raise ImageRecognitionError("头像模板库为空")
        gray, edge = _features(segment)
        core = gray[12:50, 10:54]
        if self._flat_fixture:
            color = np.asarray(_rgb(segment))[12:50, 10:54]
            exact = {t.chara_id for t in bank if np.all(color == np.asarray(_rgb(t.image))[12:50, 10:54])}
            if len(exact) == 1:
                return exact.pop(), 1.0
            raise ImageRecognitionError("纯色测试模板不匹配")
        if min(segment.size) < 24 or core.std() < 7:
            raise ImageRecognitionError("头像过小或缺少纹理，无法可靠识别")
        if cv2.Laplacian(core, cv2.CV_32F).var() < 22:
            raise ImageRecognitionError("头像模糊，请发送原图")
        ranked = {}
        # Exclude level text, stars and corner badges. Search small shifts and
        # scales inside the detected frame, not the surrounding screenshot.
        for t in bank:
            best = -1.0
            for target, target_edge in t.patches:
                if target.std() < 3 or target_edge.std() < 1:
                    continue
                values = cv2.matchTemplate(gray[6:57, 4:60], target, cv2.TM_CCOEFF_NORMED)
                edges = cv2.matchTemplate(edge[6:57, 4:60], target_edge, cv2.TM_CCOEFF_NORMED)
                best = max(best, float(np.max(0.8 * values + 0.2 * edges)))
            ranked[t.chara_id] = max(ranked.get(t.chara_id, -1), best)
        matches = sorted(ranked.items(), key=lambda item: item[1], reverse=True)
        chara_id, score = matches[0]
        if not math.isfinite(score) or score < self.threshold:
            raise ImageRecognitionError(f"头像匹配置信度过低 ({score:.2f})，模板缺失或图片不清晰")
        if len(matches) > 1 and score - matches[1][1] < 0.06:
            raise ImageRecognitionError("头像匹配存在歧义，候选角色过于接近")
        return chara_id, score


def _overlap(a, b):
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return intersection / min((a[2] - a[0]) * (a[3] - a[1]),
                              (b[2] - b[0]) * (b[3] - b[1]))


def _icon_boxes(rgb):
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    edges = cv2.Canny(gray, 45, 130)
    masks = [edges, cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)),
             ((hsv[:, :, 1] > 65) & (hsv[:, :, 2] > 65)).astype(np.uint8) * 255]
    boxes = set()
    for mask_index, mask in enumerate(masks):
        contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if 20 <= min(w, h) and max(w, h) <= 512 and 0.84 <= w / h <= 1.19:
                # Canny can trace a broken frame out and back with near-zero
                # enclosed area; its perimeter still provides a useful box.
                if (cv2.contourArea(contour) / (w * h) > 0.45 or
                        mask_index < 2 and cv2.arcLength(contour, True) > 2 * (w + h)):
                    boxes.add((x, y, x + w, y + h))
    kept = []
    for box in sorted(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]), reverse=True):
        if not any(_overlap(box, other) > 0.8 and
                   (other[3] - other[1]) < 1.4 * (box[3] - box[1]) for other in kept):
            kept.append(box)
        if len(kept) >= 600:
            break
    return kept


def _regular_row(boxes):
    boxes = sorted(boxes)
    if len(boxes) not in (5, 10):
        return None
    widths = np.array([b[2] - b[0] for b in boxes])
    heights = np.array([b[3] - b[1] for b in boxes])
    if widths.max() / widths.min() > 1.22 or heights.max() / heights.min() > 1.22:
        return None
    centers = np.array([(b[0] + b[2]) / 2 for b in boxes])
    steps = np.diff(centers)
    within = np.delete(steps, 4) if len(boxes) == 10 else steps
    pitch = np.median(within)
    if (within.min() < 0.85 * np.median(widths) or
            np.max(np.abs(within - pitch)) > 0.18 * pitch or pitch > 1.65 * np.median(widths)):
        return None
    if len(boxes) == 10 and steps[4] < 1.30 * pitch:
        return None
    return boxes


def _team_rows(rgb):
    boxes = _icon_boxes(rgb)
    proposals = []
    # Size bands keep UI controls and facial details out of avatar rows.
    for anchor in boxes:
        size = anchor[3] - anchor[1]
        similar = [b for b in boxes if 0.88 * size <= b[3] - b[1] <= 1.13 * size]
        groups = []
        for box in sorted(similar, key=lambda b: (b[1] + b[3]) / 2):
            cy = (box[1] + box[3]) / 2
            if groups and abs(cy - np.median([(b[1] + b[3]) / 2 for b in groups[-1]])) < size * 0.20:
                groups[-1].append(box)
            else:
                groups.append([box])
        complete = [r for group in groups if (r := _regular_row(group)) is not None]
        rows = []
        incomplete = False
        if complete:
            reference = max(complete, key=len)
            for group in groups:
                row = _regular_row(group)
                if row is None and len(group) >= len(reference) * 0.6:
                    row = _complete_row(group, reference)
                if row is not None:
                    rows.append(row)
                elif sum(reference[0][0] <= (b[0] + b[2]) / 2 <= reference[-1][2]
                         for b in group) >= 2:
                    incomplete = True
        if incomplete:
            continue
        if len(rows) not in (1, 3) or len({len(row) for row in rows}) != 1:
            continue
        if any(abs(row[0][0] - rows[0][0][0]) > size * 0.25 or
               abs(row[-1][2] - rows[0][-1][2]) > size * 0.25 for row in rows):
            continue
        if len(rows) == 3:
            gaps = np.diff([np.mean([(b[1] + b[3]) / 2 for b in row]) for row in rows])
            if gaps.min() < size * 0.9 or gaps.max() / gaps.min() > 1.35 or gaps.max() > size * 3.5:
                continue
        if rows not in proposals:
            proposals.append(rows)
    if not proposals:
        # Borderless, tightly packed exports have no enclosing contours. Only
        # accept exact 5-by-1/3 square grids; every slot still needs a strong
        # texture match. Never apply this to an arbitrary screenshot crop.
        height, width = rgb.shape[:2]
        for count in (1, 3):
            if height >= 24 * count and abs(width * count / (height * 5) - 1) < 0.015:
                return [[(round(c * width / 5), round(r * height / count),
                          round((c + 1) * width / 5), round((r + 1) * height / count))
                         for c in range(5)] for r in range(count)]
        raise ImageRecognitionError("未找到完整的 5 头像行或 3 队布局，请裁剪游戏截图并发送原图")
    proposals.sort(key=lambda rows: sum(len(r) for r in rows) * (rows[0][0][3] - rows[0][0][1]) ** 2,
                   reverse=True)
    best = proposals[0]
    if len(best[0]) == 5:
        left, right = best[0][0][0], rgb.shape[1] - best[0][-1][2]
        panel_width = best[0][-1][2] - best[0][0][0]
        # A missing blurred half must not turn a battle-history panel into a
        # confident single-side result. Ask for a crop when the side is unclear.
        if max(left, right) > panel_width * 0.85 and min(left, right) < panel_width * 0.5:
            raise ImageRecognitionError("可能缺失另一侧阵容，无法确认防守方，请裁剪对手五人头像或发送清晰原图")
    for other in proposals[1:]:
        if not any(_overlap(a, b) > 0.5 for r in best for a in r for s in other for b in s):
            raise ImageRecognitionError("图片包含多个阵容面板，请只保留一张对战履历")
    return best


def _complete_row(group, reference):
    """Recover broken frames from aligned columns, never from guessed IDs."""
    size = float(np.median([b[3] - b[1] for b in reference]))
    cy = float(np.median([(b[1] + b[3]) / 2 for b in group]))
    columns = [(b[0] + b[2]) / 2 for b in reference]
    slots = {}
    for box in group:
        cx = (box[0] + box[2]) / 2
        index = min(range(len(columns)), key=lambda i: abs(columns[i] - cx))
        if abs(columns[index] - cx) > size * 0.22 or index in slots:
            return None
        slots[index] = box
    if len(columns) == 10 and min(sum(i < 5 for i in slots), sum(i >= 5 for i in slots)) < 3:
        return None
    row = [slots.get(i, (round(ref[0]), round(cy - size / 2),
                         round(ref[2]), round(cy + size / 2)))
           for i, ref in enumerate(reference)]
    return _regular_row(row)
