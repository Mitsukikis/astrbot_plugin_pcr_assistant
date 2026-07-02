import os
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

try:
    from .pcr_chara_data import CHARA_NAME
except ImportError:
    from pcr_chara_data import CHARA_NAME


ICON_URL_VARIANTS = (
    "https://redive.estertion.win/icon/unit/{chara_id}31.webp",
    "https://redive.estertion.win/icon/unit/{chara_id}61.webp",
    "https://redive.estertion.win/icon/unit/{chara_id}11.webp",
)


class ImageRecognitionError(RuntimeError):
    pass


class PcrImageRecognizer:
    def __init__(
        self,
        cache_dir: str | os.PathLike | None = None,
        templates: dict[int, object] | None = None,
        threshold: float = 0.72,
    ):
        if Image is None:
            raise ImageRecognitionError("当前环境缺少 Pillow，无法识别阵容图片")
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.templates = {
            int(chara_id): _prepare_icon(image)
            for chara_id, image in (templates or {}).items()
        }
        self.threshold = float(threshold)

    def recognize_file(self, image_path: str | os.PathLike) -> list[int]:
        image = Image.open(image_path).convert("RGB")
        segments = _extract_five_icon_segments(image)
        if len(segments) != 5:
            raise ImageRecognitionError("未能从图片中切出 5 个头像")

        recognized: list[int] = []
        for segment in segments:
            chara_id, score = self._match_segment(segment)
            if score < self.threshold:
                raise ImageRecognitionError(f"头像识别置信度过低：{score:.2f}")
            recognized.append(chara_id)
        return recognized

    def _match_segment(self, segment) -> tuple[int, float]:
        prepared = _prepare_icon(segment)
        best_id = 0
        best_score = -1.0
        for chara_id in self._candidate_ids():
            template = self._template_for(chara_id)
            if template is None:
                continue
            score = _similarity(prepared, template)
            if score > best_score:
                best_id = chara_id
                best_score = score
        if not best_id:
            raise ImageRecognitionError("头像模板库为空")
        return best_id, best_score

    def _candidate_ids(self):
        if self.templates:
            return list(self.templates)
        return [
            int(chara_id)
            for chara_id in CHARA_NAME
            if int(chara_id) != 1000
        ]

    def _template_for(self, chara_id: int):
        chara_id = int(chara_id)
        if chara_id in self.templates:
            return self.templates[chara_id]
        if self.cache_dir is None:
            return None

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.cache_dir / f"{chara_id}.webp"
        if not path.exists():
            if not _download_icon(chara_id, path):
                return None
        try:
            image = Image.open(path).convert("RGB")
        except Exception:
            return None
        prepared = _prepare_icon(image)
        self.templates[chara_id] = prepared
        return prepared


def _download_icon(chara_id: int, path: Path) -> bool:
    for template in ICON_URL_VARIANTS:
        url = template.format(chara_id=int(chara_id))
        try:
            with urlopen(url, timeout=8) as response:
                payload = response.read()
        except (OSError, URLError):
            continue
        if payload:
            path.write_bytes(payload)
            return True
    return False


def _extract_five_icon_segments(image) -> list:
    crop = _candidate_team_crop(image)
    width, height = crop.size
    if width < 5 or height < 1:
        return []
    segment_width = width / 5
    segments = []
    for index in range(5):
        left = round(index * segment_width)
        right = round((index + 1) * segment_width)
        segment = crop.crop((left, 0, right, height))
        segments.append(_inner_square(segment))
    return segments


def _candidate_team_crop(image):
    bbox = _colorful_bbox(image)
    if bbox is None:
        return image
    left, top, right, bottom = bbox
    padding = 2
    left = max(0, left - padding)
    top = max(0, top - padding)
    right = min(image.width, right + padding)
    bottom = min(image.height, bottom + padding)
    return image.crop((left, top, right, bottom))


def _colorful_bbox(image):
    pixels = image.convert("RGB").load()
    width, height = image.size
    rows = []
    cols = []
    for y in range(height):
        row_count = 0
        for x in range(width):
            r, g, b = pixels[x, y]
            if _is_colorful(r, g, b):
                row_count += 1
                cols.append(x)
        if row_count:
            rows.append(y)
    if not rows or not cols:
        return None
    return min(cols), min(rows), max(cols) + 1, max(rows) + 1


def _is_colorful(r: int, g: int, b: int) -> bool:
    return max(r, g, b) - min(r, g, b) > 28 and max(r, g, b) > 70


def _inner_square(image):
    width, height = image.size
    side = min(width, height)
    left = max(0, (width - side) // 2)
    top = max(0, (height - side) // 2)
    square = image.crop((left, top, left + side, top + side))
    margin = max(1, round(side * 0.08))
    if side > margin * 2:
        square = square.crop((margin, margin, side - margin, side - margin))
    return square


def _prepare_icon(image):
    return _inner_square(image.convert("RGB")).resize((32, 32), Image.Resampling.LANCZOS)


def _similarity(left, right) -> float:
    left_pixels = list(left.getdata())
    right_pixels = list(right.getdata())
    if not left_pixels or len(left_pixels) != len(right_pixels):
        return 0.0
    total = 0
    for first, second in zip(left_pixels, right_pixels):
        total += sum((int(a) - int(b)) ** 2 for a, b in zip(first, second))
    mse = total / (len(left_pixels) * 3)
    return max(0.0, 1.0 - mse / (255 * 255))
