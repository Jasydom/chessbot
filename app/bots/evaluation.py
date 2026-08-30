"""Evaluation statique d'une position.

Volontairement isole du module de recherche : `minimax.py` ne sait rien de la
facon dont un score est calcule, il sait seulement qu'un score positif est bon
pour le camp au trait. Un reseau de neurones pourra donc remplacer ce fichier
sans toucher a l'alpha-beta.

Le bareme est celui de la "Simplified Evaluation Function" (chessprogramming
wiki) : valeur materielle + table piece/case. Deux tables existent pour le roi,
une de milieu de partie (roi a l'abri derriere ses pions) et une de finale (roi
actif au centre) ; on interpole entre les deux selon le materiel restant, sinon
le bot garde son roi dans un coin en finale de pions.
"""

import chess

# Le roi vaut 0 : il est toujours present des deux cotes, sa valeur s'annule.
PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}

# Poids de chaque piece dans le calcul de la phase de jeu (24 = position initiale).
_PHASE_WEIGHTS = {
    chess.PAWN: 0,
    chess.KNIGHT: 1,
    chess.BISHOP: 1,
    chess.ROOK: 2,
    chess.QUEEN: 4,
    chess.KING: 0,
}
_TOTAL_PHASE = 24

BISHOP_PAIR_MG = 30
BISHOP_PAIR_EG = 45

# Tables piece/case, ecrites du point de vue des Blancs et en lecture visuelle :
# la premiere ligne est la 8e rangee (a8..h8), la derniere est la 1re (a1..h1).
# La grille passe par une chaine plutot que par une liste de litteraux : c'est
# le seul moyen de garder les colonnes alignees sans que les outils de style ne
# reformatent l'echiquier en pave illisible.


def _grid(text: str) -> list[int]:
    values = [int(token) for token in text.split()]
    assert len(values) == 64, f"une table doit couvrir 64 cases, recu {len(values)}"
    return values


_PST_PAWN = _grid("""
       0    0    0    0    0    0    0    0
      50   50   50   50   50   50   50   50
      10   10   20   30   30   20   10   10
       5    5   10   25   25   10    5    5
       0    0    0   20   20    0    0    0
       5   -5  -10    0    0  -10   -5    5
       5   10   10  -20  -20   10   10    5
       0    0    0    0    0    0    0    0
""")

_PST_KNIGHT = _grid("""
     -50  -40  -30  -30  -30  -30  -40  -50
     -40  -20    0    0    0    0  -20  -40
     -30    0   10   15   15   10    0  -30
     -30    5   15   20   20   15    5  -30
     -30    0   15   20   20   15    0  -30
     -30    5   10   15   15   10    5  -30
     -40  -20    0    5    5    0  -20  -40
     -50  -40  -30  -30  -30  -30  -40  -50
""")

_PST_BISHOP = _grid("""
     -20  -10  -10  -10  -10  -10  -10  -20
     -10    0    0    0    0    0    0  -10
     -10    0    5   10   10    5    0  -10
     -10    5    5   10   10    5    5  -10
     -10    0   10   10   10   10    0  -10
     -10   10   10   10   10   10   10  -10
     -10    5    0    0    0    0    5  -10
     -20  -10  -10  -10  -10  -10  -10  -20
""")

_PST_ROOK = _grid("""
       0    0    0    0    0    0    0    0
       5   10   10   10   10   10   10    5
      -5    0    0    0    0    0    0   -5
      -5    0    0    0    0    0    0   -5
      -5    0    0    0    0    0    0   -5
      -5    0    0    0    0    0    0   -5
      -5    0    0    0    0    0    0   -5
       0    0    0    5    5    0    0    0
""")

_PST_QUEEN = _grid("""
     -20  -10  -10   -5   -5  -10  -10  -20
     -10    0    0    0    0    0    0  -10
     -10    0    5    5    5    5    0  -10
      -5    0    5    5    5    5    0   -5
       0    0    5    5    5    5    0   -5
     -10    5    5    5    5    5    0  -10
     -10    0    5    0    0    0    0  -10
     -20  -10  -10   -5   -5  -10  -10  -20
""")

_PST_KING_MG = _grid("""
     -30  -40  -40  -50  -50  -40  -40  -30
     -30  -40  -40  -50  -50  -40  -40  -30
     -30  -40  -40  -50  -50  -40  -40  -30
     -30  -40  -40  -50  -50  -40  -40  -30
     -20  -30  -30  -40  -40  -30  -30  -20
     -10  -20  -20  -20  -20  -20  -20  -10
      20   20    0    0    0    0   20   20
      20   30   10    0    0   10   30   20
""")

_PST_KING_EG = _grid("""
     -50  -40  -30  -20  -20  -30  -40  -50
     -30  -20  -10    0    0  -10  -20  -30
     -30  -10   20   30   30   20  -10  -30
     -30  -10   30   40   40   30  -10  -30
     -30  -10   30   40   40   30  -10  -30
     -30  -10   20   30   30   20  -10  -30
     -30  -30    0    0    0    0  -30  -30
     -50  -30  -30  -30  -30  -30  -30  -50
""")


_PST_MG = {
    chess.PAWN: _PST_PAWN,
    chess.KNIGHT: _PST_KNIGHT,
    chess.BISHOP: _PST_BISHOP,
    chess.ROOK: _PST_ROOK,
    chess.QUEEN: _PST_QUEEN,
    chess.KING: _PST_KING_MG,
}


def _build_common(color: chess.Color) -> list[list[int]]:
    """Tableaux [type de piece][case] pour tout le monde sauf le roi.

    On y fusionne la valeur materielle et le bonus positionnel, et on y applique
    le signe : les tables noires sont deja negatives. `evaluate` n'a donc plus
    qu'a additionner des entiers. Ces pieces-la ont la meme table en milieu de
    partie et en finale, d'ou un seul jeu de tables : seul le roi est interpole.

    Le retournement : `chess.A1 == 0` mais nos tables commencent en a8, d'ou le
    `sq ^ 56` pour les Blancs. Pour les Noirs, `sq` brut fait office de miroir
    vertical (la case a8 d'un Noir joue le role de la case a1 d'un Blanc).
    """
    tables: list[list[int]] = [[] for _ in range(len(chess.PIECE_TYPES) + 1)]
    for piece_type in _NON_KING:
        base = PIECE_VALUES[piece_type]
        table = _PST_MG[piece_type]
        if color == chess.WHITE:
            tables[piece_type] = [base + table[sq ^ 56] for sq in range(64)]
        else:
            tables[piece_type] = [-(base + table[sq]) for sq in range(64)]
    return tables


def _build_king(table: list[int], color: chess.Color) -> list[int]:
    if color == chess.WHITE:
        return [table[sq ^ 56] for sq in range(64)]
    return [-table[sq] for sq in range(64)]


_NON_KING = (chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN)

# Indexes par [couleur][type de piece][case]. `chess.WHITE` vaut True == 1.
_COMMON = [_build_common(chess.BLACK), _build_common(chess.WHITE)]
_KING_MG = [_build_king(_PST_KING_MG, chess.BLACK), _build_king(_PST_KING_MG, chess.WHITE)]
_KING_EG = [_build_king(_PST_KING_EG, chess.BLACK), _build_king(_PST_KING_EG, chess.WHITE)]


def evaluate(board: chess.Board) -> int:
    """Score de la position en centipions, du point de vue du camp au trait.

    Positif = le camp au trait est mieux. C'est la convention attendue par le
    negamax : elle evite d'avoir a manipuler un signe a chaque niveau.

    Fonction la plus chaude du moteur (appelee a chaque feuille) : les bitboards
    sont parcourus a la main plutot qu'avec `chess.scan_forward`, dont le cout
    d'appel de generateur dominait le profil.
    """
    common = 0
    phase = 0
    bishops = [0, 0]

    for color in (chess.WHITE, chess.BLACK):
        tables = _COMMON[color]
        for piece_type in _NON_KING:
            bb = board.pieces_mask(piece_type, color)
            if not bb:
                continue
            table = tables[piece_type]
            weight = _PHASE_WEIGHTS[piece_type]
            count = 0
            while bb:
                lsb = bb & -bb
                common += table[lsb.bit_length() - 1]
                bb ^= lsb
                count += 1
            phase += weight * count
            if piece_type == chess.BISHOP:
                bishops[color] = count

    white_king = board.king(chess.WHITE)
    black_king = board.king(chess.BLACK)
    mg = common + _KING_MG[chess.WHITE][white_king] + _KING_MG[chess.BLACK][black_king]
    eg = common + _KING_EG[chess.WHITE][white_king] + _KING_EG[chess.BLACK][black_king]

    # La paire de fous vaut plus que la somme de ses parties, surtout en finale.
    if bishops[chess.WHITE] >= 2:
        mg += BISHOP_PAIR_MG
        eg += BISHOP_PAIR_EG
    if bishops[chess.BLACK] >= 2:
        mg -= BISHOP_PAIR_MG
        eg -= BISHOP_PAIR_EG

    # Une sous-promotion peut faire depasser la phase initiale : on la borne.
    if phase > _TOTAL_PHASE:
        phase = _TOTAL_PHASE
    score = (mg * phase + eg * (_TOTAL_PHASE - phase)) // _TOTAL_PHASE

    return score if board.turn == chess.WHITE else -score
