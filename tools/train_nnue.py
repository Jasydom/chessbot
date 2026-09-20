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
from array import array

import chess
import numpy as np
import torch
from torch import nn

from app.bots.evaluation import evaluate
from app.bots.nnue_eval import ACC_SIZE, NUM_FEATURES, NNUE
from app.bots.nnue_eval import half_kp_features as _half_kp_features

CP_CLIP = 1000


def _target(record: dict, board: chess.Board) -> float:
    """Score cote camp au trait, coherent avec la convention d'`evaluate()`."""
    if record.get("cp") is not None:
        score = record["cp"]
    else:
        score = 1000 if record["mate"] > 0 else -1000
    score = max(-CP_CLIP, min(CP_CLIP, score))
    return float(score if board.turn == chess.WHITE else -score)


def _load(path: str):
    """Encode le fichier en features plates (indices concatenes + offsets par
    position) plutot qu'en listes Python par position : a 1M+ positions, les
    listes d'entiers et les `chess.Board` gardes en memoire ne tiennent plus.
    Les FEN sont conservees pour reconstruire des plateaux a la demande.
    """
    fens: list[str] = []
    targets: list[float] = []
    us_flat, them_flat = array("i"), array("i")
    us_off, them_off = array("q", [0]), array("q", [0])
    with open(path, encoding="utf-8") as f:
        for line in f:
            record = json.loads(line)
            board = chess.Board(record["fen"])
            fens.append(record["fen"])
            us_flat.extend(_half_kp_features(board, board.turn))
            them_flat.extend(_half_kp_features(board, not board.turn))
            us_off.append(len(us_flat))
            them_off.append(len(them_flat))
            targets.append(_target(record, board))
    us = (np.frombuffer(us_flat, dtype=np.intc), np.frombuffer(us_off, dtype=np.int64))
    them = (np.frombuffer(them_flat, dtype=np.intc), np.frombuffer(them_off, dtype=np.int64))
    return fens, us, them, np.array(targets, dtype=np.float32)


def _gather(feats, indices):
    flat, off = feats
    starts, ends = off[indices], off[indices + 1]
    idx = np.concatenate([flat[s:e] for s, e in zip(starts, ends)])
    offsets = np.concatenate(([0], np.cumsum(ends - starts)[:-1]))
    return torch.from_numpy(idx.astype(np.int64)), torch.from_numpy(offsets.astype(np.int64))


def _make_batch(indices, feats_a, feats_b, targets, scale):
    a_idx, a_off = _gather(feats_a, indices)
    b_idx, b_off = _gather(feats_b, indices)
    y = torch.from_numpy(targets[indices] / scale)
    return a_idx, a_off, b_idx, b_off, y


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
    fens, us_feats, them_feats, targets = _load(args.data)
    n = len(fens)
    print(f"{n} positions encodees", flush=True)

    rng = np.random.default_rng(0)
    idx = np.arange(n)
    rng.shuffle(idx)
    # Plafonne : au-dela de 100k positions de test la mesure ne gagne plus rien
    # en precision, et evaluate() en Python coute cher sur tout le jeu de test.
    n_test = min(int(n * 0.2), 100_000)
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
        np.array([evaluate(chess.Board(fens[i])) for i in test_idx], dtype=np.float32), -CP_CLIP, CP_CLIP
    )

    print("\n--- Comparaison sur le meme jeu de test (point de vue camp au trait) ---")
    print(f"{'moyenne (naif)':28s} RMSE={_rmse(mean_pred, y_test):7.1f}")
    print(f"{'evaluate() actuel':28s} RMSE={_rmse(handcrafted_pred, y_test):7.1f}  R2={_r2(handcrafted_pred, y_test):.3f}")
    print(f"{'NNUE (halfkp 128x2-32-32)':28s} RMSE={_rmse(preds, y_test):7.1f}  R2={_r2(preds, y_test):.3f}")

    torch.save(model.state_dict(), args.out)
    print(f"\nmodele sauvegarde : {args.out}")


if __name__ == "__main__":
    main()
