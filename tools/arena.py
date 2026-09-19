"""Arene bot-vs-bot : fait jouer deux bots du registre l'un contre l'autre et
affiche un score.

Outil de developpement, hors de l'app web : aucun lien avec FastAPI, les bots
sont appeles directement en process, sans aller-retour HTTP.

Version minimale : parties sequentielles, chaque bot pensant a son budget de
temps par defaut (declare dans `app/bots/__init__.py`), sans simulation de
pendule. Pistes non traitees ici, prevues pour une iteration future :
- parallelisation par process (le search est CPU-bound, un ProcessPoolExecutor
  fait sauter le GIL) ;
- mode a profondeur/noeuds fixe plutot qu'a temps borne, pour des resultats
  reproductibles d'un run a l'autre (un budget de temps depend de la charge de
  la machine au moment du test) ;
- sortie structuree (CSV/JSON) et intervalle de confiance (Wilson) ou SPRT
  pour juger si un ecart de score est statistiquement significatif.

Usage (depuis la racine du projet) :
    python -m tools.arena --bot-a random --bot-b normal --games 10
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

import chess

from app.bots import get_bot

DEFAULT_GAMES = 10
#: Garde-fou contre une partie qui ne se termine jamais (bug de repetition,
#: bot qui refuse de mater). Une partie humaine depasse rarement 150 coups.
DEFAULT_MAX_PLIES = 300


@dataclass
class _Score:
    wins_a: int = 0
    wins_b: int = 0
    draws: int = 0

    def record(self, winner: str | None) -> None:
        if winner == "a":
            self.wins_a += 1
        elif winner == "b":
            self.wins_b += 1
        else:
            self.draws += 1


def _play_game(bot_white, bot_black, max_plies: int) -> str | None:
    """Joue une partie entre deux bots. Renvoie "white", "black", ou None (nulle).

    `claim_draw=True` fait compter les nulles reclamables (repetition, regle
    des 50 coups) : sans ca, une partie moteur-contre-moteur peut boucler bien
    au-dela de `max_plies` avant qu'une nulle "automatique" (mat, pat, materiel
    insuffisant) ne survienne.
    """
    board = chess.Board()
    plies = 0
    while not board.is_game_over(claim_draw=True) and plies < max_plies:
        bot = bot_white if board.turn == chess.WHITE else bot_black
        move = bot.choose_move(board)
        if move is None:
            break
        board.push(move)
        plies += 1

    outcome = board.outcome(claim_draw=True)
    if outcome is None or outcome.winner is None:
        return None
    return "white" if outcome.winner == chess.WHITE else "black"


def run_match_with_bots(bot_a, bot_b, games: int, max_plies: int) -> _Score:
    """Comme `run_match`, mais avec des bots deja instancies : permet de tester
    un bot hors registre (ex. `tools/arena_nnue.py`) sans passer par `get_bot`.
    """
    score = _Score()
    for game_index in range(games):
        # Parties appariees : A joue Blancs sur les parties paires, Noirs sur
        # les impaires. Sans cela, l'avantage du trait fausserait le score.
        a_plays_white = game_index % 2 == 0
        white, black = (bot_a, bot_b) if a_plays_white else (bot_b, bot_a)

        winner_color = _play_game(white, black, max_plies)
        if winner_color is None:
            winner = None
        elif (winner_color == "white") == a_plays_white:
            winner = "a"
        else:
            winner = "b"
        score.record(winner)

        outcome_label = {"a": "A", "b": "B", None: "nulle"}[winner]
        side_label = "A" if a_plays_white else "B"
        print(f"Partie {game_index + 1}/{games} : {side_label} a les Blancs -> {outcome_label}")

    return score


def run_match(name_a: str, name_b: str, games: int, max_plies: int) -> _Score:
    bot_a = get_bot(name_a)
    bot_b = get_bot(name_b)
    if bot_a is None:
        raise SystemExit(f"Bot inconnu : {name_a}")
    if bot_b is None:
        raise SystemExit(f"Bot inconnu : {name_b}")
    return run_match_with_bots(bot_a, bot_b, games, max_plies)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fait jouer deux bots du registre l'un contre l'autre.")
    parser.add_argument("--bot-a", required=True, help="Nom du premier bot (voir app/bots/__init__.py)")
    parser.add_argument("--bot-b", required=True, help="Nom du second bot")
    parser.add_argument("--games", type=int, default=DEFAULT_GAMES, help="Nombre de parties (defaut : %(default)s)")
    parser.add_argument(
        "--max-plies", type=int, default=DEFAULT_MAX_PLIES, help="Limite de demi-coups par partie (defaut : %(default)s)"
    )
    args = parser.parse_args()

    score = run_match(args.bot_a, args.bot_b, args.games, args.max_plies)

    total = score.wins_a + score.wins_b + score.draws
    print()
    print(f"Score sur {total} parties :")
    print(f"  {args.bot_a} (A) : {score.wins_a}")
    print(f"  {args.bot_b} (B) : {score.wins_b}")
    print(f"  Nulles        : {score.draws}")


if __name__ == "__main__":
    main()
