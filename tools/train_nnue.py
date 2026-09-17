"""Prototype NNUE : encodage HalfKP + reseau halfkp-128x2-32-32, entraine sur
data/eval_sample.jsonl (labels Stockfish issus du dump Lichess evaluations).

C'est la version "precision d'abord" : le reseau tourne en PyTorch, recalcule
l'accumulateur a zero pour chaque position (pas de mise a jour incrementale
lors des coups). L'optimisation incrementale, qui donne son nom et sa vitesse
a NNUE, est une etape separee a faire une fois le modele valide : elle
suppose d'accrocher l'accumulateur au make/unmake move de la recherche
(app/bots/minimax.py), ce qui n'a pas de sens tant qu'on ne sait pas si le
reseau vaut mieux que l'eval actuelle.

Features HalfKP (King-Piece), comme dans le NNUE original de Stockfish :
pour chaque perspective (camp au trait / adversaire), chaque piece hors roi
allume un indice qui depend de la case du roi de cette perspective, de la
case de la piece, de son type et du fait qu'elle est amie ou ennemie. Les
deux perspectives partagent la meme table de poids (le plateau est retourne
verticalement pour les Noirs, cf. `_half_kp_features`), comme dans
l'implementation de reference.

Usage (depuis la racine du projet, dans un environnement avec torch) :
    python -m tools.train_nnue --data data/eval_sample.jsonl --epochs 6
"""

from __future__ import annotations

import argparse
import json

import chess
import numpy as np
import torch
from torch import nn

from app.bots.evaluation import evaluate

CP_CLIP = 1000
ACC_SIZE = 128
NUM_FEATURES = 64 * 64 * 10  # HalfKP : 64 cases de roi x 64 cases x 5 types x 2 (ami/ennemi)
_TYPE_IDX = {chess.PAWN: 0, chess.KNIGHT: 1, chess.BISHOP: 2, chess.ROOK: 3, chess.QUEEN: 4}


def _half_kp_features(board: chess.Board, perspective: chess.Color) -> list[int]:
    king_sq = board.king(perspective)
    flip = perspective == chess.BLACK
    king_rel = king_sq ^ 56 if flip else king_sq
    indices = []
    for square, piece in board.piece_map().items():
        if piece.piece_type == chess.KING:
            continue
        sq_rel = square ^ 56 if flip else square
        friend = 0 if piece.color == perspective else 1
        indices.append(king_rel * 640 + sq_rel * 10 + _TYPE_IDX[piece.piece_type] * 2 + friend)
    return indices


def _target(record: dict, board: chess.Board) -> float:
    """Score cote camp au trait, coherent avec la convention d'`evaluate()`."""
    if record.get("cp") is not None:
        score = record["cp"]
    else:
        score = 1000 if record["mate"] > 0 else -1000
    score = max(-CP_CLIP, min(CP_CLIP, score))
    return float(score if board.turn == chess.WHITE else -score)


def _load(path: str):
    boards, us_feats, them_feats, targets = [], [], [], []
    with open(path, encoding="utf-8") as f:
        for line in f:
            record = json.loads(line)
            board = chess.Board(record["fen"])
            boards.append(board)
            us_feats.append(_half_kp_features(board, board.turn))
            them_feats.append(_half_kp_features(board, not board.turn))
            targets.append(_target(record, board))
    return boards, us_feats, them_feats, np.array(targets, dtype=np.float32)


class NNUE(nn.Module):
    """halfkp-128x2-32-32 : deux accumulateurs de 128 (poids partages), puis
    un petit MLP. Le biais de l'accumulateur est ajoute une seule fois par
    perspective, pas par feature active (comme dans l'implementation de
    reference : c'est un biais de neurone, pas de feature)."""

    def __init__(self, num_features: int = NUM_FEATURES, acc_size: int = ACC_SIZE):
        super().__init__()
        self.embed = nn.EmbeddingBag(num_features, acc_size, mode="sum")
        self.acc_bias = nn.Parameter(torch.zeros(acc_size))
        self.fc1 = nn.Linear(acc_size * 2, 32)
        self.fc2 = nn.Linear(32, 32)
        self.fc3 = nn.Linear(32, 1)

    def forward(self, us_idx, us_off, them_idx, them_off):
        us = self.embed(us_idx, us_off) + self.acc_bias
        them = self.embed(them_idx, them_off) + self.acc_bias
        x = torch.cat([us, them], dim=1).clamp(0, 1)  # ClippedReLU, comme le NNUE original
        x = torch.relu(self.fc1(x))
        x = torch.relu(self.fc2(x))
        return self.fc3(x).squeeze(-1)


def _make_batch(indices, feats_a, feats_b, targets, scale):
    a_idx: list[int] = []
    a_off = [0]
    b_idx: list[int] = []
    b_off = [0]
    for i in indices:
        a_idx.extend(feats_a[i])
        a_off.append(len(a_idx))
        b_idx.extend(feats_b[i])
        b_off.append(len(b_idx))
    y = targets[indices] / scale
    return (
        torch.tensor(a_idx, dtype=torch.long),
        torch.tensor(a_off[:-1], dtype=torch.long),
        torch.tensor(b_idx, dtype=torch.long),
        torch.tensor(b_off[:-1], dtype=torch.long),
        torch.tensor(y, dtype=torch.float32),
    )


def _rmse(pred, y):
    return float(np.sqrt(np.mean((pred - y) ** 2)))


def _r2(pred, y):
    ss_res = np.sum((y - pred) ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    return 1 - ss_res / ss_tot


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="data/eval_sample.jsonl")
    parser.add_argument("--epochs", type=int, default=6)
    parser.add_argument("--batch-size", type=int, default=1024)
    parser.add_argument("--out", default="data/nnue_prototype.pt")
    args = parser.parse_args()

    print("chargement + encodage HalfKP...", flush=True)
    boards, us_feats, them_feats, targets = _load(args.data)
    n = len(boards)
    print(f"{n} positions encodees", flush=True)

    rng = np.random.default_rng(0)
    idx = np.arange(n)
    rng.shuffle(idx)
    n_test = int(n * 0.2)
    test_idx, train_idx = idx[:n_test], idx[n_test:]

    model = NNUE()
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    loss_fn = nn.MSELoss()
    scale = 100.0

    for epoch in range(args.epochs):
        rng.shuffle(train_idx)
        total = 0.0
        for start in range(0, len(train_idx), args.batch_size):
            batch = train_idx[start : start + args.batch_size]
            a_idx, a_off, b_idx, b_off, y = _make_batch(batch, us_feats, them_feats, targets, scale)
            opt.zero_grad()
            pred = model(a_idx, a_off, b_idx, b_off)
            loss = loss_fn(pred, y)
            loss.backward()
            opt.step()
            total += loss.item() * len(batch)
        print(f"epoch {epoch + 1}/{args.epochs}  train MSE (echelle /100) = {total / len(train_idx):.4f}", flush=True)

    model.eval()
    preds = []
    with torch.no_grad():
        for start in range(0, len(test_idx), 4096):
            batch = test_idx[start : start + 4096]
            a_idx, a_off, b_idx, b_off, _ = _make_batch(batch, us_feats, them_feats, targets, scale)
            preds.append(model(a_idx, a_off, b_idx, b_off).numpy() * scale)
    preds = np.concatenate(preds)
    y_test = targets[test_idx]

    mean_pred = np.full_like(y_test, targets[train_idx].mean())
    handcrafted_pred = np.clip(
        np.array([evaluate(boards[i]) for i in test_idx], dtype=np.float32), -CP_CLIP, CP_CLIP
    )

    print("\n--- Comparaison sur le meme jeu de test (point de vue camp au trait) ---")
    print(f"{'moyenne (naif)':28s} RMSE={_rmse(mean_pred, y_test):7.1f}")
    print(f"{'evaluate() actuel':28s} RMSE={_rmse(handcrafted_pred, y_test):7.1f}  R2={_r2(handcrafted_pred, y_test):.3f}")
    print(f"{'NNUE (halfkp 128x2-32-32)':28s} RMSE={_rmse(preds, y_test):7.1f}  R2={_r2(preds, y_test):.3f}")

    torch.save(model.state_dict(), args.out)
    print(f"\nmodele sauvegarde : {args.out}")


if __name__ == "__main__":
    main()
