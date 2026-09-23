# Versions déployées et résultats

Historique des versions du bot Lichess **Taudambot** (compte BOT sur lichess.org), de ce qui a changé
entre elles, de ce qu'on a mesuré et de ce qui reste à prouver. Tous les horaires sont en UTC.

État au **20/09/2026**.

## Résumé

| Version (tag de suivi) | Déployée | Ce qui change | Parties Lichess | Score |
|---|---|---|---|---|
| `v1-uci-launch` | 16/09/2026 (tag 19:47) | Première version : moteur alpha-beta en CPython, évaluation classique, 0,5 vCPU. Le 19/09, le conteneur passe à 1 vCPU sans changer le code | 297 | 33,7 % (84 V / 32 N / 181 D) |
| `v2-pypy-warmup` | 20/09/2026 (image `v5`, tag 15:43) | Moteur sous PyPy, chauffe du JIT, gestion de l'incrément, `move_overhead` 2000 → 1000 ms | 6 | 83,3 % (5 V / 0 N / 1 D) |

**Lecture honnête : il est trop tôt pour conclure sur la v2.** Six parties donnent un intervalle de confiance à
95 % d'environ 44 % à 97 %. Le score de la v1 mélange aussi deux configurations matérielles (voir plus bas).

Classements Lichess relevés le 20/09/2026 : **bullet 1879** (±45, 84 parties), **blitz 1786** (±46, 73 parties,
1782 juste avant les premières parties de la v2). Rapide et classique : pas de partie jouée.

## Infrastructure

- Azure Container Apps, groupe de ressources `rg-chessbot`, région France Central, profil Consumption.
- Conteneur `chessbot-lichess-bot`, un seul réplica en permanence (il doit rester connecté à Lichess).
- Image construite en local et poussée sur `acrchessbot` (le build serveur `az acr build` est bloqué sur cet
  abonnement). Procédure complète dans la section « Déploiement » du `README.md`.

| Date | Révision / image | Ressources | Changement |
|---|---|---|---|
| 16/09 | `v1-uci-launch` (révisions jusqu'à `0000003`, image `v4`) | 0,5 vCPU / 1 Gio (configuration constatée juste avant le 19/09) | Premier déploiement suivi (tag) |
| 19/09 | révision `0000004`, image `v4` | **1 vCPU / 2 Gio** | Redimensionnement, code inchangé |
| 20/09 | révision `0000005`, image `v5` | 1 vCPU / 2 Gio | Version `v2-pypy-warmup` |

L'app web (`chessbot-app`, FastAPI + front) tournait aussi sur Azure (image `chessbot:v16`). Elle a été supprimée
le 19/09/2026, du dépôt comme d'Azure : seul le bot Lichess est visé.

## v1 — `v1-uci-launch`

Le moteur est un bot alpha-beta en Python pur (`app/bots/minimax.py`) : approfondissement itératif, table de
transposition, quiescence, null move, LMR. L'évaluation est celle de `app/bots/evaluation.py` (matériel,
tables pièce/case, sécurité du roi). Il parle UCI à lichess-bot via `app/uci.py`.

**Résultat** : 297 parties, 33,7 % de score.

**Limite** : cette version couvre deux configurations. Jusqu'au 19/09 le moteur tournait sur un demi-cœur, où il
allait à peu près deux fois moins vite (configuration constatée juste avant le 19/09 ; je n'ai pas vérifié les
toutes premières révisions). Comme la recherche est limitée par le temps réel, cela lui faisait
perdre environ un demi-coup à un coup de profondeur. Le tag `v1-uci-launch` n'a pas été recréé lors du
redimensionnement, donc les 297 parties mélangent les deux.

### Le redimensionnement du 19/09 (0,5 → 1 vCPU)

Mesure dans le conteneur, mêmes trois positions, budget de 1,5 s :

| | nœuds/s | profondeur atteinte (initiale / milieu / finale) |
|---|---|---|
| 0,5 vCPU | 18 000 à 23 000 | 6 / 5 / 10 |
| 1 vCPU | 37 000 à 49 000 | 7 / 5 / 12 |
| Référence : un cœur entier sur le PC | 36 000 à 48 000 | 7 / 5 / 11 |

Le moteur est mono-thread : c'est la vitesse d'un cœur qui compte, pas leur nombre. Un demi-cœur partagé entre
lichess-bot et le moteur le bridait de moitié.

## v2 — `v2-pypy-warmup`

Trois changements, tous dans l'image `chessbot-lichess-bot:v5` :

1. **Le moteur tourne sous PyPy** (`lichess-bot-service/Dockerfile`, image PyPy épinglée par digest).
   lichess-bot reste sous CPython. Une fois chaud, PyPy fait environ 2,5 à 3 fois plus de nœuds/s.
2. **Chauffe du JIT** (`app/uci.py`). lichess-bot lance un nouveau moteur à chaque partie, donc le JIT de PyPy
   repart à froid. Pendant que le moteur attend un `go` (par exemple le temps de réflexion de l'adversaire), un
   fil de fond joue de courtes recherches pour le chauffer, et s'arrête dès qu'un `go` arrive.
3. **Gestion du temps** (`app/bots/minimax.py`, `app/uci.py`, `lichess-bot-service/config.yml`). L'incrément est
   passé au moteur au lieu d'être ajouté au temps restant. Le budget par coup est une fraction du temps restant
   plus 80 % de l'incrément, plafonné à la moitié du temps restant. `move_overhead` passe de 2000 à 1000 ms.

### Mesures (Docker, limité à 1 CPU)

| Situation | Milieu de partie | Position initiale |
|---|---|---|
| CPython | ~19 000 nœuds/s | ~25 000 |
| PyPy à froid (premier `go` d'une partie) | 9 400 (profondeur 3) | 30 700 (profondeur 6) |
| PyPy après 10 s de chauffe | 50 500 (profondeur 6) | 82 500 (profondeur 8) |
| PyPy après 30 s de chauffe | 62 300 (profondeur 6) | 81 700 (profondeur 8) |

**Le compromis** : le premier coup d'une partie jouée avec les Blancs part à froid, donc plus faible qu'avec
CPython. Ensuite, le milieu de partie et la finale gagnent un à deux plies. Un livre d'ouvertures (pas encore
fait) réglerait ce point.

**Résultat** : 6 parties, 5 victoires, 1 défaite (83,3 %). Trop peu pour conclure.

### Incident du déploiement

Le déploiement du 20/09 a coupé une partie en cours (`6bbWp848`). J'avais vérifié qu'aucune partie n'était en
cours à partir des logs Azure, qui ont plusieurs minutes de retard. Le nouveau conteneur est resté environ
1 min 30 limité par Lichess (erreur 429 sur le flux d'événements), a repris la partie avec l'horloge très
entamée et a perdu par mat au coup 45. Cette partie est comptée en v1, puisqu'elle a commencé avant le tag.
Avant tout futur déploiement, on vérifie l'API Lichess (`users/status?ids=Taudambot&withGameIds=true`).

Les parties jouées sur `v5` entre le déploiement (15:35) et le tag (15:43) sont aussi comptées en v1.

## Expérience non déployée : le NNUE

Un réseau HalfKP (128×2-32-32, PyTorch) entraîné sur 1,5 million de positions de la base d'évaluations Lichess
(`data/nnue_1500k.pt`) a été comparé à `evaluate()`.

| | `evaluate()` | NNUE (1,5 M) |
|---|---|---|
| RMSE contre Stockfish (50 000 positions hors entraînement) | 375 cp | **307 cp** |
| Signe correct (Stockfish à plus de 100 cp d'écart) | 75,9 % | **82,9 %** |
| Arène à profondeur fixe 3, 10 parties | **10 victoires** | 0 |

Le NNUE évalue mieux les positions déjà décidées mais joue beaucoup moins bien : retirer une dame adverse ne lui
fait gagner que +47 cp en moyenne (bruit de ±174), contre +898 pour `evaluate()`. Cause probable : sans
features indépendantes de la case du roi, il n'apprend pas correctement la valeur du matériel. Il n'est pas
déployé. Piste : lui faire apprendre la correction à ajouter à `evaluate()` plutôt que le score entier.

## Livre d'ouvertures (pas encore déployé)

`tools/build_book.py` génère `lichess-bot-service/book.bin`, un livre Polyglot d'une
trentaine de lignes de théorie usuelle (Ruy Lopez, Sicilienne, Française, Caro-Kann,
Gambit Dame, Indienne du Roi, Nimzo-Indienne, etc.), écrites à la main et rejouées avec
`python-chess` pour garantir leur légalité. lichess-bot le lit nativement
(`polyglot.enabled: true` dans `config.yml`, `selection: weighted_random`, `max_depth: 10`)
et choisit un coup du livre sans lancer la recherche tant que la position y figure.

**Objectif** : le premier `go` d'une partie tombe sur un moteur PyPy encore froid (cf. v2
ci-dessus) ; le livre couvre justement ces premiers coups, quel que soit l'adversaire, donc
la recherche ne démarre que quand le JIT a déjà eu le temps de chauffer entre les coups.

Pas encore déployé, donc pas encore mesuré en parties réelles.

## Suivre les résultats

```bash
venv\Scripts\python.exe -m tools.lichess_stats stats Taudambot     # score par version
venv\Scripts\python.exe -m tools.lichess_stats tag v3-ma-version   # à faire à chaque déploiement
venv\Scripts\python.exe -m tools.bench_nps                         # nœuds/s et profondeur (en local)
```

Il faut au moins 50 à 100 parties par version avant qu'une différence de score ait un sens, surtout en bullet.

## À faire

- Attendre assez de parties en v2 pour comparer à la v1, ou découper le score par cadence et par classement de
  l'adversaire.
- Déployer et mesurer le livre d'ouvertures (voir ci-dessus).
- Table de transposition conservée d'un coup à l'autre, et profilage de la recherche.
- NNUE : essai de la correction résiduelle (Stockfish − `evaluate()`), sans intention de déployer avant qu'il
  gagne en arène.
