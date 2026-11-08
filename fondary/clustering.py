"""Étape 7 : regroupement des versions en chants (et des quasi-doublons en une même version).

Principe
- Les décisions humaines passent d'abord : « même chant » = doit être lié, « different » = ne doit pas.
- Puis les liens machine, du plus fort au plus faible (score >= SONG_LINK).
- Garde-fou contre l'effet de chaîne (A~B, B~C mais A≁C) : deux groupes ne fusionnent que si
  au moins COHESION_MIN de leurs paires croisées sont elles-mêmes liées (score >= LINKED).
- Identifiants CH-xxxxx stables : chaque groupe reprend l'identifiant du chant précédent avec
  lequel il partage le plus de versions ; un identifiant qui disparaît devient « fusionné » avec
  une redirection (merged_into).
"""
from __future__ import annotations

import sqlite3
from collections import Counter
from datetime import datetime, timezone

import pandas as pd

SONG_LINK = 0.65        # score minimal d'un lien machine « même chant » (= début de la bande « probable »)
LINKED = 0.50           # une paire croisée compte comme liée au-dessus de ce score
COHESION_MIN = 0.50     # il faut PLUS de 50 % de paires croisées liées pour fusionner deux groupes
SAME_SONG = {"meme_version", "courte_longue", "variante", "traduction"}

DDL = [
    """CREATE TABLE IF NOT EXISTS song_registry (
        song_id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
        status TEXT NOT NULL, merged_into TEXT)""",
    """CREATE TABLE IF NOT EXISTS song_assignment (
        version_id TEXT PRIMARY KEY, song_id TEXT NOT NULL)""",
]


class Groups:
    """Union-find avec garde-fou de cohésion et contraintes « ne doit pas être lié »."""

    def __init__(self, ids, score: dict, cannot: set):
        self.members = {i: {i} for i in ids}
        self.of = {i: i for i in ids}
        self.score, self.cannot = score, cannot
        self.conflicts: list[tuple[str, str]] = []

    def sc(self, a: str, b: str) -> float:
        return self.score.get((a, b) if a < b else (b, a), 0.0)

    def try_merge(self, a: str, b: str, forced: bool) -> bool:
        ga, gb = self.of[a], self.of[b]
        if ga == gb:
            return False
        A, B = self.members[ga], self.members[gb]
        if any(frozenset((x, y)) in self.cannot for x in A for y in B):
            if forced:
                self.conflicts.append((a, b))
            return False
        if not forced:
            cross = [self.sc(x, y) >= LINKED for x in A for y in B]
            if sum(cross) / len(cross) <= COHESION_MIN:  # majorité stricte : bloque A~B~C quand A≁C
                return False
        if len(A) < len(B):
            ga, gb, A, B = gb, ga, B, A
        A |= B
        for x in B:
            self.of[x] = ga
        del self.members[gb]
        return True

    def groups(self) -> list[set[str]]:
        return sorted(self.members.values(), key=min)


def _load(con):
    versions = pd.read_sql("SELECT version_id, n_files, n_sections, language FROM song_version", con)
    c = pd.read_sql("SELECT left_id, right_id, global_score, predicted_relation, coverage_lr, coverage_rl, "
                    "human_relation FROM match_candidate ORDER BY global_score DESC, left_id, right_id", con)
    return versions, c


def cluster_songs(versions: pd.DataFrame, c: pd.DataFrame) -> tuple[list[set[str]], dict, list]:
    score = {(a, b): s for a, b, s in zip(c.left_id, c.right_id, c.global_score)}
    human = c.dropna(subset=["human_relation"])
    cannot = {frozenset((a, b)) for a, b, h in zip(human.left_id, human.right_id, human.human_relation)
              if h == "different"}
    g = Groups(versions.version_id, score, cannot)
    for a, b, h in zip(human.left_id, human.right_id, human.human_relation):
        if h in SAME_SONG:
            g.try_merge(a, b, forced=True)
    machine = c[c.human_relation.isna() & (c.global_score >= SONG_LINK) & (c.predicted_relation != "different")]
    for a, b in zip(machine.left_id, machine.right_id):  # déjà triées par score décroissant
        g.try_merge(a, b, forced=False)
    return g.groups(), score, g.conflicts


def cluster_version_groups(songs: list[set[str]], versions: pd.DataFrame, c: pd.DataFrame) -> dict[str, str]:
    """Dans chaque chant, regroupe les quasi-doublons (fautes, ponctuation) en une même version.

    Retourne {version_id: representative_id}.
    """
    song_of = {v: i for i, s in enumerate(songs) for v in s}
    same = c[c.left_id.map(song_of) == c.right_id.map(song_of)]
    human_same = same.human_relation == "meme_version"
    machine_same = same.human_relation.isna() & (same.predicted_relation == "meme_version") & (same.global_score >= SONG_LINK)
    cannot = {frozenset((a, b)) for a, b, h in zip(same.left_id, same.right_id, same.human_relation)
              if pd.notna(h) and h != "meme_version"}
    score = {(a, b): 1.0 for a, b in zip(same[machine_same | human_same].left_id, same[machine_same | human_same].right_id)}
    g = Groups(versions.version_id, score, cannot)
    for a, b in zip(same[human_same].left_id, same[human_same].right_id):
        g.try_merge(a, b, forced=True)
    for a, b in zip(same[machine_same].left_id, same[machine_same].right_id):
        g.try_merge(a, b, forced=False)
    info = versions.set_index("version_id")
    rep = {}
    for grp in g.groups():
        # représentant : la version la plus répandue (plus de fichiers), puis la plus complète
        r = sorted(grp, key=lambda v: (-info.at[v, "n_files"], -info.at[v, "n_sections"], v))[0]
        for v in grp:
            rep[v] = r
    return rep


def assign_song_ids(con: sqlite3.Connection, songs: list[set[str]]) -> tuple[list[str], dict[str, str]]:
    """Donne à chaque groupe un CH-xxxxx stable. Retourne (ids alignés sur songs, redirections)."""
    for ddl in DDL:
        con.execute(ddl)
    prev = dict(con.execute("SELECT version_id, song_id FROM song_assignment"))
    reg = dict(con.execute("SELECT song_id, status FROM song_registry"))
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # appariement glouton groupe <-> ancien identifiant, par nombre de versions partagées
    options = []
    for i, s in enumerate(songs):
        for old, n in Counter(prev[v] for v in s if v in prev).items():
            options.append((-n, old, i))
    ids: list[str | None] = [None] * len(songs)
    used = set()
    for _, old, i in sorted(options):
        if ids[i] is None and old not in used and reg.get(old) != "fusionne":
            ids[i], _ = old, used.add(old)

    last = max((int(k.split("-")[1]) for k in reg), default=0)
    for i in range(len(songs)):
        if ids[i] is None:
            last += 1
            ids[i] = f"CH-{last:05d}"
            con.execute("INSERT INTO song_registry VALUES (?, ?, 'propose', NULL)", (ids[i], now))
            reg[ids[i]] = "propose"

    # anciens identifiants disparus -> fusionnés, redirigés vers le chant qui a repris leurs versions
    new_of = {v: ids[i] for i, s in enumerate(songs) for v in s}
    redirects = {}
    for old, status in reg.items():
        if old in used or old in ids or status in ("fusionne", "supprime"):
            continue
        targets = Counter(new_of[v] for v, s in prev.items() if s == old and v in new_of)
        if targets:
            target = targets.most_common(1)[0][0]
            redirects[old] = target
            con.execute("UPDATE song_registry SET status='fusionne', merged_into=? WHERE song_id=?", (target, old))
        else:  # plus aucune de ses versions n'existe (fichiers supprimés)
            con.execute("UPDATE song_registry SET status='supprime' WHERE song_id=?", (old,))
    con.execute("DELETE FROM song_assignment")
    con.executemany("INSERT INTO song_assignment VALUES (?, ?)", list(new_of.items()))
    con.commit()
    return ids, redirects
