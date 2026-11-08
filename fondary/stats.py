"""Rapport de qualité et statistiques du corpus (étape 1 du plan)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def _pct(n: int, d: int) -> str:
    return f"{n} ({100 * n / d:.1f} %)" if d else "0"


def _table(df: pd.DataFrame) -> str:
    return df.to_markdown(index=False) if not df.empty else "_aucun_"


def build_report(files: pd.DataFrame, sections: pd.DataFrame, root: Path) -> tuple[str, dict[str, pd.DataFrame]]:
    total = len(files)
    songs = files[files.kind == "song"].copy()
    n = len(songs)
    sheets: dict[str, pd.DataFrame] = {}
    out: list[str] = [f"# Rapport d'extraction OpenSong\n\nDossier : `{root}`\n"]

    # ---- Volumes
    out.append("## 1. Volumes\n")
    out.append(f"- Fichiers trouvés : **{total}**")
    out.append(f"- Chants lus : **{n}**")
    out.append(f"- Hors chants : {_pct((files.kind == 'not_song').sum(), total)}")
    out.append(f"- Erreurs de lecture : {_pct((files.kind == 'error').sum(), total)}")
    out.append(f"- Chants sans extension `.xml` (format OpenSong natif) : {(~songs.has_xml_ext).sum()}")
    enc = songs.encoding.value_counts()
    out.append(f"- Encodages : " + ", ".join(f"{k} = {v}" for k, v in enc.items()) + "\n")
    rejected = files[files.kind != "song"][["path", "kind", "error"]]
    sheets["hors_chants_erreurs"] = rejected
    out.append("### Fichiers écartés\n\n" + _table(rejected) + "\n")

    # ---- Qualité
    out.append("## 2. Qualité des chants\n")
    empty = songs[songs.n_sections == 0]
    no_title = songs[songs.raw_title.str.strip() == ""]
    no_marker = songs[(~songs.has_markers) & (songs.n_sections > 0)]
    upper = songs[songs.uppercase_ratio > 0.7]
    out.append(f"- Sans paroles : {_pct(len(empty), n)}")
    out.append(f"- Sans titre (titre déduit du nom de fichier) : {_pct(len(no_title), n)}")
    out.append(f"- Paroles sans marqueurs de section : {_pct(len(no_marker), n)}")
    out.append(f"- Paroles en MAJUSCULES (> 70 %) : {_pct(len(upper), n)}")
    out.append(f"- Avec accords : {_pct(songs.has_chords.sum(), n)}")
    out.append(f"- Avec commentaires `;` : {_pct(songs.has_comments.sum(), n)}")
    out.append(f"- Couplets numérotés éclatés : {_pct(songs.numbered_split.sum(), n)}")
    out.append(f"- Avec sections répétées (refrain réécrit) : {_pct((songs.n_sections_raw > songs.n_sections).sum(), n)}\n")
    sheets["sans_paroles"] = empty[["file_id", "path", "raw_title"]]
    sheets["sans_marqueurs"] = no_marker[["file_id", "path", "raw_title", "n_chars"]]

    # ---- Métadonnées
    out.append("## 3. Taux de remplissage des métadonnées\n")
    meta_cols = [c for c in songs.columns if c.startswith("meta_")]
    fill = pd.DataFrame({
        "champ": [c.removeprefix("meta_") for c in meta_cols],
        "renseigné": [(songs[c] != "").sum() for c in meta_cols],
    })
    fill["%"] = (100 * fill["renseigné"] / n).round(1)
    out.append(_table(fill.sort_values("renseigné", ascending=False)) + "\n")
    ck = songs.ccli_kind.value_counts().rename_axis("contenu du champ ccli").reset_index(name="fichiers")
    out.append("**Ce que contient vraiment le champ `ccli`** :\n\n" + _table(ck) + "\n")
    top_authors = songs[songs.meta_author != ""].meta_author.value_counts().head(15)
    out.append("**Auteurs les plus fréquents** :\n\n" + _table(top_authors.rename_axis("auteur").reset_index(name="fichiers")) + "\n")

    # ---- Recueils
    out.append("## 4. Recueils détectés dans les titres\n")
    coll = songs.collection.fillna("(aucun)").value_counts().rename_axis("recueil").reset_index(name="fichiers")
    out.append(_table(coll) + "\n")
    with_num = songs.dropna(subset=["collection_number"])
    dup_num = with_num.groupby(["collection", "collection_number"]).size()
    out.append(f"- Numéros de recueil présents plusieurs fois : {(dup_num > 1).sum()} "
               f"(couvrant {dup_num[dup_num > 1].sum()} fichiers)\n")

    # ---- Langues
    out.append("## 5. Langues détectées\n")
    lang = songs.language.value_counts().rename_axis("langue").reset_index(name="fichiers")
    lang["%"] = (100 * lang.fichiers / n).round(1)
    out.append(_table(lang) + "\n")
    out.append("`?` = confiance < 0,6 : texte trop court, bilingue ou langue non couverte (mooré, dioula…).\n")
    sheets["langue_incertaine"] = songs[songs.language == "?"][["file_id", "path", "raw_title", "incipit", "language_conf"]]

    # ---- Structure
    out.append("## 6. Structure des chants\n")
    desc = songs[songs.n_sections > 0][["n_sections", "n_verses", "n_chars"]].describe().round(1)
    out.append(desc.reset_index().rename(columns={"index": "stat"}).to_markdown(index=False) + "\n")
    out.append(f"- Avec refrain : {_pct(songs.has_chorus.sum(), n)}")
    out.append(f"- Avec pont : {_pct(songs.has_bridge.sum(), n)}\n")
    if not sections.empty:
        kinds = sections.kind.value_counts().rename_axis("type de section").reset_index(name="sections")
        out.append(_table(kinds) + "\n")
        labels = sections[sections.kind == "autre"].label.value_counts().head(20)
        if len(labels):
            out.append("**Marqueurs non reconnus (à ajouter au lexique)** :\n\n"
                       + _table(labels.rename_axis("marqueur").reset_index(name="sections")) + "\n")
        short = sections[sections.text_normalized.str.split().str.len() <= 4]
        out.append(f"- Sections très courtes (≤ 4 mots, risque de faux positifs type « Alléluia ») : {len(short)}\n")

    # ---- Doublons
    out.append("## 7. Premiers signaux de doublons\n")
    s = songs[songs.n_sections > 0]
    fh = s.groupby("file_hash").filter(lambda g: len(g) > 1)
    ch = s.groupby("content_hash").filter(lambda g: len(g) > 1)
    tk = s[s.title_key != ""].groupby("title_key").filter(lambda g: len(g) > 1)
    n_versions_exact = s.content_hash.nunique()
    out.append(f"- Copies binaires strictes (même `file_hash`) : {fh.file_hash.nunique()} groupes, {len(fh)} fichiers")
    out.append(f"- Doublons de texte exacts après normalisation (même `content_hash`) : "
               f"{ch.content_hash.nunique()} groupes, {len(ch)} fichiers")
    out.append(f"- → **{len(s)} chants avec paroles se réduisent à {n_versions_exact} textes distincts** "
               f"(gain {100 * (1 - n_versions_exact / max(len(s), 1)):.1f} % avant tout calcul flou)")
    out.append(f"- Titres normalisés identiques : {tk.title_key.nunique()} groupes, {len(tk)} fichiers "
               f"(candidats : doublons, versions ou homonymes)\n")
    sheets["doublons_exacts"] = ch.sort_values(["content_hash", "path"])[["content_hash", "file_id", "path", "raw_title", "meta_key", "structure"]]
    sheets["memes_titres"] = tk.sort_values(["title_key", "path"])[["title_key", "file_id", "path", "raw_title", "collection", "collection_number", "n_sections", "content_hash", "incipit"]]
    top_titles = tk.groupby("title_key").size().sort_values(ascending=False).head(15)
    out.append("**Titres les plus dupliqués** :\n\n" + _table(top_titles.rename_axis("titre normalisé").reset_index(name="fichiers")) + "\n")

    sheets["chants"] = songs.drop(columns=["raw_lyrics", "raw_meta"])
    return "\n".join(out), sheets


def write_outputs(report: str, sheets: dict[str, pd.DataFrame], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "rapport_extraction.md").write_text(report, encoding="utf-8")
    target = out_dir / "rapport_extraction.xlsx"
    try:
        target.open("ab").close()
    except PermissionError:  # fichier ouvert dans Excel
        from datetime import datetime
        target = out_dir / f"rapport_extraction_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
        print(f"⚠ rapport_extraction.xlsx est ouvert ailleurs : écriture dans {target.name}")
    with pd.ExcelWriter(target) as xw:
        for name, df in sheets.items():
            df.to_excel(xw, sheet_name=name[:31], index=False)
