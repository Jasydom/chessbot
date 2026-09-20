"""Evaluation par reseau HalfKP (prototype NNUE), chargee depuis un modele
entraine par `tools/train_nnue.py`.

Isole du reste de `app/bots` : ce module importe `torch`, absent de
`requirements.txt` (l'app deployee n'en a pas besoin). Il ne sert que pour
comparer la force reelle de ce modele a celle de l'eval handcrafted, via
`tools/arena_nnue.py`. Rien dans `app/bots/__init__.py` ne l'importe, donc
son absence de torch en prod ne casse rien.

L'encodage des features doit rester identique a celui utilise pour
l'entrainement (`tools/train_nnue.py`) : toute divergence rendrait le modele
charge silencieusement incoherent avec ses poids.
"""

from __future__ import annotations

import chess
import torch
from torch import nn

CP_CLIP = 1000
ACC_SIZE = 128
NUM_FEATURES = 64 * 64 * 10  # HalfKP : 64 cases de roi x 64 cases x 5 types x 2 (ami/ennemi)
_TYPE_IDX = {chess.PAWN: 0, chess.KNIGHT: 1, chess.BISHOP: 2, chess.ROOK: 3, chess.QUEEN: 4}


def half_kp_features(board: chess.Board, perspective: chess.Color) -> list[int]:
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


class NNUE(nn.Module):
    """halfkp-128x2-32-32 : deux accumulateurs de 128 (poids partages), puis
    un petit MLP. Le biais de l'accumulateur est ajoute une seule fois par
    perspective (biais de neurone, pas de feature), comme dans NNUE."""

    def __init__(self, num_features: int = NUM_FEATURES, acc_size: int = ACC_SIZE):
        super().__init__()
        self.embed = nn.EmbeddingBag(num_features, acc_size, mode="sum")
        # ~30 features actives sommees puis ClippedReLU sur [0,1] : avec l'init
        # N(0,1) par defaut, ~90 % des unites saturent des le depart (gradient
        # nul) et le reseau n'apprend pas le materiel. Init petite + biais centre.
        nn.init.normal_(self.embed.weight, mean=0.0, std=0.05)
        self.acc_bias = nn.Parameter(torch.full((acc_size,), 0.5))
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


def load_evaluate_fn(model_path: str, scale: float = 100.0):
    """Charge le modele et renvoie une fonction `evaluate(board) -> int`,
    meme signature que `app.bots.evaluation.evaluate` (score cote camp au
    trait, en centipions). Un modele par appel : pas fait pour la vitesse,
    seulement pour mesurer la force en partie via l'arene.
    """
    model = NNUE()
    model.load_state_dict(torch.load(model_path, map_location="cpu"))
    model.eval()

    def evaluate(board: chess.Board) -> int:
        us = half_kp_features(board, board.turn)
        them = half_kp_features(board, not board.turn)
        us_idx = torch.tensor(us, dtype=torch.long)
        them_idx = torch.tensor(them, dtype=torch.long)
        zero_off = torch.tensor([0], dtype=torch.long)
        with torch.no_grad():
            score = model(us_idx, zero_off, them_idx, zero_off).item() * scale
        return int(max(-CP_CLIP, min(CP_CLIP, score)))

    return evaluate
