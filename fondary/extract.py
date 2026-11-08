"""Étape 1-2 : extraction du dossier OpenSong + normalisation -> SQLite.

Produit les tables source_file et section (brutes + dérivés). Aucune écriture dans le dossier source.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from lingua import Language, LanguageDetectorBuilder

from .normalize import comparison_key, normalize_title, parse_lyrics
from .opensong import iter_files, parse_file

_LANGS = [Language.FRENCH, Language.ENGLISH, Language.GERMAN, Language.SPANISH,
          Language.PORTUGUESE, Language.ITALIAN, Language.SWAHILI, Language.YORUBA, Language.LATIN]
_detector = None


def detect_language(text: str) -> tuple[str, float]:
    global _detector
    if _detector is None:
        _detector = LanguageDetectorBuilder.from_languages(*_LANGS).build()
    text = text[:1500]
    if len(text) < 20:
        return "?", 0.0
    conf = _detector.compute_language_confidence_values(text)
    top = conf[0]
    if top.value < 0.6:
        return "?", round(top.value, 2)
    return top.language.iso_code_639_1.name.lower(), round(top.value, 2)


_CCLI_REAL = re.compile(r"^\d{3,8}$")


def classify_ccli(v: str) -> str:
    if not v:
        return "vide"
    v = v.strip()
    if _CCLI_REAL.match(v):
        return "numero_ccli"
    if re.match(r"^[a-z]{2,4}\s*\d{1,4}$", v, re.I):
        return "numero_recueil"
    return "autre"


def extract(root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    files, sections = [], []
    for i, path in enumerate(iter_files(root), start=1):
        pf = parse_file(path, root)
        rec = {
            "file_id": i, "path": pf.path, "file_hash": pf.file_hash, "size": pf.size,
            "kind": pf.kind, "error": pf.error, "encoding": pf.encoding,
            "has_xml_ext": path.suffix.lower() == ".xml",
            "raw_title": pf.raw_title, "raw_lyrics": pf.raw_lyrics,
            "raw_meta": json.dumps(pf.raw_meta, ensure_ascii=False), "last_seen_at": now,
        }
        for f in ("author", "copyright", "ccli", "hymn_number", "presentation", "key", "aka", "theme"):
            rec[f"meta_{f}"] = pf.raw_meta.get(f, "")

        if pf.kind == "song":
            t = normalize_title(pf.raw_title or path.stem)
            ly = parse_lyrics(pf.raw_lyrics)
            text = "\n".join(s.text_display for s in ly.sections)
            lang, lang_conf = detect_language(text)
            rec.update({
                "title_display": t.display, "title_key": t.key, "title_hints": json.dumps(t.hints, ensure_ascii=False),
                "collection": t.collection, "collection_number": t.collection_number,
                "file_name_key": comparison_key(re.sub(r"\.xml$", "", path.name, flags=re.I)),
                "n_sections": len(ly.sections), "n_sections_raw": ly.raw_section_count,
                "n_verses": sum(s.kind == "couplet" for s in ly.sections),
                "has_chorus": any(s.kind == "refrain" for s in ly.sections),
                "has_bridge": any(s.kind == "pont" for s in ly.sections),
                "structure": " ".join(s.label for s in ly.sections),
                "has_markers": ly.has_markers, "has_chords": ly.has_chords,
                "has_comments": ly.has_comments, "numbered_split": ly.numbered_split,
                "n_chars": len(text), "uppercase_ratio": _upper_ratio(text),
                "content_hash": ly.content_hash, "incipit": ly.incipit, "chorus_incipit": ly.chorus_incipit,
                "language": lang, "language_conf": lang_conf,
                "ccli_kind": classify_ccli(pf.raw_meta.get("ccli", "")),
            })
            for s in ly.sections:
                sections.append({"file_id": i, "position": s.position, "label": s.label, "kind": s.kind,
                                 "text_display": s.text_display, "text_normalized": s.text_key,
                                 "section_hash": s.hash, "has_repeat": s.has_repeat})
        files.append(rec)
    return pd.DataFrame(files), pd.DataFrame(sections)


def _upper_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    return round(sum(c.isupper() for c in letters) / len(letters), 2) if letters else 0.0


def save_sqlite(files: pd.DataFrame, sections: pd.DataFrame, db: Path) -> None:
    db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db) as con:
        files.to_sql("source_file", con, if_exists="replace", index=False)
        sections.to_sql("section", con, if_exists="replace", index=False)
        con.execute("CREATE INDEX IF NOT EXISTS ix_section_file ON section(file_id)")
        con.execute("CREATE INDEX IF NOT EXISTS ix_file_content ON source_file(content_hash)")
