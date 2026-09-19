"""Fait jouer le bot NNUE (prototype, cf. tools/train_nnue.py) contre un bot
du registre a budget de temps egal, pour verifier si le gain de RMSE observe
a l'entrainement se traduit en un gain de parties.

Attention a l'interpretation : ce NNUE recalcule son accumulateur a zero a
chaque position (pas de mise a jour incrementale), donc il est plus lent par
noeud que `evaluate()`. A budget de temps egal, il explore moins de noeuds,
ce qui defavorise le NNUE independamment de la qualite de son eval. C'est
la condition reelle si on le deployait tel quel aujourd'hui, mais ce n'est
pas un test isole de la qualite de l'eval seule.

Usage (necessite torch ; le modele doit deja exister, cf. train_nnue.py) :
    python -m tools.arena_nnue --against normal --games 20 --model data/nnue_prototype.pt
"""

from __future__ import annotations

import argparse
from dataclasses import replace

from app.bots import get_bot
from app.bots.minimax import MinimaxBot
from app.bots.nnue_eval import load_evaluate_fn
from tools.arena import DEFAULT_GAMES, DEFAULT_MAX_PLIES, run_match_with_bots


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--against", default="normal", help="Bot du registre a affronter (voir app/bots/__init__.py)")
    parser.add_argument("--model", default="data/nnue_prototype.pt")
    parser.add_argument("--games", type=int, default=DEFAULT_GAMES)
    parser.add_argument("--max-plies", type=int, default=DEFAULT_MAX_PLIES)
    parser.add_argument(
        "--depth",
        type=int,
        default=None,
        help="Profondeur fixe pour les deux bots (sans limite de temps) : isole la qualite de l'eval du cout par noeud",
    )
    args = parser.parse_args()

    baseline_bot = get_bot(args.against)
    if baseline_bot is None:
        raise SystemExit(f"Bot inconnu : {args.against}")

    if not isinstance(baseline_bot, MinimaxBot):
        raise SystemExit("--against doit etre un bot minimax (easy/normal/hard), pas un budget de temps a comparer")

    if args.depth is not None:
        # Budget de temps hors d'atteinte : c'est max_depth qui borne la recherche.
        baseline_bot = replace(baseline_bot, max_depth=args.depth, time_budget=3600.0)

    nnue_evaluate = load_evaluate_fn(args.model)
    nnue_bot = MinimaxBot(
        name="nnue",
        label="Minimax - NNUE",
        max_depth=baseline_bot.max_depth,
        time_budget=baseline_bot.time_budget,
        use_quiescence=baseline_bot.use_quiescence,
        evaluate_fn=nnue_evaluate,
    )

    score = run_match_with_bots(nnue_bot, baseline_bot, args.games, args.max_plies)

    total = score.wins_a + score.wins_b + score.draws
    print()
    if args.depth is not None:
        print(f"Score sur {total} parties (profondeur fixe {args.depth}) :")
    else:
        print(f"Score sur {total} parties (meme budget de temps, {baseline_bot.time_budget}s) :")
    print(f"  nnue (A)         : {score.wins_a}")
    print(f"  {args.against} (B) : {score.wins_b}")
    print(f"  Nulles           : {score.draws}")


if __name__ == "__main__":
    main()
