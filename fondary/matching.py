"""Étapes 4 à 6 : génération de candidats, signaux, score combiné, relation proposée.

Tout se fait au niveau VERSION (les doublons exacts sont déjà fusionnés à l'étape 3).

Écart assumé par rapport au cadrage : le recouvrement A→B / B→A est calculé par LIGNE de A
cherchée dans le texte entier de B (pondérée par sa longueur) plutôt que section contre section :
18 % des fichiers n'ont pas de marqueurs, et un même texte est souvent coupé différemment
(sections comme retours à la ligne) d'un fichier à l'autre.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from itertools import combinations

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process
from sklearn.feature_extraction.text import TfidfVectorizer

from .normalize import comparison_key

# ---------------------------------------------------------------- paramètres (à calibrer)
WEIGHTS = {"coverage": 0.45, "tfidf": 0.20, "incipit": 0.15, "title": 0.10, "meta": 0.10}
LINE_MATCH = 85          # ratio rapidfuzz pour considérer deux lignes identiques
FULL = 0.90              # recouvrement « ≈ 1 »
PARTIAL = 0.30           # en dessous : textes différents
TFIDF_TOP_K = 10
TFIDF_MIN = 0.30
MAX_BLOCK = 40           # un bloc plus gros (« psaume », « alleluia ») est ignoré pour le blocking par titre
BANDS = [(0.90, "tres_forte"), (0.70, "probable"), (0.50, "incertaine"), (0.0, "rejet")]


@dataclass
class V:
    id: str
    title_keys: list[str]
    colls: set[str]
    authors: list[str]
    lines: list[str]
    weights: np.ndarray
    text_key: str
    incipit: str
    chorus: str
    lang: str
    n_chars: int


def _split(s: str) -> list[str]:
    return [x for x in (s or "").split(" | ") if x]


def load_versions(con: sqlite3.Connection) -> dict[str, V]:
    vers = pd.read_sql("SELECT * FROM song_version", con)
    secs = pd.read_sql(
        "SELECT s.file_id, s.position, s.text_display FROM section s "
        "JOIN song_version v ON v.preferred_file_id = s.file_id ORDER BY s.file_id, s.position", con)
    by_file = secs.groupby("file_id").text_display.apply(list).to_dict()
    out = {}
    for r in vers.itertuples():
        lines, seen = [], set()
        for sec in by_file.get(r.preferred_file_id, []):
            for l in sec.split("\n"):
                k = comparison_key(l)
                if k and k not in seen:
                    seen.add(k)
                    lines.append(k)
        out[r.version_id] = V(
            id=r.version_id, title_keys=_split(r.title_keys), colls=set(_split(r.collections)),
            authors=[comparison_key(a) for a in _split(r.authors)], lines=lines,
            weights=np.array([len(l) for l in lines], dtype=np.float32),
            text_key=" ".join(lines), incipit=comparison_key(r.incipit or ""),
            chorus=comparison_key(r.chorus_incipit or ""), lang=r.language, n_chars=r.n_chars,
        )
    return out


# ---------------------------------------------------------------- étape 4 : blocking

def generate_candidates(vs: dict[str, V]) -> tuple[dict[tuple[str, str], set[str]], dict[tuple[str, str], float]]:
    """Retourne {paire: {sources du blocking}} et le cosinus TF-IDF de chaque paire."""
    pairs: dict[tuple[str, str], set[str]] = {}

    def add(a: str, b: str, src: str) -> None:
        if a != b:
            pairs.setdefault((min(a, b), max(a, b)), set()).add(src)

    def add_blocks(key_fn, src: str, max_block: int = MAX_BLOCK) -> None:
        blocks: dict[str, set[str]] = {}
        for v in vs.values():
            for k in key_fn(v):
                if k:
                    blocks.setdefault(k, set()).add(v.id)
        for ids in blocks.values():
            if 1 < len(ids) <= max_block:
                for a, b in combinations(sorted(ids), 2):
                    add(a, b, src)

    add_blocks(lambda v: v.title_keys, "titre")
    add_blocks(lambda v: v.colls, "recueil")
    add_blocks(lambda v: [v.incipit] if len(v.incipit) >= 12 else [], "incipit")
    add_blocks(lambda v: [v.chorus] if len(v.chorus) >= 12 else [], "refrain")

    ids = list(vs)
    index = {vid: i for i, vid in enumerate(ids)}
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2, sublinear_tf=True, dtype=np.float32)
    X = vec.fit_transform([vs[i].text_key for i in ids])
    for start in range(0, X.shape[0], 500):
        sims = (X[start:start + 500] @ X.T).toarray()
        for r in range(sims.shape[0]):
            sims[r, start + r] = -1
        top = np.argpartition(-sims, TFIDF_TOP_K, axis=1)[:, :TFIDF_TOP_K]
        for r, cols in enumerate(top):
            for c in cols:
                if sims[r, c] >= TFIDF_MIN:
                    add(ids[start + r], ids[c], "tfidf")

    keys = list(pairs)
    ia = np.array([index[a] for a, _ in keys])
    ib = np.array([index[b] for _, b in keys])
    cos = np.asarray(X[ia].multiply(X[ib]).sum(axis=1)).ravel() if keys else np.array([])
    return pairs, dict(zip(keys, cos.astype(float)))


# ---------------------------------------------------------------- étape 5 : signaux

def _cov(a: V, b: V) -> float:
    """Part (pondérée par la longueur) des lignes de A retrouvées quelque part dans le texte de B.

    partial_ratio aligne la ligne sur le meilleur passage de B : insensible aux retours à la
    ligne (une ligne de A peut être coupée en deux dans B) et tolérant aux fautes.
    """
    if not a.lines or not b.text_key:
        return 0.0
    s = process.cdist(a.lines, [b.text_key], scorer=fuzz.partial_ratio, dtype=np.uint8, workers=1)[:, 0]
    return float((a.weights * (s >= LINE_MATCH)).sum() / a.weights.sum())


def coverage(a: V, b: V) -> tuple[float, float]:
    return _cov(a, b), _cov(b, a)


def title_sim(a: V, b: V) -> float:
    return max((fuzz.token_set_ratio(x, y) / 100 for x in a.title_keys for y in b.title_keys), default=0.0)


def incipit_sim(a: V, b: V) -> float:
    s = fuzz.ratio(a.incipit, b.incipit) / 100 if a.incipit and b.incipit else 0.0
    if a.chorus and b.chorus:
        s = max(s, fuzz.ratio(a.chorus, b.chorus) / 100)
    return s


def meta_signals(a: V, b: V) -> tuple[float, bool, str]:
    """(score, conflit de recueil, explication)."""
    shared = a.colls & b.colls
    if shared:
        return 1.0, False, "même n° " + ", ".join(sorted(shared))
    conflict = bool({c.split()[0] for c in a.colls} & {c.split()[0] for c in b.colls})
    authors = max((fuzz.token_set_ratio(x, y) for x in a.authors for y in b.authors), default=0)
    if authors >= 90:
        return 0.7, conflict, "même auteur"
    return 0.0, conflict, ("n° de recueil différents" if conflict else "")


# ---------------------------------------------------------------- étape 6 : score + relation

def band_of(s: float) -> str:
    return next(name for th, name in BANDS if s >= th)


def relation_of(a: V, b: V, ab: float, ba: float) -> str:
    if a.lang != b.lang and "?" not in (a.lang, b.lang):
        return "traduction_possible"
    if ab >= FULL and ba >= FULL:
        return "meme_version"
    if ab >= FULL or ba >= FULL:
        return "courte_longue"
    if max(ab, ba) >= PARTIAL:
        return "variante"
    return "different"


def score_pair(a: V, b: V, cos: float) -> dict:
    ab, ba = coverage(a, b)
    cov = max(ab, ba)
    t, inc = title_sim(a, b), incipit_sim(a, b)
    meta, conflict, meta_txt = meta_signals(a, b)
    s = (WEIGHTS["coverage"] * cov + WEIGHTS["tfidf"] * cos + WEIGHTS["incipit"] * inc
         + WEIGHTS["title"] * t + WEIGHTS["meta"] * meta)
    rules = []
    if meta == 1.0 and cov >= 0.5 and s < 0.70:
        s, _ = 0.70, rules.append("même n° de recueil → au moins probable")
    if t >= 0.99 and cov < PARTIAL and s >= 0.70:
        s, _ = 0.69, rules.append("titre identique mais texte différent → homonyme ?")
    if conflict and cov < 0.5 and s >= 0.70:
        s, _ = 0.69, rules.append("n° de recueil différents → plafonné")
    rel = relation_of(a, b, ab, ba)
    short = ""
    if rel == "courte_longue":
        short = a.id if ab >= ba else b.id
    expl = f"recouvrement {ab:.0%}→ / ←{ba:.0%}, tfidf {cos:.2f}, titre {t:.2f}, incipit {inc:.2f}"
    if meta_txt:
        expl += f", {meta_txt}"
    return {
        "coverage_lr": round(ab, 3), "coverage_rl": round(ba, 3), "tfidf_cos": round(cos, 3),
        "title_sim": round(t, 3), "incipit_sim": round(inc, 3), "meta_score": meta,
        "global_score": round(min(s, 1.0), 3), "predicted_relation": rel, "short_version_id": short,
        "rules": " ; ".join(rules), "explanation": expl,
    }


def apply_decisions(con: sqlite3.Connection, cands: pd.DataFrame) -> pd.DataFrame:
    dec = pd.read_sql("SELECT left_id, right_id, relation, decision_id FROM decision ORDER BY decision_id", con)
    cands["decision_id"] = pd.NA
    cands["human_relation"] = pd.NA
    if dec.empty:
        return cands
    last = {}
    for r in dec.itertuples():
        last[(min(r.left_id, r.right_id), max(r.left_id, r.right_id))] = (r.decision_id, r.relation)
    for i, (a, b) in enumerate(zip(cands.left_id, cands.right_id)):
        if (a, b) in last:
            cands.iat[i, cands.columns.get_loc("decision_id")] = last[(a, b)][0]
            cands.iat[i, cands.columns.get_loc("human_relation")] = last[(a, b)][1]
    return cands


def run_matching(con: sqlite3.Connection) -> pd.DataFrame:
    vs = load_versions(con)
    pairs, cos = generate_candidates(vs)
    rows = []
    for (a, b), srcs in pairs.items():
        r = {"left_id": a, "right_id": b, "level": "version", "blocking": ",".join(sorted(srcs))}
        r.update(score_pair(vs[a], vs[b], cos[(a, b)]))
        rows.append(r)
    cands = pd.DataFrame(rows).sort_values("global_score", ascending=False).reset_index(drop=True)
    cands["confidence_band"] = cands.global_score.map(band_of)
    cands.insert(0, "pair_id", [f"PA-{i + 1:06d}" for i in range(len(cands))])
    cands = apply_decisions(con, cands)
    cands.to_sql("match_candidate", con, if_exists="replace", index=False)
    con.commit()
    return cands
