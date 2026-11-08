"""Rapport des étapes 3 à 6, et évaluation sur les paires annotées quand il y en a."""
from __future__ import annotations

import pandas as pd

from .matching import BANDS


def _t(df: pd.DataFrame) -> str:
    return df.to_markdown(index=False) if not df.empty else "_aucun_"


def build_match_report(versions: pd.DataFrame, cands: pd.DataFrame, n_files: int) -> str:
    out = ["# Rapport de matching (étapes 3 à 6)\n"]

    out.append("## Étape 3 : doublons exacts → versions provisoires\n")
    multi = versions[versions.n_files > 1]
    out.append(f"- {n_files} fichiers avec paroles → **{len(versions)} versions**")
    out.append(f"- {len(multi)} versions regroupent plusieurs fichiers (jusqu'à {versions.n_files.max()})\n")

    out.append("## Étape 4 : candidats\n")
    n = len(versions)
    out.append(f"- **{len(cands)} paires candidates** sur {n * (n - 1) // 2:,} paires possibles".replace(",", " "))
    src = cands.blocking.str.split(",").explode().value_counts().rename_axis("source").reset_index(name="paires")
    out.append("\n" + _t(src) + "\n")

    out.append("## Étapes 5-6 : bandes de confiance × relation proposée\n")
    order = [b for _, b in BANDS]
    ct = pd.crosstab(cands.confidence_band, cands.predicted_relation, margins=True, margins_name="total")
    ct = ct.reindex([b for b in order if b in ct.index] + ["total"])
    out.append(ct.reset_index().rename(columns={"confidence_band": "bande"}).to_markdown(index=False) + "\n")
    out.append(f"- Règles prioritaires appliquées : {(cands.rules != '').sum()} paires\n")

    out.append("## Exemples par bande\n")
    for band in order:
        g = cands[cands.confidence_band == band].head(8)
        if band == "rejet":
            g = cands[cands.confidence_band == band].head(5)
        out.append(f"### {band}\n")
        out.append(_t(g[["left_id", "right_id", "global_score", "predicted_relation", "explanation", "rules"]]) + "\n")

    ann = cands.dropna(subset=["human_relation"])
    if len(ann):
        out.append("## Évaluation sur les paires annotées\n")
        seuil = next(th for th, name in BANDS if name == "probable")
        ann = ann.assign(meme_chant_humain=ann.human_relation != "different",
                         propose=ann.global_score >= seuil)
        tp = (ann.propose & ann.meme_chant_humain).sum()
        fp = (ann.propose & ~ann.meme_chant_humain).sum()
        fn = (~ann.propose & ann.meme_chant_humain).sum()
        prec = tp / (tp + fp) if tp + fp else 0
        rec = tp / (tp + fn) if tp + fn else 0
        out.append(f"- {len(ann)} paires annotées. Seuil « même chant » = {seuil:.2f} → "
                   f"précision **{prec:.0%}**, rappel **{rec:.0%}**\n")
        by_band = ann.groupby("confidence_band").meme_chant_humain.agg(["count", "mean"]).reset_index()
        by_band.columns = ["bande", "paires annotées", "part réellement même chant"]
        out.append(_t(by_band.round(2)) + "\n")
        rel = pd.crosstab(ann.predicted_relation, ann.human_relation).reset_index()
        out.append("**Relation proposée (lignes) vs relation humaine (colonnes)** :\n\n" + _t(rel) + "\n")
    return "\n".join(out)
