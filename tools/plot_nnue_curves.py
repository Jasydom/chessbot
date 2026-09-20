"""Trace les courbes d'apprentissage produites par `tools/train_nnue_curves.py` :
RMSE test (centipions) en fonction du nombre de positions vues, une courbe par
taille d'accumulateur, avec `evaluate()` et la moyenne naive en references.

Usage (depuis la racine du projet, avec matplotlib) :
    python -m tools.plot_nnue_curves --data data/nnue_curves.json --out data/nnue_curves.png
"""

from __future__ import annotations

import argparse
import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import FuncFormatter

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
GRID = "#ecebe8"
#: Rampe de bleus (etapes 250 / 400 / 550 / 700 de la palette de reference) :
#: la taille d'accumulateur est ordonnee, donc plus grand = plus fonce.
BLUE_RAMP = ["#86b6ef", "#3987e5", "#1c5cab", "#0d366b"]


def _series_colors(n: int) -> list[str]:
    if n > len(BLUE_RAMP):
        raise SystemExit(f"{n} courbes : la rampe ordinale valide n'en gere que {len(BLUE_RAMP)}")
    return [BLUE_RAMP[i] for i in np.round(np.linspace(0, len(BLUE_RAMP) - 1, n)).astype(int)]


def _fmt_positions(x: float, _pos=None) -> str:
    if x >= 1e6:
        return f"{x / 1e6:g} M"
    if x >= 1e3:
        return f"{x / 1e3:g} k"
    return f"{x:g}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="data/nnue_curves.json")
    parser.add_argument("--out", default="data/nnue_curves.png")
    args = parser.parse_args()

    with open(args.data, encoding="utf-8") as f:
        data = json.load(f)
    meta, refs, runs = data["meta"], data["references"], data["runs"]
    colors = _series_colors(len(runs))

    fig, ax = plt.subplots(figsize=(10, 6), dpi=150, facecolor=SURFACE)
    ax.set_facecolor(SURFACE)

    # References : lignes horizontales en encre secondaire, etiquetees directement.
    x_max = max(max(r["positions"]) for r in runs)
    x_min = min(min(r["positions"]) for r in runs)
    for key, label, style in (("mean", "moyenne du train (naïf)", (0, (1, 2))), ("evaluate", "evaluate() actuel", (0, (5, 3)))):
        ax.axhline(refs[key], color=INK_SECONDARY, lw=1.5, linestyle=style, zorder=1)
        ax.text(x_min, refs[key], f"{label} : {refs[key]:.0f} cp", color=INK_SECONDARY, fontsize=9,
                va="bottom", ha="left", zorder=4)

    for run, color in zip(runs, colors):
        pos, rmse = np.array(run["positions"]), np.array(run["rmse"])
        label = f"acc. {run['acc_size']} ({run['params'] / 1e6:.1f} M)"
        ax.plot(pos, rmse, color=color, lw=2, solid_capstyle="round", solid_joinstyle="round", label=label, zorder=3)
        ax.plot(pos[-1], rmse[-1], "o", ms=8, color=color, markeredgecolor=SURFACE, markeredgewidth=2, zorder=5)

    best = min(runs, key=lambda r: r["rmse"][-1])
    ax.annotate(f"{best['rmse'][-1]:.0f} cp", (best["positions"][-1], best["rmse"][-1]), xytext=(8, 0),
                textcoords="offset points", color=INK, fontsize=10, va="center", fontweight="bold")

    ax.set_xscale("log")
    ax.xaxis.set_major_formatter(FuncFormatter(_fmt_positions))
    ax.set_xlim(x_min * 0.9, x_max * 1.8)
    ax.set_ylim(top=refs["mean"] * 1.05)
    ax.set_xlabel("Positions vues (cumul sur les epochs, échelle log)", color=INK_SECONDARY, fontsize=10)
    ax.set_ylabel("RMSE sur le jeu de test (centipions)", color=INK_SECONDARY, fontsize=10)
    ax.grid(True, which="major", color=GRID, lw=1, linestyle="-")
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK_SECONDARY, labelsize=9, length=0)

    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.13), ncol=len(runs), frameon=False, fontsize=9,
              labelcolor=INK_SECONDARY, handlelength=1.6, columnspacing=1.8)

    n_train, n_test = (f"{meta[k]:,}".replace(",", " ") for k in ("n_train", "n_test"))
    fig.text(0.075, 0.955, "NNUE : erreur d'évaluation vs positions vues", color=INK, fontsize=14, fontweight="bold", ha="left")
    fig.text(0.075, 0.918,
             f"Cible : éval. Stockfish, écrêtée à ±{meta['cp_clip']} cp, du point de vue du camp au trait. "
             f"Réseau HalfKP « accumulateur ×2 - 32 - 32 ».",
             color=INK_SECONDARY, fontsize=9, ha="left")
    fig.text(0.075, 0.892,
             f"{n_train} positions train / {n_test} test · batch {meta['batch_size']} · lr {meta['lr']:g} · {meta['epochs']} epochs"
             " · légende : taille de l'accumulateur (paramètres)",
             color=INK_SECONDARY, fontsize=9, ha="left")
    fig.subplots_adjust(left=0.075, right=0.97, top=0.85, bottom=0.2)
    fig.savefig(args.out, facecolor=SURFACE)
    print(f"graphe sauvegarde : {args.out}")

    # Vue tableau : les valeurs finales (le graphe n'etiquette pas chaque courbe).
    print(f"\n{'modele':>14s} {'params':>10s} {'RMSE final (cp)':>16s} {'vs evaluate()':>14s}")
    for run in runs:
        rm = run["rmse"][-1]
        print(f"{'acc. ' + str(run['acc_size']):>14s} {run['params']:>10,d} {rm:>16.1f} {rm - refs['evaluate']:>+14.1f}".replace(",", " "))
    print(f"{'evaluate()':>14s} {'':>10s} {refs['evaluate']:>16.1f}")
    print(f"{'moyenne':>14s} {'':>10s} {refs['mean']:>16.1f}")


if __name__ == "__main__":
    main()
