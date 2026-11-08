import pandas as pd

from fondary.canonical import _join, canonical_title, describe
from fondary.clustering import Groups, cluster_songs
from fondary.normalize import clean_title_display


def test_clean_title_display():
    assert clean_title_display("JEM 079 A toi la gloire") == "A toi la gloire"
    assert clean_title_display("A celui qui nous aime (JEM 57)") == "A celui qui nous aime"
    assert clean_title_display("Ailes de la foi 012 Psaumes 42") == "Psaumes 42"
    assert clean_title_display("CC323 C'est Jésus") == "C'est Jésus"
    assert clean_title_display("Paix profonde (1)") == "Paix profonde"
    assert clean_title_display("PAIX PROFONDE - copie") == "PAIX PROFONDE"
    assert clean_title_display("Amazing Grace (anglais)") == "Amazing Grace"


def test_canonical_title_prefers_accents_and_collects_alts():
    title, alts = canonical_title(["JEM 079 A toi la gloire", "A toi la gloire", "À toi la gloire",
                                   "Toi, lumière du matin"])
    assert title == "À toi la gloire"
    assert alts == ["Toi, lumière du matin"]


def test_verse_list_wording():
    assert _join([1]) == "couplet 1"
    assert _join([1, 3]) == "couplets 1 et 3"
    assert _join([1, 2, 3]) == "couplets 1 à 3"


def _secs(kinds, texts):
    return pd.DataFrame({"kind": kinds, "text_normalized": texts})


def test_describe_short_version():
    ref = _secs(["couplet", "refrain", "couplet", "couplet"], ["aaa un", "refrain x", "bbb deux", "ccc trois"])
    v = _secs(["couplet", "refrain", "couplet"], ["aaa un", "refrain x", "ccc trois"])
    assert describe(v, ref, 1.0, 0.7, True) == ("courte", "courte", "couplets 1 et 3 + refrain")


def test_describe_translation():
    v = _secs(["couplet", "couplet"], ["x", "y"])
    assert describe(v, v, 0.0, 0.0, False)[0] == "traduction"


def _cands(rows):
    return pd.DataFrame(rows, columns=["left_id", "right_id", "global_score", "predicted_relation", "human_relation"])


VERS = pd.DataFrame({"version_id": ["A", "B", "C", "D"], "n_files": 1, "n_sections": 3, "language": "fr"})


def test_chain_guard():
    # A~B et B~C forts, mais A et C sans lien : C ne doit pas rejoindre {A, B} par simple chaînage...
    c = _cands([("A", "B", 0.95, "variante", None), ("B", "C", 0.75, "variante", None)])
    groups, _, _ = cluster_songs(VERS, c)
    assert {"A", "B"} in groups and {"C"} in groups
    # ...mais le rejoint si A~C est aussi lié
    c = _cands([("A", "B", 0.95, "variante", None), ("B", "C", 0.75, "variante", None),
                ("A", "C", 0.6, "variante", None)])
    groups, _, _ = cluster_songs(VERS, c)
    assert {"A", "B", "C"} in groups


def test_human_decisions_win():
    c = _cands([("A", "B", 0.99, "meme_version", "different"), ("C", "D", 0.10, "different", "variante")])
    groups, _, _ = cluster_songs(VERS, c)
    assert {"A"} in groups and {"B"} in groups and {"C", "D"} in groups


def test_cannot_link_blocks_forced_merge():
    g = Groups(["A", "B"], {}, {frozenset(("A", "B"))})
    assert not g.try_merge("A", "B", forced=True)
    assert g.conflicts == [("A", "B")]
