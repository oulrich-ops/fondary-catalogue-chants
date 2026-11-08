"""Étape 9 : catalogue canonique.

Pour chaque chant : titre canonique, titres alternatifs, version de référence,
et pour chaque version distincte un code stable (CH-00142.fr.courte) et un libellé lisible
(« FR · courte — couplets 1 et 3 + refrain »), décrits par différence avec la référence.
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from collections import Counter

import pandas as pd
from rapidfuzz import fuzz

from .clustering import _load, assign_song_ids, cluster_songs, cluster_version_groups
from .matching import FULL, band_of, coverage, load_versions
from .normalize import clean_title_display, comparison_key

SECTION_MATCH = 80

DDL = """CREATE TABLE IF NOT EXISTS version_code_registry (
    version_id TEXT PRIMARY KEY, song_id TEXT NOT NULL, version_code TEXT NOT NULL,
    custom_label TEXT)"""


# ---------------------------------------------------------------- titres

def _accents(s: str) -> int:
    return sum(1 for ch in unicodedata.normalize("NFD", s) if unicodedata.category(ch) == "Mn")


def canonical_title(titles: list[str]) -> tuple[str, list[str]]:
    """Titre le plus fréquent (sans n° de recueil) ; à égalité, le mieux accentué."""
    cleaned = [clean_title_display(t) for t in titles if t]
    by_key = Counter(comparison_key(t) for t in cleaned)
    best_key = sorted(by_key, key=lambda k: (-by_key[k], -len(k)))[0]
    forms = Counter(t for t in cleaned if comparison_key(t) == best_key)
    # à clé égale, la forme accentuée est la bonne typographie (« À toi » plutôt que « A toi »)
    best = sorted(forms, key=lambda t: (-_accents(t), -forms[t], not t[:1].isupper(), t))[0]
    alts, seen = [], {best_key}
    for t in sorted(set(cleaned)):
        k = comparison_key(t)
        if k not in seen:
            seen.add(k)
            alts.append(t)
    return best, alts


# ---------------------------------------------------------------- structure & libellés

def _join(nums: list[int]) -> str:
    if len(nums) == 1:
        return f"couplet {nums[0]}"
    if nums == list(range(nums[0], nums[-1] + 1)) and len(nums) > 2:
        return f"couplets {nums[0]} à {nums[-1]}"
    return "couplets " + ", ".join(map(str, nums[:-1])) + f" et {nums[-1]}"


def structure_text(secs: pd.DataFrame) -> str:
    n = int((secs.kind == "couplet").sum())
    parts = [f"{n} couplet{'s' if n > 1 else ''}"] if n else []
    if (secs.kind == "refrain").any():
        parts.append("refrain")
    if (secs.kind == "pont").any():
        parts.append("pont")
    return " + ".join(parts) or "texte unique"


def _map_sections(v_secs: pd.DataFrame, ref_secs: pd.DataFrame) -> list[int | None]:
    """Pour chaque section de v : position de la section correspondante dans la référence (ou None)."""
    out = []
    for t in v_secs.text_normalized:
        best = max(((fuzz.ratio(t, r), i) for i, r in enumerate(ref_secs.text_normalized)), default=(0, None))
        out.append(best[1] if best[0] >= SECTION_MATCH else None)
    return out


def describe(v_secs, ref_secs, cov_v_ref: float, cov_ref_v: float, same_lang: bool) -> tuple[str, str, str]:
    """(nature, slug du code, facette structure)."""
    if not same_lang:
        return "traduction", "trad", structure_text(v_secs)
    if cov_v_ref >= FULL and cov_ref_v < FULL:
        ref_verses = [i for i, k in enumerate(ref_secs.kind) if k == "couplet"]
        kept = sorted({m for m in _map_sections(v_secs, ref_secs) if m in ref_verses})
        nums = [ref_verses.index(m) + 1 for m in kept]
        if nums:
            txt = _join(nums) + (" + refrain" if (v_secs.kind == "refrain").any() else "")
        else:
            txt = structure_text(v_secs)
        return "courte", "courte", txt
    if cov_ref_v >= FULL and cov_v_ref < FULL:
        extra = sum(m is None for m in _map_sections(v_secs, ref_secs))
        return "longue", "longue", f"+ {extra} section{'s' if extra > 1 else ''} · {structure_text(v_secs)}"
    if cov_v_ref >= FULL and cov_ref_v >= FULL:
        return "variante mineure", "var", structure_text(v_secs)
    return "variante de texte", "var", structure_text(v_secs)


# ---------------------------------------------------------------- construction

def build_catalogue(con: sqlite3.Connection) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    con.execute(DDL)
    versions, cands = _load(con)
    songs, _, conflicts = cluster_songs(versions, cands)
    rep = cluster_version_groups(songs, versions, cands)
    song_ids, redirects = assign_song_ids(con, songs)

    vinfo = pd.read_sql("SELECT * FROM song_version", con).set_index("version_id")
    secs = pd.read_sql("SELECT s.file_id, s.position, s.label, s.kind, s.text_normalized FROM section s "
                       "JOIN song_version v ON v.preferred_file_id = s.file_id ORDER BY s.file_id, s.position", con)
    secs_of = {fid: g.reset_index(drop=True) for fid, g in secs.groupby("file_id")}
    files = pd.read_sql("SELECT fv.version_id, sf.title_display, sf.meta_aka, sf.meta_key FROM file_version fv "
                        "JOIN source_file sf USING(file_id)", con)
    titles_of = files.groupby("version_id").title_display.apply(list).to_dict()
    aka_of = files[files.meta_aka.fillna("") != ""].groupby("version_id").meta_aka.apply(list).to_dict()
    keys_of = files[files.meta_key.fillna("") != ""].groupby("version_id").meta_key.apply(set).to_dict()
    vs = load_versions(con)
    pair_score = {(a, b): s for a, b, s in zip(cands.left_id, cands.right_id, cands.global_score)}
    codes_prev = {r[0]: (r[1], r[2], r[3]) for r in con.execute(
        "SELECT version_id, song_id, version_code, custom_label FROM version_code_registry")}

    song_rows, ver_rows = [], []
    for sid, members in zip(song_ids, songs):
        members = sorted(members)
        reps = sorted({rep[v] for v in members})
        n_files_of = {r: int(sum(vinfo.at[v, "n_files"] for v in members if rep[v] == r)) for r in reps}
        # Référence : français d'abord, puis la plus complète, puis la plus répandue
        ref = sorted(reps, key=lambda r: (vinfo.at[r, "language"] != "fr", -vinfo.at[r, "n_sections"],
                                          -n_files_of[r], r))[0]
        ref_secs = secs_of.get(vinfo.at[ref, "preferred_file_id"], pd.DataFrame(columns=secs.columns))
        all_titles = [t for v in members for t in titles_of.get(v, [])] + [t for v in members for t in aka_of.get(v, [])]
        title, alts = canonical_title(all_titles)

        # cohésion : moyenne des scores sur toutes les paires internes (paire non candidate = 0)
        pairs = [(a, b) for i, a in enumerate(members) for b in members[i + 1:]]
        cohesion = sum(pair_score.get(p, 0.0) for p in pairs) / len(pairs) if pairs else 1.0

        used_codes: set[str] = set()
        rep_rows = []
        for r in sorted(reps, key=lambda r: (r != ref, r)):
            v_secs = secs_of.get(vinfo.at[r, "preferred_file_id"], pd.DataFrame(columns=secs.columns))
            lang = vinfo.at[r, "language"] if vinfo.at[r, "language"] != "?" else vinfo.at[ref, "language"]
            if r == ref:
                nature, slug, struct = "complète", "", structure_text(v_secs)
                ab = ba = 1.0
            else:
                ab, ba = coverage(vs[r], vs[ref])
                nature, slug, struct = describe(v_secs, ref_secs, ab, ba, lang == vinfo.at[ref, "language"])
            base = f"{sid}.{lang}" + (f".{slug}" if slug else "")
            prev = codes_prev.get(r)
            if prev and prev[0] == sid and prev[1] not in used_codes:
                code = prev[1]  # code figé : on ne le recalcule pas
            else:
                code = base
                if code in used_codes:
                    src = (vinfo.at[r, "collections"] or "").split(" ")[0].lower()
                    code = f"{base}-{src}" if src else base
                letter = ord("b")
                while code in used_codes:
                    code, letter = f"{base}-{chr(letter)}", letter + 1
            used_codes.add(code)
            label = f"{lang.upper()} · {nature} — {struct}"
            if prev and prev[0] == sid and prev[2]:
                label = prev[2]  # libellé renommé par l'équipe : jamais écrasé
            con.execute("INSERT INTO version_code_registry (version_id, song_id, version_code) VALUES (?,?,?) "
                        "ON CONFLICT(version_id) DO UPDATE SET song_id=excluded.song_id, "
                        "version_code=excluded.version_code, custom_label=CASE WHEN "
                        "version_code_registry.song_id = excluded.song_id THEN custom_label END",
                        (r, sid, code))
            keys = sorted({k for v in members if rep[v] == r for k in keys_of.get(v, set())})
            rep_rows.append({"version_id": r, "song_id": sid, "version_code": code, "version_label": label,
                             "version_type": nature, "language": lang, "is_reference": r == ref,
                             "structure": struct, "coverage_to_ref": round(ab, 3), "coverage_from_ref": round(ba, 3),
                             "n_files": n_files_of[r], "keys": ", ".join(keys),
                             "preferred_file_id": int(vinfo.at[r, "preferred_file_id"])})
        for v in members:
            if v != rep[v]:  # quasi-doublon absorbé par son représentant
                ver_rows.append({"version_id": v, "song_id": sid, "alias_of": rep[v]})
        ver_rows.extend({**row, "alias_of": None} for row in rep_rows)

        song_rows.append({
            "song_id": sid, "canonical_title": title, "normalized_title": comparison_key(title),
            "alt_titles": " | ".join(alts),
            "original_language": vinfo.at[ref, "language"],
            "authors": " | ".join(sorted({a for v in members for a in (vinfo.at[v, "authors"] or "").split(" | ") if a})),
            "collections": " | ".join(sorted({c for v in members for c in (vinfo.at[v, "collections"] or "").split(" | ") if c})),
            "incipit": vinfo.at[ref, "incipit"], "chorus_incipit": vinfo.at[ref, "chorus_incipit"],
            "reference_version_id": ref, "n_versions": len(reps), "n_text_versions": len(members),
            "n_files": int(sum(n_files_of.values())), "cohesion": round(cohesion, 3),
            "confidence_band": (band_of(cohesion).replace("rejet", "faible")) if len(members) > 1 else "isole",
            "status": "propose", "merged_into": None,
        })

    song_df = pd.DataFrame(song_rows)
    ver_df = pd.DataFrame(ver_rows)
    for col in ("n_files", "preferred_file_id"):
        ver_df[col] = ver_df[col].astype("Int64")
    song_df.to_sql("song", con, if_exists="replace", index=False)
    ver_df.to_sql("version_catalogue", con, if_exists="replace", index=False)
    con.commit()
    return song_df, ver_df, {"conflicts": conflicts, "redirects": redirects}


def catalogue_report(song_df: pd.DataFrame, ver_df: pd.DataFrame, extra: dict) -> str:
    reps = ver_df[ver_df.alias_of.isna()]
    multi = song_df[song_df.n_text_versions > 1]
    out = ["# Catalogue (étapes 7 et 9)\n",
           f"- **{len(song_df)} chants** (CH-…) pour {len(ver_df)} textes distincts",
           f"- {len(reps)} versions affichées après fusion des quasi-doublons (fautes, ponctuation) : "
           f"{len(ver_df) - len(reps)} textes absorbés",
           f"- {len(multi)} chants regroupent plusieurs textes ; {int((song_df.n_versions > 1).sum())} ont plusieurs versions affichées",
           f"- Conflits entre décisions humaines : {len(extra['conflicts'])}",
           f"- Identifiants redirigés (fusions) : {len(extra['redirects'])}\n",
           "## Cohésion des chants regroupés\n",
           multi.confidence_band.value_counts().rename_axis("bande").reset_index(name="chants").to_markdown(index=False),
           "\n## Types de versions\n",
           reps.version_type.value_counts().rename_axis("type").reset_index(name="versions").to_markdown(index=False),
           "\n## Chants avec le plus de versions\n"]
    top = song_df.sort_values(["n_versions", "n_files"], ascending=False).head(15)
    out.append(top[["song_id", "canonical_title", "n_versions", "n_text_versions", "n_files", "cohesion"]].to_markdown(index=False))
    out.append("\n## Exemples de libellés\n")
    ex = reps[reps.song_id.isin(top.song_id.head(5))].sort_values(["song_id", "is_reference"], ascending=[True, False])
    out.append(ex[["version_code", "version_label", "n_files"]].to_markdown(index=False))
    return "\n".join(out)
