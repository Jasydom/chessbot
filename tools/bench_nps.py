"""Mesure la vitesse de recherche (noeuds/s) et la profondeur atteinte.

Sert a comparer des interpreteurs (CPython / PyPy) ou des tailles de conteneur
sur les memes positions et le meme budget de temps. Le JIT de PyPy demarre a
froid : les positions sont donc rejouees sur plusieurs tours, comme le fait le
moteur UCI qui reste vivant toute la partie, et on affiche chaque tour pour voir
la montee en regime.

Usage (depuis la racine du projet, ne necessite que python-chess) :
    python -m tools.bench_nps
    pypy3 -m tools.bench_nps --rounds 6 --time-budget 1.0
"""

from __future__ import annotations

import argparse
import platform
import time

import chess

from app.bots.minimax import _Search

_POSITIONS = {
    "initiale": chess.STARTING_FEN,
    "milieu": "r1bqkb1r/pp1n1ppp/2p1pn2/3p4/2PP4/2N1PN2/PP3PPP/R1BQKB1R w KQkq - 0 6",
    "finale": "8/5pk1/6p1/7p/7P/6P1/5PK1/8 w - - 0 1",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--time-budget", type=float, default=1.5)
    parser.add_argument("--rounds", type=int, default=3)
    args = parser.parse_args()

    print(f"{platform.python_implementation()} {platform.python_version()}")
    print(f"{'tour':>4s} {'position':10s} {'noeuds':>9s} {'noeuds/s':>9s} {'prof':>5s}")
    for round_number in range(1, args.rounds + 1):
        for label, fen in _POSITIONS.items():
            search = _Search(
                chess.Board(fen),
                deadline=time.monotonic() + args.time_budget,
                max_depth=64,
            )
            started = time.monotonic()
            search.run()
            elapsed = time.monotonic() - started
            print(
                f"{round_number:4d} {label:10s} {search.nodes:9d} "
                f"{search.nodes / elapsed:9.0f} {search.depth_reached:5d}"
            )


if __name__ == "__main__":
    main()
