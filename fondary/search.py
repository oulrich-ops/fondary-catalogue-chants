"""Étape 10 : recherche pour l'équipe de projection, liste de célébration, export de set OpenSong."""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from xml.sax.saxutils import quoteattr

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process

from .normalize import comparison_key

OK_SCORE = 85        # au-dessus : résolution sûre
MIN_SCORE = 72       # en dessous : introuvable
AMBIGUOUS_GAP = 4    # écart minimal entre le 1er et le 2e chant


@dataclass
class Index:
    songs: pd.DataFrame
    titles: list[list[str]]
    lines: list[str]
    texts: list[str]


def build_index(con: sqlite3.Connection) -> Index:
    songs = pd.read_sql("SELECT * FROM song", con)
    # titres (canonique + alternatifs) et incipits de toutes les versions du chant
    vers = pd.read_sql("""SELECT vc.song_id, v.incipit, v.chorus_incipit, v.title_keys
                          FROM version_catalogue vc JOIN song_version v USING(version_id)""", con)
    secs = pd.read_sql("""SELECT vc.song_id, s.text_normalized FROM version_catalogue vc
                          JOIN section s ON s.file_id = vc.preferred_file_id
                          WHERE vc.alias_of IS NULL ORDER BY vc.song_id, s.position""", con)
    by_song_titles = vers.groupby("song_id").title_keys.apply(
        lambda s: {k for x in s.fillna("") for k in x.split(" | ") if k}).to_dict()
    by_song_lines = vers.groupby("song_id").apply(
        lambda g: " ".join(comparison_key(x) for x in pd.concat([g.incipit, g.chorus_incipit]).fillna("") if x),
        include_groups=False).to_dict()
    by_song_text = secs.groupby("song_id").text_normalized.apply(" ".join).to_dict()
    titles = []
    for r in songs.itertuples():
        t = {r.normalized_title} | by_song_titles.get(r.song_id, set())
        t |= {comparison_key(a) for a in (r.alt_titles or "").split(" | ") if a}
        titles.append(sorted(t))
    return Index(songs=songs, titles=titles,
                 lines=[by_song_lines.get(s, "") for s in songs.song_id],
                 texts=[by_song_text.get(s, "") for s in songs.song_id])


def search(idx: Index, query: str, n: int = 10) -> pd.DataFrame:
    """Chants classés par pertinence : titre, première ligne / refrain, ou phrase des paroles."""
    q = comparison_key(query)
    if not q:
        return idx.songs.head(0)
    s_title = np.array([max(((fuzz.ratio(q, t) + fuzz.token_set_ratio(q, t)) / 2 for t in ts), default=0)
                        for ts in idx.titles])
    s_line = process.cdist([q], idx.lines, scorer=fuzz.partial_ratio)[0] * 0.92
    s_text = process.cdist([q], idx.texts, scorer=fuzz.partial_ratio)[0] * 0.85 if len(q) >= 15 else 0
    score = np.maximum.reduce([s_title, s_line, np.broadcast_to(s_text, s_title.shape)])
    top = np.argsort(-score, kind="stable")[:n]
    res = idx.songs.iloc[top].copy()
    res.insert(0, "score", score[top].round())
    return res[["score", "song_id", "canonical_title", "incipit", "n_versions", "n_files", "alt_titles",
                "collections", "authors"]].reset_index(drop=True)


def song_card(con: sqlite3.Connection, song_id: str) -> tuple[pd.Series, pd.DataFrame]:
    """Fiche chant : infos + versions (référence en tête) avec fichier préféré et tonalités."""
    sid = song_id
    while True:  # suit les redirections d'un chant fusionné
        row = con.execute("SELECT status, merged_into FROM song_registry WHERE song_id=?", (sid,)).fetchone()
        if not row or row[0] != "fusionne" or not row[1]:
            break
        sid = row[1]
    song = pd.read_sql("SELECT * FROM song WHERE song_id=?", con, params=(sid,)).iloc[0]
    versions = pd.read_sql("""
        SELECT vc.version_code, vc.version_label, vc.is_reference, vc.structure, vc.n_files, vc.keys,
               sf.path AS fichier_prefere, v.incipit, vc.version_id
        FROM version_catalogue vc
        JOIN song_version v USING(version_id)
        JOIN source_file sf ON sf.file_id = vc.preferred_file_id
        WHERE vc.song_id=? AND vc.alias_of IS NULL
        ORDER BY vc.is_reference DESC, vc.version_code""", con, params=(sid,))
    return song, versions


# ---------------------------------------------------------------- liste de célébration

_BULLET = re.compile(r"^\s*(?:[-*•·]+|\d{1,2}\s*[.)/-]|\d{1,2}\s+(?=\D))\s*")


def resolve_list(con: sqlite3.Connection, idx: Index, text: str) -> pd.DataFrame:
    """Une ligne = un chant (texte libre). Retourne le chant, sa version de référence et un statut."""
    rows = []
    for raw in text.splitlines():
        line = _BULLET.sub("", raw).strip()
        if not comparison_key(line):
            continue
        res = search(idx, line, n=3)
        best = res.iloc[0]
        gap = best.score - (res.iloc[1].score if len(res) > 1 else 0)
        status = ("introuvable" if best.score < MIN_SCORE else
                  "ok" if best.score >= OK_SCORE and gap >= AMBIGUOUS_GAP else "à vérifier")
        _, versions = song_card(con, best.song_id)
        ref = versions.iloc[0]
        rows.append({
            "ligne": raw.strip(), "statut": status, "score": best.score,
            "song_id": best.song_id, "chant": best.canonical_title,
            "version": ref.version_label, "version_code": ref.version_code,
            "fichier": ref.fichier_prefere,
            "autres_candidats": " | ".join(f"{r.canonical_title} ({r.score:.0f})" for r in res.iloc[1:].itertuples()),
        })
    return pd.DataFrame(rows)


def export_set(resolved: pd.DataFrame, name: str, out_dir: Path, songs_subfolder: str = "",
               strip_extension: bool = False) -> Path:
    """Écrit un set OpenSong (fichier NOUVEAU ; les chants existants ne sont pas touchés).

    Dans le set, name = nom du fichier chant, path = son sous-dossier DANS le dossier Songs d'OpenSong.
    songs_subfolder : à renseigner si le dossier analysé est lui-même un sous-dossier de Songs
    (ex. « Chants XML » si les chants sont dans Songs/Chants XML/).
    strip_extension : True si, dans OpenSong, les fichiers chants n'ont pas l'extension .xml
    (format natif d'OpenSong).
    """
    prefix = songs_subfolder.strip("/\\")
    groups = []
    for r in resolved[resolved.statut != "introuvable"].itertuples():
        p = PurePosixPath(r.fichier)
        parts = [x for x in (prefix, "" if str(p.parent) == "." else str(p.parent)) if x]
        sub = "/".join(parts) + "/" if parts else ""
        song_name = p.stem if strip_extension and p.suffix.lower() == ".xml" else p.name
        groups.append(f'    <slide_group name={quoteattr(song_name)} type="song" presentation="" path={quoteattr(sub)}/>')
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           f"<set name={quoteattr(name)}>\n  <slide_groups>\n" + "\n".join(groups) +
           "\n  </slide_groups>\n</set>\n")
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r'[<>:"/\\|?*]', "-", name).strip()
    path = out_dir / safe
    path.write_text(xml, encoding="utf-8")
    return path
