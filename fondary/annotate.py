"""Jeu de référence : export d'un échantillon de paires à annoter, puis réimport en décisions."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

LABELS = ["meme_version", "courte_longue", "variante", "traduction", "different", "?"]
QUOTAS = {"tres_forte": 60, "probable": 90, "incertaine": 90, "rejet": 60}


def _version_text(con: sqlite3.Connection) -> dict[str, str]:
    q = ("SELECT v.version_id, s.label, s.text_display FROM song_version v "
         "JOIN section s ON s.file_id = v.preferred_file_id ORDER BY v.version_id, s.position")
    out: dict[str, list[str]] = {}
    for vid, label, text in con.execute(q):
        out.setdefault(vid, []).append(f"[{label}]\n{text}")
    return {k: "\n\n".join(v) for k, v in out.items()}


def export_sample(con: sqlite3.Connection, path: Path, seed: int = 42) -> int:
    c = pd.read_sql("SELECT * FROM match_candidate WHERE decision_id IS NULL", con)
    parts = []
    for band, n in QUOTAS.items():
        g = c[c.confidence_band == band]
        if band == "rejet":  # la zone utile du rejet est juste sous le seuil
            g = g[g.global_score >= 0.35]
        parts.append(g.sample(min(n, len(g)), random_state=seed))
    s = pd.concat(parts).sample(frac=1, random_state=seed)  # mélange : l'annotateur ne voit pas la bande d'abord

    v = pd.read_sql("SELECT version_id, title, n_files, collections, authors FROM song_version", con).set_index("version_id")
    f = pd.read_sql("SELECT fv.version_id, sf.path FROM file_version fv JOIN source_file sf USING(file_id) "
                    "WHERE fv.is_preferred_file", con).set_index("version_id").path
    texts = _version_text(con)
    rows = []
    for r in s.itertuples():
        rows.append({
            "label_humain": "", "commentaire": "",
            "left_id": r.left_id, "right_id": r.right_id,
            "titre_A": v.at[r.left_id, "title"], "titre_B": v.at[r.right_id, "title"],
            "texte_A": texts.get(r.left_id, ""), "texte_B": texts.get(r.right_id, ""),
            "fichier_A": f.get(r.left_id, ""), "fichier_B": f.get(r.right_id, ""),
            "recueil_A": v.at[r.left_id, "collections"], "recueil_B": v.at[r.right_id, "collections"],
            "auteur_A": v.at[r.left_id, "authors"], "auteur_B": v.at[r.right_id, "authors"],
            "score": r.global_score, "bande": r.confidence_band, "relation_proposee": r.predicted_relation,
            "explication": r.explanation, "regles": r.rules,
        })
    df = pd.DataFrame(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(path, index=False, sheet_name="paires")

    wb = load_workbook(path)
    ws = wb["paires"]
    widths = {"A": 16, "B": 25, "C": 10, "D": 10, "E": 28, "F": 28, "G": 55, "H": 55}
    for col, w in widths.items():
        ws.column_dimensions[col].width = w
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    for cell in ws[1]:
        cell.font = Font(bold=True)
    ws["A1"].fill = PatternFill("solid", fgColor="FFF2CC")
    ws.freeze_panes = "C2"
    dv = DataValidation(type="list", formula1='"' + ",".join(LABELS) + '"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(f"A2:A{ws.max_row}")

    guide = wb.create_sheet("consignes")
    for line in [
        ["label_humain", "Signification"],
        ["meme_version", "Mêmes paroles projetées (fautes, ponctuation, ordre des sections ignorés)"],
        ["courte_longue", "Même chant, l'un a des couplets en plus ou en moins"],
        ["variante", "Même chant, texte partiellement réécrit ou autre choix de couplets"],
        ["traduction", "Même chant dans une autre langue (traduction fidèle)"],
        ["different", "Chants différents (même si titre ou première ligne proches)"],
        ["?", "Je ne sais pas : laisser de côté"],
        [],
        ["Astuce", "Les colonnes score / bande / relation_proposee sont à droite : remplir label_humain AVANT de les regarder."],
    ]:
        guide.append(line)
    guide.column_dimensions["A"].width = 16
    guide.column_dimensions["B"].width = 90
    wb.save(path)
    return len(df)


def import_annotations(con: sqlite3.Connection, path: Path, author: str) -> tuple[int, int]:
    df = pd.read_excel(path, sheet_name="paires", dtype=str).fillna("")
    df = df[df.label_humain.str.strip() != ""]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ok = skipped = 0
    for r in df.itertuples():
        label = r.label_humain.strip()
        if label not in LABELS or label == "?":
            skipped += 1
            continue
        (a, pa), (b, pb) = sorted([(r.left_id, r.fichier_A), (r.right_id, r.fichier_B)])
        con.execute(
            "INSERT INTO decision (action, left_id, right_id, relation, author, created_at, comment, left_path, right_path) "
            "VALUES ('annoter', ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(left_id, right_id, action) DO UPDATE SET relation=excluded.relation, "
            "author=excluded.author, created_at=excluded.created_at, comment=excluded.comment, "
            "left_path=excluded.left_path, right_path=excluded.right_path",
            (a, b, label, author, now, r.commentaire, pa, pb))
        ok += 1
    con.commit()
    return ok, skipped
