"""Construit un livre d'ouvertures Polyglot (.bin) a partir de lignes ecrites a la main.

lichess-bot sait lire un livre Polyglot nativement (voir `polyglot:` dans
lichess-bot-service/config.yml) : il choisit le coup du moteur tant que la position
est dans le livre, ce qui evite de faire tourner la recherche (et le JIT PyPy encore
froid, cf. VERSIONS.md) sur les premiers coups d'une partie.

Usage:
    python -m tools.build_book [--out lichess-bot-service/book.bin]
"""

from __future__ import annotations

import argparse
import struct
from pathlib import Path

import chess
import chess.polyglot

# Chaque ligne est une suite de coups en SAN, avec un poids (popularite relative,
# arbitraire ici). Les positions partagees par plusieurs lignes cumulent les poids
# de chaque coup vu a cette position : c'est normal et voulu pour un livre Polyglot.
OPENING_LINES: list[tuple[str, list[str], int]] = [
    ("Ruy Lopez, Morphy", "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7".split(), 12),
    ("Ruy Lopez, Berlin", "e4 e5 Nf3 Nc6 Bb5 Nf6".split(), 6),
    ("Giuoco Piano", "e4 e5 Nf3 Nc6 Bc4 Bc5".split(), 10),
    ("Two Knights", "e4 e5 Nf3 Nc6 Bc4 Nf6".split(), 6),
    ("Scotch", "e4 e5 Nf3 Nc6 d4 exd4 Nxd4".split(), 6),
    ("Petrov", "e4 e5 Nf3 Nf6".split(), 5),
    ("Vienna", "e4 e5 Nc3 Nf6".split(), 3),
    ("Bishop's Opening", "e4 e5 Bc4 Nf6".split(), 2),
    ("King's Gambit", "e4 e5 f4 exf4".split(), 2),
    ("Sicilian, Open", "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3".split(), 14),
    ("Sicilian, Najdorf", "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6".split(), 8),
    ("Sicilian, Taimanov", "e4 c5 Nf3 e6".split(), 6),
    ("Sicilian, Rossolimo", "e4 c5 Nf3 Nc6 Bb5".split(), 4),
    ("Sicilian, Closed", "e4 c5 Nc3".split(), 3),
    ("Sicilian, Alapin", "e4 c5 c3".split(), 4),
    ("French, Classical", "e4 e6 d4 d5 Nc3 Nf6".split(), 10),
    ("French, Tarrasch", "e4 e6 d4 d5 Nd2".split(), 4),
    ("Caro-Kann, Classical", "e4 c6 d4 d5 Nc3 dxe4 Nxe4".split(), 8),
    ("Caro-Kann, Advance", "e4 c6 d4 d5 e5 Bf5".split(), 5),
    ("Pirc", "e4 d6 d4 Nf6 Nc3 g6".split(), 4),
    ("Modern Defense", "e4 g6".split(), 2),
    ("Scandinavian", "e4 d5 exd5 Qxd5 Nc3 Qa5".split(), 4),
    ("Alekhine", "e4 Nf6 e5 Nd5 d4 d6".split(), 3),
    ("Queen's Gambit Declined", "d4 d5 c4 e6 Nc3 Nf6".split(), 10),
    ("Queen's Gambit Accepted", "d4 d5 c4 dxc4 Nf3 Nf6".split(), 4),
    ("Slav", "d4 d5 c4 c6 Nf3 Nf6".split(), 8),
    ("King's Indian", "d4 Nf6 c4 g6 Nc3 Bg7 e4 d6".split(), 8),
    ("Nimzo-Indian", "d4 Nf6 c4 e6 Nc3 Bb4".split(), 8),
    ("Queen's Indian", "d4 Nf6 c4 e6 Nf3 b6".split(), 5),
    ("Grunfeld", "d4 Nf6 c4 g6 Nc3 d5".split(), 5),
    ("Dutch", "d4 f5".split(), 3),
    ("Benoni", "d4 Nf6 c4 c5".split(), 3),
    ("London System", "d4 d5 Nf3 Nf6 Bf4".split(), 6),
    ("English, Symmetric", "c4 c5 Nf3 Nf6".split(), 4),
    ("English, Reversed Sicilian", "c4 e5 Nc3 Nf6".split(), 4),
    ("English vs d5", "c4 d5".split(), 2),
    ("Reti", "Nf3 d5 c4".split(), 3),
]

# Format d'une entree Polyglot : cle Zobrist (8o), coup (2o), poids (2o), "learn" (4o).
_ENTRY = struct.Struct(">QHHI")

_PROMOTION_BITS = {
    None: 0,
    chess.KNIGHT: 1,
    chess.BISHOP: 2,
    chess.ROOK: 3,
    chess.QUEEN: 4,
}


def _encode_move(board: chess.Board, move: chess.Move) -> int:
    """Encode un coup au format Polyglot (voir chess.polyglot.MemoryMappedReader)."""
    to_square = move.to_square
    if board.is_castling(move):
        # Polyglot encode le roque comme un roi qui va sur la case de sa propre tour
        # (norme pre-Chess960), pas sur sa case d'arrivee habituelle (g1/c1/g8/c8).
        rook_file = 7 if board.is_kingside_castling(move) else 0
        to_square = chess.square(rook_file, chess.square_rank(move.from_square))
    promotion_bits = _PROMOTION_BITS[move.promotion]
    return (promotion_bits << 12) | (move.from_square << 6) | to_square


def build_entries(lines: list[tuple[str, list[str], int]]) -> list[tuple[int, int, int]]:
    """Rejoue chaque ligne et cumule (cle, coup_encode, poids) par position+coup."""
    weights: dict[tuple[int, int], int] = {}
    for name, sans, weight in lines:
        board = chess.Board()
        for san in sans:
            try:
                move = board.parse_san(san)
            except ValueError as exc:
                raise ValueError(f"{name!r} : coup invalide {san!r} ({exc})") from exc
            key = chess.polyglot.zobrist_hash(board)
            raw_move = _encode_move(board, move)
            weights[(key, raw_move)] = weights.get((key, raw_move), 0) + weight
            board.push(move)
    return [(key, raw_move, weight) for (key, raw_move), weight in weights.items()]


def write_book(entries: list[tuple[int, int, int]], out_path: Path) -> None:
    # Un livre Polyglot doit etre trie par cle croissante (recherche par dichotomie).
    entries = sorted(entries, key=lambda entry: entry[0])
    with out_path.open("wb") as book_file:
        for key, raw_move, weight in entries:
            book_file.write(_ENTRY.pack(key, raw_move, weight, 0))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("lichess-bot-service/book.bin"),
        help="chemin du fichier .bin genere",
    )
    args = parser.parse_args()

    entries = build_entries(OPENING_LINES)
    write_book(entries, args.out)
    positions = len({key for key, _, _ in entries})
    print(f"{args.out} : {len(entries)} coups sur {positions} positions ({len(OPENING_LINES)} lignes)")


if __name__ == "__main__":
    main()
