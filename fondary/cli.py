"""Ligne de commande : `python -m fondary import <dossier>`."""
from __future__ import annotations

import sys
from pathlib import Path

import typer

# Console Windows (cp1252) : on force l'UTF-8 pour les accents et les flèches.
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

app = typer.Typer(help="Alignement de chants OpenSong", no_args_is_help=True)

DEFAULT_SRC = Path("chant_xml/Chants XML")
DEFAULT_DB = Path("data/catalogue.sqlite")
DEFAULT_OUT = Path("reports")


@app.command("import")
def import_cmd(
    source: Path = typer.Argument(DEFAULT_SRC, help="Dossier Songs/ OpenSong (lu, jamais modifié)"),
    db: Path = typer.Option(DEFAULT_DB, help="Base SQLite produite"),
    out: Path = typer.Option(DEFAULT_OUT, help="Dossier des rapports"),
) -> None:
    """Extrait, normalise, enregistre en base et produit le rapport de qualité."""
    from .extract import extract, save_sqlite
    from .stats import build_report, write_outputs

    if not source.is_dir():
        raise typer.BadParameter(f"dossier introuvable : {source}")
    typer.echo(f"Lecture de {source} …")
    files, sections = extract(source)
    save_sqlite(files, sections, db)
    report, sheets = build_report(files, sections, source)
    write_outputs(report, sheets, out)
    typer.echo(f"{len(files)} fichiers, {len(sections)} sections → {db}")
    typer.echo(f"Rapport : {out / 'rapport_extraction.md'} et .xlsx")


@app.command()
def match(
    db: Path = typer.Option(DEFAULT_DB),
    out: Path = typer.Option(DEFAULT_OUT),
) -> None:
    """Étapes 3-6 : versions (doublons exacts), candidats, scores, relations."""
    import sqlite3

    from .catalog import build_versions
    from .match_report import build_match_report
    from .matching import run_matching

    with sqlite3.connect(db) as con:
        versions = build_versions(con)
        n_files = con.execute("SELECT COUNT(*) FROM file_version").fetchone()[0]
        typer.echo(f"{n_files} fichiers → {len(versions)} versions")
        cands = run_matching(con)
    typer.echo(f"{len(cands)} paires candidates")
    typer.echo(cands.confidence_band.value_counts().to_string())
    out.mkdir(parents=True, exist_ok=True)
    (out / "rapport_matching.md").write_text(build_match_report(versions, cands, n_files), encoding="utf-8")
    typer.echo(f"Rapport : {out / 'rapport_matching.md'}")


@app.command()
def catalogue(db: Path = typer.Option(DEFAULT_DB), out: Path = typer.Option(DEFAULT_OUT)) -> None:
    """Étapes 7 et 9 : chants (CH-…), version de référence, codes et libellés de versions."""
    import sqlite3

    from .canonical import build_catalogue, catalogue_report

    with sqlite3.connect(db) as con:
        songs, versions, extra = build_catalogue(con)
    out.mkdir(parents=True, exist_ok=True)
    (out / "rapport_catalogue.md").write_text(catalogue_report(songs, versions, extra), encoding="utf-8")
    typer.echo(f"{len(songs)} chants, {int(versions.alias_of.isna().sum())} versions → {out / 'rapport_catalogue.md'}")


@app.command()
def chercher(texte: str, n: int = 10, db: Path = typer.Option(DEFAULT_DB)) -> None:
    """Cherche un chant (titre, première ligne ou phrase des paroles)."""
    import sqlite3

    from .search import build_index, search

    with sqlite3.connect(db) as con:
        res = search(build_index(con), texte, n)
    typer.echo(res[["score", "song_id", "canonical_title", "incipit", "n_versions"]].to_string(index=False))


@app.command("set")
def make_set(
    liste: Path = typer.Argument(..., help="Fichier texte : un chant par ligne"),
    nom: str = typer.Option(..., help="Nom du set, ex. « Culte 2026-11-15 »"),
    out: Path = typer.Option(Path("exports/sets")),
    db: Path = typer.Option(DEFAULT_DB),
) -> None:
    """Liste de célébration -> set OpenSong (nouveau fichier, rien n'est modifié dans OpenSong)."""
    import sqlite3

    from .search import build_index, export_set, resolve_list

    with sqlite3.connect(db) as con:
        res = resolve_list(con, build_index(con), liste.read_text(encoding="utf-8"))
    typer.echo(res[["ligne", "statut", "chant", "version", "fichier"]].to_string(index=False))
    path = export_set(res, nom, out)
    typer.echo(f"\nSet écrit : {path}  (lignes « à vérifier » incluses, « introuvable » exclues)")


@app.command("annoter-export")
def annotate_export(
    path: Path = typer.Option(Path("annotations/paires_a_annoter.xlsx")),
    db: Path = typer.Option(DEFAULT_DB),
) -> None:
    """Exporte ~300 paires stratifiées par bande, à annoter dans Excel."""
    import sqlite3

    from .annotate import export_sample

    if path.exists():
        raise typer.BadParameter(f"{path} existe déjà : importe-le d'abord ou choisis un autre nom (--path)")
    with sqlite3.connect(db) as con:
        n = export_sample(con, path)
    typer.echo(f"{n} paires → {path}")


@app.command("annoter-import")
def annotate_import(
    path: Path = typer.Option(Path("annotations/paires_a_annoter.xlsx")),
    author: str = typer.Option(..., help="Nom de l'annotateur"),
    db: Path = typer.Option(DEFAULT_DB),
) -> None:
    """Réimporte les annotations comme décisions (relancer ensuite `match`)."""
    import sqlite3

    from .annotate import import_annotations
    from .catalog import ensure_schema

    with sqlite3.connect(db) as con:
        ensure_schema(con)
        ok, skipped = import_annotations(con, path, author)
    typer.echo(f"{ok} décisions enregistrées, {skipped} ignorées (« ? » ou libellé inconnu)")


@app.command()
def show(file_id: int, db: Path = typer.Option(DEFAULT_DB)) -> None:
    """Affiche un fichier tel que normalisé (pour vérifier le découpage)."""
    import sqlite3

    with sqlite3.connect(db) as con:
        f = con.execute("SELECT path, raw_title, title_key, title_hints, language, structure FROM source_file WHERE file_id=?", (file_id,)).fetchone()
        if not f:
            raise typer.BadParameter("file_id inconnu")
        typer.echo(f"{f[0]}\n  titre : {f[1]}  →  clé : {f[2]}  indices : {f[3]}\n  langue : {f[4]}  structure : {f[5]}\n")
        for label, kind, text in con.execute("SELECT label, kind, text_display FROM section WHERE file_id=? ORDER BY position", (file_id,)):
            typer.echo(f"[{label}] ({kind})\n{text}\n")


if __name__ == "__main__":
    app()
