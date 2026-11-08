import numpy as np

from fondary.matching import V, band_of, coverage, relation_of, score_pair
from fondary.normalize import comparison_key


def mk(id, lines, title="t", colls=(), authors=(), lang="fr"):
    keys = [comparison_key(l) for l in lines]
    return V(id=id, title_keys=[comparison_key(title)], colls=set(colls), authors=list(authors),
             lines=keys, weights=np.array([len(k) for k in keys], dtype=np.float32),
             text_key=" ".join(keys), incipit=keys[0], chorus="", lang=lang, n_chars=sum(map(len, keys)))


COUPLETS = ["Sur le chemin de la vie je marche", "Ta main me guide chaque jour",
            "Dans la nuit tu es ma lumière", "Je chanterai ton nom Seigneur"]


def test_coverage_insensitive_to_line_breaks():
    a = mk("A", COUPLETS)
    b = mk("B", ["Sur le chemin de la vie", "je marche ta main me guide", "chaque jour dans la nuit",
                 "tu es ma lumière je chanterai", "ton nom Seigneur"])
    ab, ba = coverage(a, b)
    assert ab >= 0.9 and ba >= 0.9


def test_short_long_relation():
    short = mk("S", COUPLETS[:2])
    long_ = mk("L", COUPLETS)
    ab, ba = coverage(short, long_)
    assert ab == 1.0 and ba < 0.7
    assert relation_of(short, long_, ab, ba) == "courte_longue"
    r = score_pair(short, long_, cos=0.8)
    assert r["short_version_id"] == "S"


def test_homonym_capped():
    a = mk("A", ["Viens Esprit Saint viens", "brûle nos cœurs de ton feu"], title="Viens Esprit Saint")
    b = mk("B", ["Viens Esprit Saint viens", "Souffle sur nous ce matin", "Que ta paix règne ici", "Remplis cette maison"],
           title="Viens Esprit Saint")
    r = score_pair(a, b, cos=0.9)
    assert r["global_score"] < 0.70


def test_shared_collection_number_boosts():
    a = mk("A", COUPLETS, colls=["JEM 79"])
    b = mk("B", COUPLETS[:2] + ["Autre texte pour finir le chant", "Encore une ligne différente ici"], colls=["JEM 79"])
    r = score_pair(a, b, cos=0.5)
    assert r["meta_score"] == 1.0 and r["global_score"] >= 0.70


def test_bands():
    assert [band_of(s) for s in (0.95, 0.8, 0.6, 0.2)] == ["tres_forte", "probable", "incertaine", "rejet"]
