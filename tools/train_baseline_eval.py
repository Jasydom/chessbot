"""Baseline supervise : une regression lineaire sur le materiel seul,
entrainee sur les evaluations Stockfish de data/eval_sample.jsonl.

Objectif : etablir un point de comparaison chiffre avant d'attaquer un
modele plus riche (reseau de neurones). Trois predicteurs sont compares sur
le meme jeu de test :
  - la moyenne du jeu d'entrainement (baseline naive) ;
  - une regression lineaire sur le seul comptage de pieces (+ trait) ;
  - `evaluate()` (app/bots/evaluation.py), l'eval handcrafted actuelle du bot.

Le label Stockfish (`cp`) du dataset Lichess est du point de vue des Blancs ;
`evaluate()` est du point de vue du camp au trait (app/bots/evaluation.py:257),
d'ou la conversion `evaluate_white_pov` ci-dessous.

Usage (depuis la racine du projet, avec scikit-learn installe) :
    python -m tools.train_baseline_eval --data data/eval_sample.jsonl
"""

from __future__ import annotations

import argparse
import json

import chess
import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_squared_error, r2_score
from sklearn.model_selection import train_test_split

from app.bots.evaluation import PIECE_VALUES, evaluate

_MATERIAL_TYPES = (chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN)
#: Au-dela, la position est deja tranchee : borner l'evite de dominer la loss.
CP_CLIP = 1000


def _load(path: str) -> tuple[list[chess.Board], np.ndarray]:
    boards = []
    targets = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            record = json.loads(line)
            if record.get("cp") is None:
                continue  # mat force : hors perimetre de ce baseline
            boards.append(chess.Board(record["fen"]))
            targets.append(max(-CP_CLIP, min(CP_CLIP, record["cp"])))
    return boards, np.array(targets, dtype=float)


def _features(boards: list[chess.Board]) -> np.ndarray:
    rows = []
    for board in boards:
        row = [
            chess.popcount(board.pieces_mask(pt, chess.WHITE))
            - chess.popcount(board.pieces_mask(pt, chess.BLACK))
            for pt in _MATERIAL_TYPES
        ]
        row.append(1.0 if board.turn == chess.WHITE else -1.0)
        rows.append(row)
    return np.array(rows, dtype=float)


def _evaluate_white_pov(board: chess.Board) -> int:
    score = evaluate(board)
    return score if board.turn == chess.WHITE else -score


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="data/eval_sample.jsonl")
    args = parser.parse_args()

    boards, y = _load(args.data)
    X = _features(boards)
    print(f"{len(boards)} positions chargees (cp non-nul, clip a +-{CP_CLIP})")

    idx = np.arange(len(boards))
    idx_train, idx_test = train_test_split(idx, test_size=0.2, random_state=0)
    X_train, X_test = X[idx_train], X[idx_test]
    y_train, y_test = y[idx_train], y[idx_test]

    # Baseline naive : toujours predire la moyenne du train.
    mean_pred = np.full_like(y_test, y_train.mean())
    mean_mse = mean_squared_error(y_test, mean_pred)

    # Regression lineaire sur le materiel + trait.
    model = LinearRegression()
    model.fit(X_train, y_train)
    lin_pred = model.predict(X_test)
    lin_mse = mean_squared_error(y_test, lin_pred)
    lin_r2 = r2_score(y_test, lin_pred)

    # Eval handcrafted actuelle du bot, convertie point de vue Blancs.
    boards_test = [boards[i] for i in idx_test]
    handcrafted_pred = np.array([_evaluate_white_pov(b) for b in boards_test], dtype=float)
    handcrafted_pred = np.clip(handcrafted_pred, -CP_CLIP, CP_CLIP)
    handcrafted_mse = mean_squared_error(y_test, handcrafted_pred)
    handcrafted_r2 = r2_score(y_test, handcrafted_pred)

    print("\n--- Resultats sur le jeu de test (RMSE en centipions) ---")
    print(f"{'moyenne (naif)':25s} RMSE={mean_mse ** 0.5:7.1f}")
    print(f"{'regression materiel':25s} RMSE={lin_mse ** 0.5:7.1f}  R2={lin_r2:.3f}")
    print(f"{'evaluate() actuel':25s} RMSE={handcrafted_mse ** 0.5:7.1f}  R2={handcrafted_r2:.3f}")

    print("\n--- Valeurs de pieces apprises vs celles codees en dur ---")
    names = {chess.PAWN: "pion", chess.KNIGHT: "cavalier", chess.BISHOP: "fou",
             chess.ROOK: "tour", chess.QUEEN: "dame"}
    for pt, coef in zip(_MATERIAL_TYPES, model.coef_):
        print(f"{names[pt]:10s} appris={coef:7.1f}   code en dur={PIECE_VALUES[pt]}")
    print(f"{'trait (tempo)':10s} appris={model.coef_[-1]:7.1f}")
    print(f"intercept={model.intercept_:.1f}")


if __name__ == "__main__":
    main()
