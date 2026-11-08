# Fondary · Catalogue des chants OpenSong

**Retrouver le bon chant, dans la bonne version, sans ouvrir dix fichiers.**

La bibliothèque OpenSong contient 5 284 fichiers, avec des doublons (`Paix profonde`, `paix profonde (1)`…), des chants retitrés et des versions courtes ou longues. L'outil les range en **chants** et en **versions**, puis prépare le **set** d'un culte à partir d'une simple liste.

OpenSong n'est jamais modifié : l'outil lit les chants et écrit seulement des sets.

## Résultats

| | |
|---|---|
| Fichiers lus | 5 284 |
| Chants identifiés | 2 991 |
| Fiabilité des regroupements | 96 % (vérifiée sur 300 cas) |
| Set généré puis ouvert dans OpenSong | ✅ |

## Comment ça marche

```
Fichiers OpenSong ──► Lire et nettoyer ──► Comparer ──► Regrouper en chants ──► Vérifier (humain)
                                                                                     │
Set OpenSong ◄──────── Retrouver chaque chant ◄──── Liste du culte ◄──── Catalogue ◄─┘
```

On colle la liste du culte, un chant par ligne, même avec des fautes (« a toi la glore »). L'outil retrouve chaque chant, choisit la version et écrit le set.

## Démarrer

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

Ouvrir **`00_PILOTAGE_COMMENCER_ICI.ipynb`** dans VS Code et exécuter les cellules dans l'ordre.
Les chants sont attendus dans `chant_xml/Chants XML/`. Ce dossier n'est pas publié, car les paroles sont soumises au droit d'auteur.

## Outils

| Outil | Rôle |
|---|---|
| Python, pandas | Langage et manipulation des données |
| lxml | Lecture des fichiers OpenSong |
| unidecode, lingua | Suppression des accents, détection de la langue |
| rapidfuzz, scikit-learn | Comparaison des textes malgré les fautes |
| SQLite | Base du catalogue, en un seul fichier |
| openpyxl | Fichiers Excel (rapports, vérification) |
| Jupyter, pytest | Notebook de pilotage, tests |

## Prochaine étape

Une application simple pour l'équipe de projection, avec trois écrans :
- **Chercher** un chant ;
- **Préparer un culte**, avec le choix de la version ;
- **Vérifier** les cas douteux.
