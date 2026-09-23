# ChessBot

Un moteur d'échecs écrit en Python, fait pour jouer sur Lichess :

- **sur Lichess** : le moteur, exposé en UCI et branché sur [lichess-bot](https://github.com/lichess-bot-devs/lichess-bot) ;
- **en laboratoire** : des outils pour mesurer sa force (arène bot contre bot, suivi des parties Lichess par version) et pour entraîner une évaluation apprise (prototype NNUE).

Le moteur repose sur [`python-chess`](https://python-chess.readthedocs.io/) pour les règles ; toute la recherche et l'évaluation sont écrites ici.

## Le moteur

**Recherche** (`app/bots/minimax.py`) : negamax avec élagage alpha-bêta, à temps borné.

- approfondissement itératif (un coup jouable à tout instant) ;
- table de transposition ;
- tri des coups : coup de la table, captures (MVV-LVA), killers, heuristique d'historique ;
- recherche de quiescence, avec delta pruning ;
- null move pruning et Late Move Reductions.

**Évaluation** (`app/bots/evaluation.py`) : valeur matérielle + tables pièce/case (« Simplified Evaluation Function »), avec interpolation milieu de partie / finale selon le matériel restant, et un terme de sécurité du roi (abri de pions, colonnes ouvertes). Le score est toujours du point de vue du camp au trait.

L'évaluation est isolée de la recherche : `MinimaxBot.evaluate_fn` est injectable, ce qui permet de comparer une autre évaluation (par exemple un réseau appris) sans dupliquer l'alpha-bêta.

**Bots** (registre dans `app/bots/__init__.py`, utilisé par l'arène) :

| Nom | Description |
|---|---|
| `random` | coups aléatoires |
| `easy` | profondeur 2, sans quiescence (gaffe comme un débutant) |
| `normal` (défaut) | budget de 0,6 s par coup |
| `hard` | budget de 1,5 s par coup |

Chaque bot adapte son temps de réflexion au temps restant sur la pendule (`clock_fraction` : une fraction du temps restant par coup), pour ne pas tomber au drapeau.

## Lancer en local

```bash
python -m venv venv
source venv/bin/activate        # Windows : venv\Scripts\activate
pip install -r requirements.txt
python -m tools.arena --bot-a random --bot-b normal --games 10
```

## Jouer sur Lichess

`app/uci.py` est un pont UCI : il lit les commandes sur stdin, appelle `MinimaxBot` directement (sans HTTP) et répond sur stdout. `lichess-bot-service/` l'empaquette avec une version épinglée de lichess-bot.

```bash
# .env à la racine (ignoré par git) :
#   LICHESS_BOT_TOKEN=<jeton API d'un compte Lichess converti en bot>
docker compose up --build lichess-bot
```

La configuration (défis acceptés, cadences, etc.) est dans `lichess-bot-service/config.yml`. L'historique des versions déployées et leurs résultats sont dans [`VERSIONS.md`](VERSIONS.md).

**Suivi par version.** Lichess ne connaît pas la notion de version du moteur ; `tools/lichess_stats.py` garde donc son propre repère dans `tools/lichess_versions.json` :

```bash
python -m tools.lichess_stats tag v2-ma-version        # à chaque déploiement d'une nouvelle version
python -m tools.lichess_stats stats <compte_bot>       # score par version
```

## Outils de développement

Tous se lancent depuis la racine du projet avec `python -m tools.<nom>`.

| Outil | Rôle |
|---|---|
| `arena` | fait jouer deux bots du registre l'un contre l'autre et affiche le score (`--bot-a random --bot-b normal --games 10`) |
| `lichess_stats` | performances réelles sur Lichess, par version du moteur |
| `prepare_eval_dataset` | extrait un échantillon du dump Lichess d'évaluations Stockfish |
| `train_baseline_eval` | baselines de comparaison : moyenne, régression sur le matériel, `evaluate()` actuel |
| `train_nnue` | entraîne le prototype NNUE (HalfKP 128×2-32-32, PyTorch) |
| `arena_nnue` | fait jouer le NNUE contre un bot du registre, à temps égal ou à profondeur fixe (`--depth`) |
| `diagnose_nnue_speed` | mesure nœuds et profondeur atteints par `evaluate()` et par le NNUE au même budget |
| `bench_nps` | mesure nœuds/s et profondeur atteinte sur 3 positions (comparer CPython/PyPy ou des tailles de conteneur) |
| `build_book` | génère `lichess-bot-service/book.bin`, le livre d'ouvertures Polyglot (lu par lichess-bot, pas par notre moteur) |

Ces outils ont des dépendances absentes de `requirements.txt`, car le bot déployé n'en a pas besoin : `scikit-learn`, `torch`, `zstandard` et `azure-storage-blob` selon l'outil.

### Données d'entraînement

Le dump complet des évaluations Lichess (~22 Go compressés, une position analysée par Stockfish par ligne) est stocké sur Azure Blob Storage et n'est jamais téléchargé en entier : `prepare_eval_dataset` le lit en streaming et s'arrête après N positions.

```bash
export AZURE_STORAGE_KEY=<clé du compte de stockage>    # jamais en argument de commande
python tools/prepare_eval_dataset.py --count 300000 --out data/eval_sample.jsonl
```

Le dossier `data/` est ignoré par git.

### Où en est le NNUE

C'est un prototype de recherche, pas encore un moteur déployé. Le réseau est évalué en PyTorch, avec un accumulateur recalculé à zéro à chaque position (pas de mise à jour incrémentale), donc plus lent par nœud que `evaluate()`. Selon `tools/diagnose_nnue_speed.py`, ce coût n'explique qu'une partie de la défaite en arène : à profondeur égale, le prototype perd aussi. L'optimisation incrémentale n'a de sens qu'une fois l'évaluation elle-même meilleure que l'actuelle.

## Déploiement

Le bot Lichess tourne sur Azure Container Apps (image construite en local, poussée sur Azure Container Registry) :

```bash
docker build --no-cache -f lichess-bot-service/Dockerfile -t <registre>.azurecr.io/chessbot-lichess-bot:vN .
az acr login --name <registre>
docker push <registre>.azurecr.io/chessbot-lichess-bot:vN
az containerapp update -n <app> -g <groupe-de-ressources> --image <registre>.azurecr.io/chessbot-lichess-bot:vN
```

Incrémenter `N` à chaque déploiement, puis `python -m tools.lichess_stats tag <version>`. Le conteneur reste en permanence à 1 réplica pour garder la connexion à Lichess ; le mettre à jour redémarre le bot, à faire entre deux parties.

## Structure

```
app/
  uci.py             pont UCI pour lichess-bot
  bots/
    base.py          interface Bot
    minimax.py       recherche alpha-bêta
    evaluation.py    évaluation statique
    nnue_eval.py     évaluation par réseau HalfKP (prototype, dépend de torch)
    random_bot.py
lichess-bot-service/ Dockerfile + config de lichess-bot + book.bin (livre d'ouvertures)
tools/               arène, suivi Lichess, entraînement (voir ci-dessus)
.claude/agents/      sous-agents de dev (coder, verifier, cleaner)
```
