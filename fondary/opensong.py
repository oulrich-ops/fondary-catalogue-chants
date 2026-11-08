"""Lecture tolérante d'un fichier OpenSong (lecture seule, aucune écriture)."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from charset_normalizer import from_bytes
from lxml import etree

# Champs OpenSong connus ; tout autre champ est aussi conservé dans raw_meta.
META_FIELDS = [
    "author", "copyright", "ccli", "hymn_number", "presentation", "key", "capo",
    "tempo", "time_sig", "timesig", "theme", "alttheme", "aka", "key_line",
    "user1", "user2", "user3",
]

IGNORED_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".ipynb", ".txt", ".doc", ".docx"}


@dataclass
class ParsedFile:
    path: str
    file_hash: str
    size: int
    kind: str  # song | not_song | error
    raw_title: str = ""
    raw_lyrics: str = ""
    raw_meta: dict[str, str] = field(default_factory=dict)
    encoding: str = "utf-8"
    error: str = ""


def _decode(data: bytes) -> tuple[str, str]:
    """Retourne (texte, encodage). UTF-8 d'abord, puis détection."""
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        best = from_bytes(data).best()
        enc = best.encoding if best else "cp1252"
        return data.decode(enc, errors="replace"), enc


def parse_file(path: Path, root: Path) -> ParsedFile:
    data = path.read_bytes()
    rel = path.relative_to(root).as_posix()
    pf = ParsedFile(path=rel, file_hash=hashlib.sha1(data).hexdigest(), size=len(data), kind="error")

    if path.suffix.lower() in IGNORED_SUFFIXES:
        pf.kind, pf.error = "not_song", f"extension {path.suffix}"
        return pf

    text, pf.encoding = _decode(data)
    # lxml refuse une str avec déclaration d'encodage : on repasse en bytes UTF-8.
    parser = etree.XMLParser(recover=True, resolve_entities=False, no_network=True)
    try:
        tree = etree.fromstring(text.encode("utf-8"), parser)
    except etree.XMLSyntaxError as e:
        pf.error = f"XML illisible : {e}"
        return pf
    if tree is None:
        pf.error = "XML vide ou illisible"
        return pf
    if tree.tag != "song":
        pf.kind, pf.error = "not_song", f"racine <{tree.tag}>"
        return pf

    pf.raw_title = (tree.findtext("title") or "").strip()
    pf.raw_lyrics = tree.findtext("lyrics") or ""
    for child in tree:
        if not isinstance(child.tag, str) or child.tag in ("title", "lyrics"):
            continue
        val = (child.text or "").strip()
        if val:
            pf.raw_meta[child.tag] = val

    if tree.find("lyrics") is None:
        pf.kind = "not_song"
        if len(tree) <= 1:
            pf.error = "coquille vide (titre seul, aucun contenu)"
        elif tree.find(".//body") is not None:
            pf.error = "diapositive personnalisée (<body>, pas de <lyrics>)"
        else:
            pf.error = "pas de <lyrics>"
        return pf

    pf.kind = "song"
    return pf


def iter_files(root: Path):
    for p in sorted(root.rglob("*")):
        if p.is_file():
            yield p
