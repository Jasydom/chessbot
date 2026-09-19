"""Mesure les noeuds/profondeur atteints par evaluate() et par le NNUE au
meme budget de temps, pour quantifier le cout par noeud du NNUE (chaque appel
construit des tenseurs PyTorch et fait tourner deux passes avant).

Ce cout n'explique qu'une partie de la deroute dans tools/arena_nnue.py : a
profondeur egale (`--depth`), le prototype perd aussi, donc son eval est
elle-meme plus faible que celle de `evaluate()`.

Usage (necessite torch) :
    python -m tools.diagnose_nnue_speed --model data/nnue_prototype.pt
"""

from __future__ import annotations

import argparse
import time

import chess

from app.bots.evaluation import evaluate
from app.bots.minimax import _Search
from app.bots.nnue_eval import load_evaluate_fn

_POSITIONS = {
    "position initiale": chess.STARTING_FEN,
    "milieu de partie": "r1bqkb1r/pp1n1ppp/2p1pn2/3p4/2PP4/2N1PN2/PP3PPP/R1BQKB1R w KQkq - 0 6",
    "finale": "8/5pk1/6p1/7p/7P/6P1/5PK1/8 w - - 0 1",
}


def _run(evaluate_fn, fen: str, time_budget: float) -> tuple[int, int]:
    board = chess.Board(fen)
    search = _Search(board, deadline=time.monotonic() + time_budget, max_depth=64, evaluate_fn=evaluate_fn)
    search.run()
    return search.nodes, search.depth_reached


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="data/nnue_prototype.pt")
    parser.add_argument("--time-budget", type=float, default=0.6)
    args = parser.parse_args()

    nnue_evaluate = load_evaluate_fn(args.model)

    header = f"{'position':18s} {'evaluate() noeuds':>18s} {'evaluate() prof':>16s} {'nnue noeuds':>12s} {'nnue prof':>10s} {'ratio noeuds':>13s}"
    print(header)
    for label, fen in _POSITIONS.items():
        nodes_hc, depth_hc = _run(evaluate, fen, args.time_budget)
        nodes_nnue, depth_nnue = _run(nnue_evaluate, fen, args.time_budget)
        ratio = nodes_hc / max(nodes_nnue, 1)
        print(f"{label:18s} {nodes_hc:18d} {depth_hc:16d} {nodes_nnue:12d} {depth_nnue:10d} {ratio:12.1f}x")


if __name__ == "__main__":
    main()
