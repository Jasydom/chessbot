"""Courbes d'apprentissage NNUE : RMSE test (centipions) en fonction du nombre
de positions vues, pour plusieurs tailles d'accumulateur.

Meme jeu de donnees, meme split train/test (seed 0, 20 %) et meme protocole
que `tools/train_nnue.py` ; la difference est qu'on mesure le RMSE test a des
points regulierement espaces (echelle geometrique) pendant l'entrainement au
lieu de le calculer une seule fois a la fin. `evaluate()` et la moyenne du
train servent de references horizontales.

"Positions vues" est cumule sur les epochs : une position revue a l'epoch 2
compte a nouveau (le dataset est un ensemble de positions independantes, pas
de parties).

Usage (depuis la racine du projet, dans un environnement avec torch) :
    python -m tools.train_nnue_curves --acc-sizes 32 64 128 256 --epochs 10
puis :
    python -m tools.plot_nnue_curves
"""

from __future__ import annotations

import argparse
import json
import time

import numpy as np
import torch
from torch import nn

from app.bots.evaluation import evaluate
from app.bots.nnue_eval import NNUE
from tools.train_nnue import CP_CLIP, _load, _make_batch, _rmse

SCALE = 100.0
EVAL_BATCH = 4096


def _eval_steps(total_steps: int, steps_per_epoch: int, n_points: int) -> set[int]:
    """Pas d'entrainement (1-indexes) apres lesquels on mesure le RMSE test :
    grille geometrique (la courbe chute vite au debut) + fin de chaque epoch."""
    geometric = {int(round(s)) for s in np.geomspace(1, total_steps, n_points)}
    epoch_ends = set(range(steps_per_epoch, total_steps + 1, steps_per_epoch))
    return geometric | epoch_ends


def _test_rmse(model: nn.Module, test_batches, y_test: np.ndarray) -> float:
    model.eval()
    with torch.no_grad():
        preds = np.concatenate([model(*batch).numpy() * SCALE for batch in test_batches])
    model.train()
    return _rmse(preds, y_test)


def _train_one(acc_size, args, train_idx, test_batches, y_test, feats_us, feats_them, targets):
    torch.manual_seed(0)
    rng = np.random.default_rng(1)
    model = NNUE(acc_size=acc_size)
    n_params = sum(p.numel() for p in model.parameters())
    opt = torch.optim.Adam(model.parameters(), lr=args.lr)
    loss_fn = nn.MSELoss()

    steps_per_epoch = -(-len(train_idx) // args.batch_size)
    total_steps = args.epochs * steps_per_epoch
    eval_at = _eval_steps(total_steps, steps_per_epoch, args.n_points)

    positions, rmses = [], []
    seen = 0
    step = 0
    t0 = time.time()
    order = train_idx.copy()
    for epoch in range(args.epochs):
        rng.shuffle(order)
        for start in range(0, len(order), args.batch_size):
            batch = order[start : start + args.batch_size]
            a_idx, a_off, b_idx, b_off, y = _make_batch(batch, feats_us, feats_them, targets, SCALE)
            opt.zero_grad()
            loss = loss_fn(model(a_idx, a_off, b_idx, b_off), y)
            loss.backward()
            opt.step()
            seen += len(batch)
            step += 1
            if step in eval_at:
                positions.append(seen)
                rmses.append(_test_rmse(model, test_batches, y_test))
        print(
            f"  acc={acc_size:3d}  epoch {epoch + 1}/{args.epochs}  "
            f"vues={seen:>8d}  RMSE test={rmses[-1]:6.1f} cp  ({time.time() - t0:.0f}s)",
            flush=True,
        )
    return {"acc_size": acc_size, "params": n_params, "positions": positions, "rmse": rmses}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="data/eval_sample.jsonl")
    parser.add_argument("--acc-sizes", type=int, nargs="+", default=[32, 64, 128, 256])
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=1024)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--n-points", type=int, default=40, help="points de mesure par courbe (echelle geometrique)")
    parser.add_argument("--out", default="data/nnue_curves.json")
    args = parser.parse_args()

    print("chargement + encodage HalfKP...", flush=True)
    boards, feats_us, feats_them, targets = _load(args.data)
    n = len(boards)

    # Meme split que tools/train_nnue.py.
    rng = np.random.default_rng(0)
    idx = np.arange(n)
    rng.shuffle(idx)
    n_test = int(n * 0.2)
    test_idx, train_idx = idx[:n_test], idx[n_test:]
    y_test = targets[test_idx]
    print(f"{n} positions : {len(train_idx)} train / {len(test_idx)} test", flush=True)

    test_batches = [
        _make_batch(test_idx[s : s + EVAL_BATCH], feats_us, feats_them, targets, SCALE)[:4]
        for s in range(0, len(test_idx), EVAL_BATCH)
    ]

    references = {
        "mean": _rmse(np.full_like(y_test, targets[train_idx].mean()), y_test),
        "evaluate": _rmse(
            np.clip(np.array([evaluate(boards[i]) for i in test_idx], dtype=np.float32), -CP_CLIP, CP_CLIP),
            y_test,
        ),
    }
    print(f"references : moyenne={references['mean']:.1f}  evaluate()={references['evaluate']:.1f}", flush=True)

    result = {
        "meta": {
            "n_train": int(len(train_idx)),
            "n_test": int(len(test_idx)),
            "epochs": args.epochs,
            "batch_size": args.batch_size,
            "lr": args.lr,
            "cp_clip": CP_CLIP,
        },
        "references": references,
        "runs": [],
    }
    for acc_size in args.acc_sizes:
        print(f"\n== NNUE halfkp-{acc_size}x2-32-32", flush=True)
        result["runs"].append(_train_one(acc_size, args, train_idx, test_batches, y_test, feats_us, feats_them, targets))
        with open(args.out, "w", encoding="utf-8") as f:  # ecrit apres chaque modele : rien perdu si on interrompt
            json.dump(result, f)
    print(f"\ncourbes sauvegardees : {args.out}")


if __name__ == "__main__":
    main()
