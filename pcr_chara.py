import re
import unicodedata
import json
from pathlib import Path

try:
    from .pcr_chara_data import CHARA_NAME
except ImportError:
    from pcr_chara_data import CHARA_NAME


UNKNOWN_CHARA_ID = 1000
_LEGACY_NPC_PLAYABLE = {
    1900: (1230, '爱梅斯'), 1908: (1185, '花凛'), 1909: (1186, '涅比亚'),
    1918: (1181, '兰法'), 1920: (1182, '美空'),
}
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


def _literal_chara_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return text.translate(_BRACKET_TRANSLATION).lower().strip()


def normalize_chara_text(value: str) -> str:
    text = _literal_chara_text(value)
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


def _team_segments(text, separators=',，/|_+-', protected=()):
    segments, current, depth = [], [], 0
    for position, char in enumerate(text):
        if char == '(':
            depth += 1
        elif char == ')':
            depth = max(0, depth - 1)
        if depth == 0 and position not in protected and (char.isspace() or char in separators):
            if current:
                segments.append(''.join(current))
                current = []
        else:
            current.append(char)
    if current:
        segments.append(''.join(current))
    return segments


class CharaRoster:
    def __init__(self, chara_name: dict[int, list[str]] | None = None, canonical_names=None):
        self._alias_to_id: dict[str, int] = {}
        self._literal_aliases: set[str] = set()
        source = chara_name or CHARA_NAME
        for item in sorted(canonical_names or [], key=lambda item: item['id']):
            self._alias_to_id.setdefault(compact_chara_text(item['name']), item['id'])
            self._literal_aliases.add(_literal_chara_text(item['name']))
        # Full names take priority over nicknames; playable IDs precede old NPCs.
        for raw_id, aliases in sorted(source.items()):
            if aliases:
                self._alias_to_id.setdefault(compact_chara_text(aliases[0]), int(raw_id))
        for raw_id, aliases in sorted(source.items()):
            chara_id = int(raw_id)
            for alias in aliases:
                self._literal_aliases.add(_literal_chara_text(alias))
                normalized = compact_chara_text(alias)
                if normalized and normalized not in self._alias_to_id:
                    self._alias_to_id[normalized] = chara_id
        self._aliases_by_length = sorted(self._alias_to_id, key=len, reverse=True)
        self._operator_aliases = [alias for alias in self._literal_aliases if any(c in alias for c in '+-_')]

    def parse_team(self, text: str) -> tuple[list[int], str]:
        team: list[int] = []
        unknown: list[str] = []
        raw = _literal_chara_text(text)
        raw = re.sub(r'\s+(?=\()', '', raw)
        segments = []
        for segment in _team_segments(raw, separators=''):
            # Preserve literal names (初音、栞 / tp+3), not arbitrary joined lists.
            if segment in self._literal_aliases:
                segments.append(segment)
            else:
                protected = set()
                for alias in self._operator_aliases:
                    start = segment.find(alias)
                    while start >= 0:
                        protected.update(range(start, start + len(alias)))
                        start = segment.find(alias, start + len(alias))
                segments.extend(_team_segments(segment, separators=',，/|_+-、', protected=protected))
        for segment in segments:
            remaining = compact_chara_text(segment)
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


def _load_bundled_aliases():
    path = Path(__file__).with_name('pcr_wiki_aliases.json')
    try:
        rows = json.loads(path.read_text(encoding='utf-8'))['characters']
    except (OSError, ValueError, KeyError, TypeError):
        return 0
    if not isinstance(rows, list) or len(rows) > 1024:
        return 0
    loaded = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        cid, name, aliases = row.get('id'), row.get('name'), row.get('aliases')
        if type(cid) is not int or not 1001 <= cid < 1900:
            continue
        if not isinstance(name, str) or not name or len(name) > 100 or not isinstance(aliases, list):
            continue
        existing = CHARA_NAME.setdefault(cid, [name])
        seen = {compact_chara_text(alias) for alias in existing}
        for alias in [name] + aliases[:100]:
            if not isinstance(alias, str) or not alias or len(alias) > 100:
                continue
            key = compact_chara_text(alias)
            if key and key not in seen:
                existing.append(alias)
                seen.add(key)
                loaded += 1
    for old, (target, _) in _LEGACY_NPC_PLAYABLE.items():
        if target in CHARA_NAME:
            for alias in CHARA_NAME.get(old, []):
                if alias not in CHARA_NAME[target]:
                    CHARA_NAME[target].append(alias)
    return loaded


_load_bundled_aliases()
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
        legacy = _LEGACY_NPC_PLAYABLE.get(cid)
        if legacy and compact_chara_text(name) == compact_chara_text(legacy[1]):
            cid = legacy[0]
        existing = CHARA_NAME.setdefault(cid, [])
        if name not in existing:
            existing.insert(0, name)
        accepted.append({'id': cid, 'name': name})
    canonical = {}
    for item in sorted(accepted, key=lambda item: item['id']):
        canonical.setdefault(compact_chara_text(item['name']), item['id'])
    official_ids = {item['id'] for item in accepted}
    aliases = {cid: list(names) for cid, names in CHARA_NAME.items()}
    # Legacy dictionaries include story NPC IDs such as Ameth 1900. Move their
    # familiar aliases to the playable ID confirmed by the game database.
    for cid, names in list(aliases.items()):
        target = canonical.get(compact_chara_text(names[0])) if names else None
        if cid not in official_ids and target is not None and target != cid:
            aliases.setdefault(target, []).extend(names)
            del aliases[cid]
    _ROSTER = CharaRoster(aliases, canonical_names=accepted)
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
