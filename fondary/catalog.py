"""Étape 3 : doublons exacts -> versions provisoires (1 version = n fichiers au texte identique).

Les identifiants VE-xxxxx sont attribués une seule fois et conservés d'une relance à l'autre
(table version_registry, jamais effacée). Pour l'instant l'ancrage se fait sur content_hash :
si le texte d'un fichier change, il rejoint ou crée une autre version ; les décisions humaines
(étape 8) permettront ensuite de figer les rattachements.
"""
from __future__ import annotations

import sqlite3
from collections import Counter
from datetime import datetime, timezone

import pandas as pd

PERSISTENT_DDL = [
    """CREATE TABLE IF NOT EXISTS version_registry (
        content_hash TEXT PRIMARY KEY,
        version_id   TEXT UNIQUE NOT NULL,
        created_at   TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS decision (
        decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
        action      TEXT NOT NULL,          -- annoter, confirmer, fusionner, separer, ...
        left_id     TEXT NOT NULL,          -- version_id
        right_id    TEXT NOT NULL,
        relation    TEXT NOT NULL,          -- meme_version, courte_longue, variante, traduction, different
        author      TEXT,
        created_at  TEXT NOT NULL,
        comment     TEXT,
        UNIQUE(left_id, right_id, action))""",
]

META_COLS = ["meta_author", "meta_copyright", "meta_ccli", "meta_hymn_number", "meta_theme", "meta_aka"]


def ensure_schema(con: sqlite3.Connection) -> None:
    for ddl in PERSISTENT_DDL:
        con.execute(ddl)


def _assign_ids(con: sqlite3.Connection, files: pd.DataFrame) -> dict[str, str]:
    reg = dict(con.execute("SELECT content_hash, version_id FROM version_registry"))
    last = max((int(v.split("-")[1]) for v in reg.values()), default=0)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # ordre déterministe : premier chemin rencontré
    new = (files[~files.content_hash.isin(reg)].groupby("content_hash").path.min().sort_values())
    for h in new.index:
        last += 1
        vid = f"VE-{last:05d}"
        reg[h] = vid
        con.execute("INSERT INTO version_registry VALUES (?,?,?)", (h, vid, now))
    return reg


def build_versions(con: sqlite3.Connection) -> pd.DataFrame:
    ensure_schema(con)
    files = pd.read_sql("SELECT * FROM source_file WHERE kind='song' AND n_sections > 0", con)
    reg = _assign_ids(con, files)
    files["version_id"] = files.content_hash.map(reg)

    # Fichier préféré : métadonnées les plus complètes, puis extension .xml, puis chemin le plus court.
    files["meta_fill"] = (files[META_COLS].fillna("") != "").sum(axis=1)
    files["path_len"] = files.path.str.len()
    files = files.sort_values(["version_id", "meta_fill", "has_xml_ext", "path_len"],
                              ascending=[True, False, False, True])
    files["is_preferred_file"] = ~files.duplicated("version_id")

    rows = []
    for vid, g in files.groupby("version_id", sort=True):
        p = g.iloc[0]
        colls = sorted({f"{c} {n}" for c, n in zip(g.collection, g.collection_number)
                        if pd.notna(c) and pd.notna(n) and c and n})
        authors = sorted({a for a in g.meta_author if pd.notna(a) and a and a.lower() != "inconnu"})
        rows.append({
            "version_id": vid,
            "content_hash": p.content_hash,
            "preferred_file_id": int(p.file_id),
            "n_files": len(g),
            "title": p.title_display,
            "alt_titles": " | ".join(sorted(set(g.title_display) - {p.title_display})),
            "title_keys": " | ".join(sorted(set(k for k in g.title_key if k))),
            "collections": " | ".join(colls),
            "authors": " | ".join(authors),
            "language": Counter(g.language).most_common(1)[0][0],
            "structure": p.structure,
            "n_sections": int(p.n_sections),
            "n_verses": int(p.n_verses),
            "has_chorus": bool(p.has_chorus),
            "has_bridge": bool(p.has_bridge),
            "incipit": p.incipit,
            "chorus_incipit": p.chorus_incipit,
            "n_chars": int(p.n_chars),
        })
    versions = pd.DataFrame(rows)
    versions.to_sql("song_version", con, if_exists="replace", index=False)
    files[["file_id", "version_id", "is_preferred_file"]].to_sql("file_version", con, if_exists="replace", index=False)
    con.commit()
    return versions
