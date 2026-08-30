"""Bot de reference : joue un coup legal au hasard.

Sert de temoin pour mesurer la force des autres bots.
"""

import random

import chess


class RandomBot:
    name = "random"
    label = "Aleatoire"

    def choose_move(
        self, board: chess.Board, ms_left: int | None = None
    ) -> chess.Move | None:
        legal_moves = list(board.legal_moves)
        if not legal_moves:
            return None
        return random.choice(legal_moves)
