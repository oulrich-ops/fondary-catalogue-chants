"""Normalisation des titres et des paroles OpenSong.

Deux formes : affichage (nettoyage léger) et clé de comparaison (nettoyage agressif).
Le brut n'est jamais modifié.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field

from unidecode import unidecode

# --------------------------------------------------------------------------- utils

_APOS = str.maketrans({"’": "'", "‘": "'", "`": "'", "´": "'", "‛": "'",
                       "–": "-", "—": "-", "‐": "-", "«": '"', "»": '"', "“": '"', "”": '"',
                       " ": " "})


def clean_display(s: str) -> str:
    s = unicodedata.normalize("NFC", s).translate(_APOS)
    return re.sub(r"[ \t]+", " ", s).strip()


def comparison_key(s: str) -> str:
    """minuscules, sans accents, sans ponctuation ; élisions gardées (j'ai -> j ai)."""
    s = clean_display(s).lower().replace("œ", "oe").replace("æ", "ae")
    s = unidecode(s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- titres

# code -> (motif, numéro obligatoire ?)
COLLECTIONS = {
    "JEM": (r"j\.?e\.?m", False),
    "DPS": (r"d\.?p\.?s", False),
    "ATG": (r"a\.?t\.?g", False),
    "AILES": (r"ailes de la foi", False),
    "DIVERS": (r"divers", True),
    "ARC": (r"arc[- ]en[- ]ciel", False),
    "CC": (r"cc", True),
    "AF": (r"af", True),
}

_HINT_PATTERNS = [
    ("courte", r"\b(version )?(courte|court|abregee?)\b"),
    ("longue", r"\b(version )?(longue|long|complete)\b"),
    ("bis", r"\(\s*bis\s*\)"),
    ("arrangement", r"\barr(angement)?\.?\s*\d*\b"),
    ("copie", r"\b-?\s*copie\b|\(\d+\)\s*$"),
    ("couplets", r"\b\d+\s*couplets?\b"),
    ("langue", r"\((fr|en|eng|anglais|francais|mooree?|dioula|dioula)\)"),
]


@dataclass
class TitleInfo:
    display: str
    key: str
    hints: list[str] = field(default_factory=list)
    collection: str | None = None
    collection_number: str | None = None


_COLL_DISPLAY = r"(?:J\.?E\.?M|D\.?P\.?S|A\.?T\.?G|CC|AF|DIVERS|Ailes de la foi)"


def clean_title_display(raw: str) -> str:
    """Titre d'affichage sans numéro de recueil ni marque de copie (« JEM 079 A toi » -> « A toi »)."""
    s = clean_display(raw)
    s = re.sub(rf"^\s*{_COLL_DISPLAY}\s*n?[°o]?\s*\d{{1,4}}\s*(?:\(\d+\))?\s*[-.:]?\s*", "", s, flags=re.I)
    s = re.sub(rf"[\(\[]\s*{_COLL_DISPLAY}\s*\d{{1,4}}\s*[\)\]]", "", s, flags=re.I)
    s = re.sub(r"\s*(?:-\s*copie|\(\d+\)|_\d+)\s*$", "", s, flags=re.I)
    s = re.sub(r"\s*\((?:anglais|english|fran[cç]ais|french|allemand|en|fr|eng|moor[eé]|dioula)\)", "", s, flags=re.I)
    s = re.sub(r"\s{2,}", " ", s).strip(" -_")
    return s[:1].upper() + s[1:] if s else clean_display(raw)


def normalize_title(raw: str) -> TitleInfo:
    display = clean_display(raw)
    work = unidecode(display.lower())
    hints: list[str] = []
    coll = num = None

    # Numéro de recueil : « JEM 512 », « (JEM 57) », « Ailes de la foi 015 Titre », « DPS 12 »
    for code, (pat, need_num) in COLLECTIONS.items():
        q = "" if need_num else "?"
        m = re.search(rf"[\(\[]?\s*\b{pat}\.?\s*(?:(?:n(?:o|deg)?\.?\s*)?(\d{{1,4}})){q}\b\s*[\)\]]?", work)
        if m:
            coll, num = code, (m.group(1).lstrip("0") or "0") if m.group(1) else None
            work = (work[: m.start()] + " " + work[m.end():])
            hints.append(f"recueil:{code}" + (f" {num}" if num else ""))
            break

    for name, pat in _HINT_PATTERNS:
        if re.search(pat, work):
            hints.append(name)
            work = re.sub(pat, " ", work)

    key = comparison_key(work)
    # Numéro résiduel en tête seulement (reste de recueil). Un numéro en fin est gardé :
    # « Psaume 23 » et « Psaume 91 » sont deux chants différents.
    key = re.sub(r"^\d+\s+", "", key).strip()
    return TitleInfo(display=display, key=key, hints=hints, collection=coll, collection_number=num)


# --------------------------------------------------------------------------- paroles

_MARKER = re.compile(r"^\s*\[([^\]]+)\]\s*$")
# Vrai marqueur de section : V1, C, C2, Pont, CFin, V1s, R, Refrain 2…  (pas une phrase entre crochets)
_LABEL_OK = re.compile(r"^[A-Za-zÀ-ÿ]{1,8}\s?\d{0,2}[a-z]?$")
# Marqueur qui n'est qu'une indication de répétition : [x2], [2x], [3], [bis]
_LABEL_REPEAT = re.compile(r"^(x\s*\d+|\d+\s*x|bis|ter)$", re.I)
_LABEL_DIGITS = re.compile(r"^\d{1,2}$")  # [3] = couplet 3
# Ligne qui n'est qu'une consigne (« REF », « Refrain », « bis ») : pas du texte projeté.
_INSTRUCTION = re.compile(r"^\(?\s*(ref|refrain|chorus|bis|ter|x\s*\d+|\d+\s*x)\s*[.:)]?\s*\)?$", re.I)
_REPEAT = re.compile(r"[\[\(]\s*(bis|x\s*\d+|\d+\s*x|ter)\s*[\]\)]|\bx\s*\d\b", re.I)
_INLINE_CHORUS = re.compile(r"^\s*(?:ch(?:oe|œ)ur|refrain|ref|chorus)\s*\d*\s*[.:]\s*(.*)$", re.I)
_INLINE_LABEL = "\x00C"  # marqueur interne, renommé en « C » après lecture
_NUMBERED = re.compile(r"^([1-9]\d?)[ .)]\s*(.*)$")  # pas 0 : souvent un « O » mal tapé

KIND_BY_PREFIX = [
    ("pre-refrain", r"^(p|pr|pre)\d*$"),  # OpenSong : P = pre-chorus
    ("pont", r"^(b|pont|bridge)\d*"),
    ("refrain", r"^(c|r|ch|refrain|chorus)"),
    ("couplet", r"^(v|couplet|verse|s|strophe)"),
    ("fin", r"^(e|t|fin|end|tag|coda)"),
    ("intro", r"^(i|intro)"),
]


def section_kind(label: str) -> str:
    l = comparison_key(label).replace(" ", "")
    for kind, pat in KIND_BY_PREFIX:
        if re.match(pat, l):
            return kind
    return "autre"


@dataclass
class Section:
    label: str
    kind: str
    position: int
    text_display: str
    text_key: str
    has_repeat: bool = False

    @property
    def hash(self) -> str:
        return sha1(self.text_key)


@dataclass
class LyricsInfo:
    sections: list[Section]
    has_markers: bool
    has_chords: bool
    has_comments: bool
    numbered_split: bool
    raw_section_count: int  # avant dédoublonnage
    content_hash: str = ""
    incipit: str = ""
    chorus_incipit: str = ""

    @property
    def full_key(self) -> str:
        return "\n".join(s.text_key for s in self.sections)


def _clean_line(line: str) -> tuple[str, bool]:
    rep = bool(_REPEAT.search(line))
    line = _REPEAT.sub(" ", line)
    line = line.replace("|", " ").replace("_", "")
    return clean_display(line), rep


def parse_lyrics(raw: str) -> LyricsInfo:
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    blocks: list[tuple[str, list[str]]] = []
    current_label, current_lines = "", []
    has_markers = has_chords = has_comments = False

    for line in raw.split("\n"):
        m = _MARKER.match(line)
        if m and _LABEL_REPEAT.match(m.group(1).strip()):
            current_lines.append("(bis)")  # mémorisé comme drapeau de répétition
            continue
        if m and _LABEL_DIGITS.match(m.group(1).strip()):
            if current_lines or current_label:
                blocks.append((current_label, current_lines))
            current_label, current_lines = "V" + m.group(1).strip(), []
            has_markers = True
            continue
        if m and not _LABEL_OK.match(m.group(1).strip()):
            current_lines.append(m.group(1))  # phrase entre crochets = paroles
            continue
        if m:
            if current_lines or current_label:
                blocks.append((current_label, current_lines))
            current_label, current_lines = m.group(1).strip(), []
            has_markers = True
            continue
        if line.startswith("."):
            has_chords = True
            continue
        if line.startswith(";"):
            has_comments = True
            continue
        # « Chœur : » / « Refrain: texte » écrit dans les paroles = marqueur de refrain implicite
        im = _INLINE_CHORUS.match(line)
        if im:
            if current_lines or current_label:
                blocks.append((current_label, current_lines))
            current_label, current_lines = _INLINE_LABEL, ([im.group(1)] if im.group(1).strip() else [])
            continue
        # après un refrain implicite, un couplet numéroté (« 2. … ») ouvre un nouveau bloc
        if current_label == _INLINE_LABEL and _NUMBERED.match(line.strip()) and current_lines:
            blocks.append((current_label, current_lines))
            current_label, current_lines = "", []
        current_lines.append(line)
    blocks.append((current_label, current_lines))
    blocks = [("C" if lab == _INLINE_LABEL else lab, ls) for lab, ls in blocks]

    # Couplets numérotés sous un même marqueur (1 ..., 2 ..., 3 ...)
    numbered_split = False
    expanded: list[tuple[str, list[str]]] = []
    for label, lines in blocks:
        nums = {int(m.group(1)) for l in lines if (m := _NUMBERED.match(l.strip()))}
        if len(nums) >= 2 and section_kind(label or "v") == "couplet":
            numbered_split = True
            buckets: dict[int, list[str]] = {}
            cur = min(nums)
            for l in lines:
                m = _NUMBERED.match(l.strip())
                if m and int(m.group(1)) in nums:
                    cur = int(m.group(1))
                    l = m.group(2)
                buckets.setdefault(cur, []).append(l)
            base = re.sub(r"\d+$", "", label or "V")
            for n in sorted(buckets):
                expanded.append((f"{base}{n}", buckets[n]))
        else:
            # Numéro de couplet isolé en tête (« 1 O mon Dieu ») : retiré.
            if len(nums) == 1 and lines:
                for i, l in enumerate(lines):
                    if l.strip():
                        m = _NUMBERED.match(l.strip())
                        if m:
                            lines = lines[:i] + [m.group(2)] + lines[i + 1:]
                        break
            expanded.append((label, lines))

    sections: list[Section] = []
    seen: set[str] = set()
    raw_count = 0
    for label, lines in expanded:
        cleaned = [_clean_line(l) for l in lines]
        if any(_INSTRUCTION.match(l.strip()) for l in lines):
            cleaned.append(("", True))
        text_lines = [t for t, _ in cleaned if t and not _INSTRUCTION.match(t)]
        if not text_lines:
            continue
        raw_count += 1
        display = "\n".join(text_lines)
        key = comparison_key(display)
        if not key or key in seen:  # refrain répété : dédoublonné
            continue
        seen.add(key)
        sections.append(Section(
            label=label or "V", kind=section_kind(label or "v"), position=len(sections),
            text_display=display, text_key=key, has_repeat=any(r for _, r in cleaned),
        ))

    info = LyricsInfo(sections=sections, has_markers=has_markers, has_chords=has_chords,
                      has_comments=has_comments, numbered_split=numbered_split,
                      raw_section_count=raw_count)
    if sections:
        info.content_hash = sha1(info.full_key)
        info.incipit = sections[0].text_display.split("\n")[0]
        chorus = next((s for s in sections if s.kind == "refrain"), None)
        if chorus:
            info.chorus_incipit = chorus.text_display.split("\n")[0]
    return info
