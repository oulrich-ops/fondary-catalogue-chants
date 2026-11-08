from fondary.normalize import comparison_key, normalize_title, parse_lyrics


def test_comparison_key():
    assert comparison_key("À Toi La Gloire, ô ressuscité !") == "a toi la gloire o ressuscite"
    assert comparison_key("J’ai soif de ta présence") == "j ai soif de ta presence"
    assert comparison_key("Cœur") == "coeur"


def test_title_collection_and_hints():
    t = normalize_title("A toi la gloire  (JEM 79)")
    assert (t.key, t.collection, t.collection_number) == ("a toi la gloire", "JEM", "79")
    t = normalize_title("Ailes de la foi 015 O mon Dieu")
    assert (t.key, t.collection, t.collection_number) == ("o mon dieu", "AILES", "15")
    t = normalize_title("CC323 C'est Jésus quand je chancelle")
    assert t.collection == "CC" and t.key == "c est jesus quand je chancelle"
    t = normalize_title("Sur le chemin (version courte)")
    assert t.key == "sur le chemin" and "courte" in t.hints
    t = normalize_title("Paix profonde (1)")
    assert t.key == "paix profonde" and "copie" in t.hints
    # « jem » dans un mot ne doit pas être pris pour un recueil
    assert normalize_title("Je m'abandonne").collection is None


def test_sections_and_chorus_dedup():
    raw = "[V1]\n Lumière du matin\n[C]\n Alléluia, gloire\n[V2]\n Deuxième couplet\n[C]\n Alléluia, gloire\n"
    ly = parse_lyrics(raw)
    assert [s.label for s in ly.sections] == ["V1", "C", "V2"]
    assert ly.raw_section_count == 4
    assert ly.incipit == "Lumière du matin" and ly.chorus_incipit == "Alléluia, gloire"


def test_chords_comments_repeats_removed():
    # « | » = saut de ligne OpenSong, « _ » = liaison de syllabe sous un accord
    raw = "[V1]\n.C   G\n Gloire à Dieu [x2]\n;note\n Jé_sus|vit\n"
    ly = parse_lyrics(raw)
    assert ly.has_chords and ly.has_comments
    assert ly.sections[0].text_key == "gloire a dieu jesus vit"
    assert ly.sections[0].has_repeat


def test_numbered_verses_split():
    raw = "[V]\n1 Premier couplet\n2 Deuxième couplet\n3 Troisième\n"
    ly = parse_lyrics(raw)
    assert ly.numbered_split
    assert [s.label for s in ly.sections] == ["V1", "V2", "V3"]


def test_bracket_lyrics_and_repeat_markers():
    raw = "[V1]\n Le royaume\n[x2]\n[Dieu nous remplit de son Esprit]\n[3]\n Troisième\n"
    ly = parse_lyrics(raw)
    assert [s.label for s in ly.sections] == ["V1", "V3"]
    assert "dieu nous remplit" in ly.sections[0].text_key
    assert ly.sections[0].has_repeat


def test_instruction_lines_dropped():
    ly = parse_lyrics("[V1]\n Couplet un\nREF\n")
    assert ly.sections[0].text_key == "couplet un"


def test_psalm_number_kept():
    assert normalize_title("Ailes de la foi 012 Psaumes 42").key == "psaumes 42"


def test_inline_refrain_label_and_verse_numbers():
    raw = " 1. C'est vers toi\n[V1]\n Refrain:\n Seigneur, ô Seigneur\n[V2]\n 2. Mes yeux\n"
    ly = parse_lyrics(raw)
    assert [s.kind for s in ly.sections] == ["couplet", "refrain", "couplet"]
    assert ly.sections[0].text_key == "c est vers toi"
    assert ly.sections[1].text_key == "seigneur o seigneur"
    assert ly.chorus_incipit == "Seigneur, ô Seigneur"


def test_inline_choeur_without_markers():
    raw = " 1. Premier couplet\n Choeur :\n A toi la gloire\n 2. Second couplet\n"
    ly = parse_lyrics(raw)
    assert [s.kind for s in ly.sections] == ["couplet", "refrain", "couplet"]
    assert ly.incipit == "Premier couplet"
    assert ly.sections[2].text_key == "second couplet"


def test_zero_is_not_a_verse_number():
    ly = parse_lyrics("[V1]\n1 0 MON DIEU\n suite\n2 deuxième\n")
    assert [s.label for s in ly.sections] == ["V1", "V2"]
    assert ly.sections[0].text_key.startswith("0 mon dieu")


def test_no_markers_single_section():
    ly = parse_lyrics(" Une ligne\n Deux lignes\n")
    assert len(ly.sections) == 1 and not ly.has_markers
