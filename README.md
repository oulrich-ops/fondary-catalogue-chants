# Fondary · Catalogue des chants OpenSong

Retrouver **le bon chant, dans la bonne version, sans ouvrir dix fichiers.**

Une bibliothèque OpenSong accumule au fil des années des doublons (`Paix profonde`, `paix profonde (1)`, `PAIX PROFONDE - copie`), des chants retitrés, des versions courtes ou longues, des traductions. Ce projet lit tous les fichiers et range chaque chant sur trois niveaux :

| Niveau | Question | Exemple |
|---|---|---|
| **Chant** `CH-00218` | De quel chant parle-t-on ? | *Ô grâce infinie* |
| **Version** `CH-00218.fr.courte` | Quelles paroles exactes ? | FR · courte — couplets 1 et 3 |
| **Fichier** | Quel fichier ouvrir ? | `Ô grâce infinie.xml` |

- **Doublon** = plusieurs fichiers pour une même version.
- **Variante** = plusieurs versions pour un même chant.

**OpenSong n'est jamais modifié.** Le catalogue est une couche au-dessus. Le seul fichier produit pour OpenSong est un *set* (liste de chants d'un culte), créé comme un nouveau fichier.

---

## Démarrer

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

Ouvrez ensuite **`00_PILOTAGE_COMMENCER_ICI.ipynb`** dans VS Code, choisissez le noyau `.venv` et exécutez les cellules dans l'ordre (**Maj + Entrée**). Tout y est : traitement, recherche, préparation d'un culte, annotation.

Le dossier des chants est attendu dans `chant_xml/Chants XML/`. Il n'est **pas** inclus dans le dépôt, car les paroles sont soumises au droit d'auteur. Indiquez un autre chemin dans la variable `SOURCE` du notebook si besoin.

---

## Comment ça marche

```
Fichiers OpenSong ──► 1. Lire ──► 2. Nettoyer ──► 3. Doublons exacts ──► 4. Candidats ──► 5-6. Score
   (lecture seule)                                                                            │
                                                                                              ▼
   Set OpenSong ◄── 10. Recherche ◄── 9. Catalogue ◄── 8. Validation humaine ◄── 7. Regroupement
```

1. **Lire** chaque fichier XML, sans jamais l'écrire.
2. **Nettoyer** : découper en couplets et refrain, retirer accords et « (bis) », extraire le recueil du titre (`JEM 079`), produire une clé sans accents ni ponctuation.
3. **Doublons exacts** : les fichiers aux paroles identiques forment une seule version.
4. **Candidats** : seules les paires plausibles sont comparées (même titre, même recueil, voisins TF-IDF), soit environ 17 000 au lieu de 9,4 millions.
5. **Signaux** : part des lignes de A retrouvées dans B et inversement, similarité globale, titre, première ligne, recueil, auteur.
6. **Score** de 0 à 1, bande de confiance (très forte, probable, incertaine, rejet) et relation proposée (même version, courte/longue, variante, traduction, différent).
7. **Regroupement** en chants, avec un garde-fou contre les chaînes (A ressemble à B, B à C, mais A pas à C).
8. **Validation humaine** : chaque décision est enregistrée et réappliquée à chaque relance.
9. **Catalogue** : titre canonique, version de référence, codes et libellés de version stables.
10. **Recherche** tolérante aux fautes, fiche chant, liste de célébration vers set OpenSong.

Le traitement est **rejouable** : on peut ajouter des fichiers ou améliorer l'algorithme et relancer, sans perdre aucune décision. Les identifiants `CH-` et `VE-` ne sont jamais réattribués, et une fusion laisse une redirection.

---

## Outils utilisés

| Outil | Rôle dans le projet |
|---|---|
| **Python 3.12** | Langage du projet |
| **lxml** | Lecture tolérante des fichiers XML OpenSong, même mal formés |
| **charset-normalizer** | Détection de l'encodage des vieux fichiers non UTF-8 |
| **unidecode** | Suppression des accents pour comparer (« À toi » devient « a toi ») |
| **lingua** | Détection de la langue de chaque chant |
| **rapidfuzz** | Ressemblance entre textes malgré les fautes : titres, lignes, recherche |
| **scikit-learn** | TF-IDF sur des morceaux de 3 à 5 lettres, pour trouver vite les chants proches |
| **numpy** | Calculs sur les tableaux de scores |
| **pandas** | Manipulation des tableaux, statistiques, lecture et écriture SQLite et Excel |
| **SQLite** | Base du catalogue : un seul fichier, aucun serveur |
| **openpyxl** | Fichiers Excel (rapports, fiche d'annotation avec liste déroulante) |
| **tabulate** | Tableaux des rapports Markdown |
| **Typer** | Commandes `python -m fondary …` |
| **Jupyter** (ipykernel) | Notebook de pilotage |
| **pytest** | Tests automatiques (nettoyage, score, regroupement) |

Il n'y a aucun modèle d'IA dans cette première version : règles, similarité de texte et validation humaine suffisent pour les doublons, les versions et les retitrages. Les traductions et les cas douteux pourront bénéficier d'embeddings ou d'un LLM en V2.

---

## En ligne de commande (facultatif)

```powershell
.venv\Scripts\python -m fondary import            # 1-2  lire et nettoyer
.venv\Scripts\python -m fondary match             # 3-6  comparer
.venv\Scripts\python -m fondary catalogue         # 7, 9 chants et versions
.venv\Scripts\python -m fondary chercher "a toi la glore"
.venv\Scripts\python -m fondary set liste.txt --nom "Culte 2026-11-15"
.venv\Scripts\python -m fondary annoter-export    # paires à vérifier dans Excel
.venv\Scripts\python -m fondary annoter-import --author "Prénom"
.venv\Scripts\python -m pytest                    # tests
```

## Organisation du code

```
00_PILOTAGE_COMMENCER_ICI.ipynb   notebook de pilotage
fondary/
  opensong.py     lecture des fichiers OpenSong
  normalize.py    nettoyage des titres et des paroles
  extract.py      étapes 1-2 : extraction, langue, base SQLite
  stats.py        rapport de qualité
  catalog.py      étape 3 : versions et fichier préféré
  matching.py     étapes 4-6 : candidats, signaux, score (réglages en tête de fichier)
  clustering.py   étape 7 : regroupement en chants, identifiants stables
  canonical.py    étape 9 : titres, version de référence, codes et libellés
  search.py       étape 10 : recherche, liste de célébration, export de set
  annotate.py     jeu de référence annoté
  cli.py          commandes
tests/            tests automatiques
```

Fichiers générés, non versionnés : `data/catalogue.sqlite`, `reports/`, `annotations/`, `exports/sets/`.

## Où en est le projet

- [x] Lecture, nettoyage et rapport de qualité
- [x] Doublons exacts, candidats, score, relation
- [x] Regroupement en chants, catalogue, codes et libellés de versions
- [x] Recherche, liste de célébration, export de set OpenSong
- [ ] Annoter 200 à 300 paires et régler les seuils
- [ ] Écran de revue (valider, fusionner, séparer) pour les éditeurs du catalogue
- [ ] Tester un set exporté dans OpenSong sur un vrai culte
