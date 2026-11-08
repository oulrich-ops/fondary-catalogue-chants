import pandas as pd
from lxml import etree

from fondary.search import export_set


def _resolved():
    return pd.DataFrame({"statut": ["ok", "à vérifier", "introuvable"],
                         "fichier": ["À toi la gloire.xml", "Louange/Ce feu en moi.xml", "x.xml"]})


def _groups(path):
    root = etree.parse(str(path)).getroot()
    assert root.tag == "set"
    return [(g.get("name"), g.get("path"), g.get("type")) for g in root.iter("slide_group")]


def test_set_basic(tmp_path):
    p = export_set(_resolved(), "Culte 15/11", tmp_path)
    assert p.name == "Culte 15-11"  # caractères interdits remplacés, pas d'extension (format OpenSong)
    assert _groups(p) == [("À toi la gloire.xml", "", "song"), ("Ce feu en moi.xml", "Louange/", "song")]


def test_set_subfolder_and_no_extension(tmp_path):
    p = export_set(_resolved(), "Culte", tmp_path, songs_subfolder="Chants XML", strip_extension=True)
    assert _groups(p) == [("À toi la gloire", "Chants XML/", "song"),
                          ("Ce feu en moi", "Chants XML/Louange/", "song")]
