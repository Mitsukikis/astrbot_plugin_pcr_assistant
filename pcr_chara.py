import re
import unicodedata
import json
from pathlib import Path

try:
    from .pcr_chara_data import CHARA_NAME
except ImportError:
    from pcr_chara_data import CHARA_NAME


UNKNOWN_CHARA_ID = 1000
_SEPARATOR_RE = re.compile(r"[\s,，、/|_+\-]+")
_BRACKET_TRANSLATION = str.maketrans({
    "（": "(",
    "）": ")",
    "【": "(",
    "】": ")",
    "［": "(",
    "］": ")",
    "[": "(",
    "]": ")",
    "「": "(",
    "」": ")",
})


def normalize_chara_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.translate(_BRACKET_TRANSLATION).lower()
    text = _SEPARATOR_RE.sub(" ", text)
    return text.strip()


def compact_chara_text(value: str) -> str:
    return normalize_chara_text(value).replace(" ", "")


def name_for_id(chara_id: int) -> str:
    names = CHARA_NAME.get(int(chara_id), CHARA_NAME.get(UNKNOWN_CHARA_ID, ["未知角色"]))
    return str(names[0])


def id_from_unit_id(unit_id: int) -> int:
    return int(unit_id) // 100


def unit_id_from_id(chara_id: int) -> int:
    return int(chara_id) * 100 + 1


class CharaRoster:
    def __init__(self, chara_name: dict[int, list[str]] | None = None):
        self._alias_to_id: dict[str, int] = {}
        source = chara_name or CHARA_NAME
        for raw_id, aliases in source.items():
            chara_id = int(raw_id)
            for alias in aliases:
                normalized = compact_chara_text(alias)
                if normalized and normalized not in self._alias_to_id:
                    self._alias_to_id[normalized] = chara_id
        self._aliases_by_length = sorted(self._alias_to_id, key=len, reverse=True)

    def parse_team(self, text: str) -> tuple[list[int], str]:
        remaining = compact_chara_text(text)
        team: list[int] = []
        unknown: list[str] = []

        while remaining:
            match = self._longest_prefix(remaining)
            if match is None:
                unknown.append(remaining[0])
                remaining = remaining[1:]
                continue
            alias, chara_id = match
            team.append(chara_id)
            remaining = remaining[len(alias):]

        return team, "".join(unknown)

    def _longest_prefix(self, text: str) -> tuple[str, int] | None:
        for alias in self._aliases_by_length:
            if text.startswith(alias):
                return alias, self._alias_to_id[alias]
        return None


_ROSTER = CharaRoster()


def parse_team_names(text: str) -> tuple[list[int], str]:
    return _ROSTER.parse_team(text)


def extend_character_roster(characters, cache_path=None):
    global _ROSTER
    accepted = []
    for item in list(characters or [])[:1024]:
        if not isinstance(item, dict):
            continue
        try:
            cid = int(item['id'])
        except (KeyError, ValueError, TypeError):
            continue
        name = str(item.get('name') or '').strip()
        if not 1001 <= cid < 2000 or not name or len(name) > 100:
            continue
        existing = CHARA_NAME.setdefault(cid, [])
        if name not in existing:
            existing.insert(0, name)
        accepted.append({'id': cid, 'name': name})
    _ROSTER = CharaRoster()
    if cache_path is not None:
        path = Path(cache_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(accepted, ensure_ascii=False), encoding='utf-8')
        temp.replace(path)
    return len(accepted)


def load_character_roster(cache_path):
    try:
        data = json.loads(Path(cache_path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return 0
    return extend_character_roster(data if isinstance(data, list) else [])
