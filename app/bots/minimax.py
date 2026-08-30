"""Moteur de recherche : negamax + elagage alpha-beta.

Les briques, dans l'ordre de rentabilite :

- **Approfondissement iteratif** : on cherche a profondeur 1, 2, 3... jusqu'a
  epuisement du budget temps. Le cout des profondeurs abandonnees est marginal
  (l'arbre croit geometriquement) et cela donne deux choses gratuitement : un
  coup jouable a tout instant, et un excellent ordre de coups pour l'iteration
  suivante.
- **Tri des coups** : l'alpha-beta ne coupe que si les bons coups arrivent en
  premier. Coup de la table de transposition, puis captures (MVV-LVA), puis
  killers, puis heuristique d'historique.
- **Recherche de quiescence** : on ne s'arrete jamais au milieu d'une sequence
  de captures, sinon le moteur croit gagner une dame juste avant de la reperdre
  (effet d'horizon).
- **Table de transposition** : la meme position est atteinte par plusieurs ordres
  de coups ; on memorise son score.
- **Null move pruning** : si passer son tour laisse quand meme la position
  au-dessus de beta, inutile de la fouiller.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass

import chess

from app.bots.evaluation import PIECE_VALUES, evaluate

MATE_SCORE = 1_000_000
#: Au-dela, un score encode un mat et non une evaluation materielle.
MATE_THRESHOLD = MATE_SCORE - 1_000
INFINITY = MATE_SCORE + 1
MAX_PLY = 64

# Bornes stockees dans la table de transposition.
_EXACT, _LOWER, _UPPER = 0, 1, 2

# Reduction appliquee par le null move pruning.
_NULL_MOVE_REDUCTION = 2
# Profondeur minimale pour tenter un null move. Le seuil garantit que la
# recherche reduite garde au moins un ply reel : si elle tombait a zero,
# elle se resumerait a une evaluation materielle, et un sacrifice gagnant
# passerait pour une catastrophe. C'est exactement ce qui faisait rater a la
# profondeur 4 un mat que la profondeur 3 trouvait.
_NULL_MOVE_MIN_DEPTH = _NULL_MOVE_REDUCTION + 2

# Late Move Reductions : rang a partir duquel un coup calme est sonde moins
# profondement, et rang a partir duquel la reduction passe a deux plies.
_LMR_MIN_MOVE = 3
_LMR_DEEP_MOVE = 6

# Ordre de grandeur des scores de tri. L'historique est plafonne sous les
# killers pour ne jamais passer devant eux.
_TT_MOVE_SCORE = 1_000_000
_CAPTURE_SCORE = 100_000
_PROMOTION_SCORE = 90_000
_KILLER_SCORES = (80_000, 79_000)
_HISTORY_CAP = 70_000

#: Valeurs simplifiees pour le tri MVV-LVA (victime la plus grosse, agresseur
#: le plus petit). Un ordre suffit, la precision materielle est inutile ici.
_MVV_LVA = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 20,
}

#: Marge de delta pruning : en quiescence, on ignore une capture qui, meme en
#: gagnant la piece prise, ne peut pas remonter jusqu'a alpha.
_DELTA_MARGIN = 200


def _transposition_key(board: chess.Board):
    """Cle identifiant une position pour la table de transposition.

    `Board._transposition_key()` est prefixe d'un underscore mais c'est l'API
    interne stable et rapide de python-chess (un tuple de bitboards, sans
    collision). On retombe sur le hash Zobrist public si elle venait a bouger.
    """
    return board._transposition_key()


try:
    _transposition_key(chess.Board())
except AttributeError:  # pragma: no cover - filet de securite
    from chess.polyglot import zobrist_hash as _transposition_key


class _TimeUp(Exception):
    """Levee pour interrompre la recherche des que le budget est epuise."""


class _Search:
    """Etat d'une recherche. Instancie a chaque coup : aucun etat n'est partage
    entre deux requetes, ce qui rend le bot utilisable depuis le threadpool de
    FastAPI sans verrou.
    """

    def __init__(
        self,
        board: chess.Board,
        deadline: float,
        max_depth: int,
        use_quiescence: bool = True,
    ) -> None:
        self.board = board
        self.deadline = deadline
        self.max_depth = max_depth
        self.use_quiescence = use_quiescence

        self.tt: dict[object, tuple[int, int, int, chess.Move | None]] = {}
        # Les extensions d'echec font grimper `ply` au-dela de `max_depth` :
        # on dimensionne large plutot que de borner l'indexation a chaud.
        self.killers: list[list[chess.Move | None]] = [
            [None, None] for _ in range(2 * MAX_PLY + 8)
        ]
        self.history: dict[tuple[bool, int, int], int] = {}

        self.nodes = 0
        self.depth_reached = 0
        self.score = 0
        #: Meilleur coup de l'iteration en cours, mis a jour au fil de l'eau
        #: pour etre exploitable si le temps tombe en plein milieu.
        self._partial_best: chess.Move | None = None

    # ------------------------------------------------------------------ API

    def run(self) -> chess.Move | None:
        best_move: chess.Move | None = None

        for depth in range(1, self.max_depth + 1):
            self._partial_best = None
            try:
                move, score = self._search_root(depth, best_move)
            except _TimeUp:
                # L'iteration est incomplete, mais les coups deja explores l'ont
                # ete a cette profondeur et le meilleur precedent passait en
                # premier : ce resultat partiel vaut mieux que l'ancien.
                if self._partial_best is not None:
                    best_move = self._partial_best
                break

            best_move = move
            self.score = score
            self.depth_reached = depth

            # Mat trouve : creuser davantage ne changera rien.
            if abs(score) > MATE_THRESHOLD:
                break
            # Inutile d'entamer une profondeur qu'on ne finira pas.
            if time.monotonic() >= self.deadline:
                break

        return best_move

    # --------------------------------------------------------------- racine

    def _search_root(self, depth: int, previous_best: chess.Move | None):
        board = self.board
        moves = list(board.legal_moves)

        # Melange avant le tri : le tri est stable, donc les coups juges
        # equivalents gardent cet ordre aleatoire. Sans cela le bot rejouerait
        # exactement la meme partie a chaque fois.
        random.shuffle(moves)
        moves.sort(key=lambda m: self._move_score(m, previous_best, 0), reverse=True)

        alpha = -INFINITY
        best_move: chess.Move | None = None
        best_score = -INFINITY

        for index, move in enumerate(moves):
            board.push(move)
            try:
                if index == 0:
                    score = -self._negamax(depth - 1, -INFINITY, -alpha, 1)
                else:
                    # PVS : on parie que le premier coup est le meilleur et on
                    # teste les suivants en fenetre nulle, bien plus rapide.
                    score = -self._negamax(depth - 1, -alpha - 1, -alpha, 1)
                    if score > alpha:
                        score = -self._negamax(depth - 1, -INFINITY, -alpha, 1)
            finally:
                board.pop()

            if score > best_score:
                best_score = score
                best_move = move
                self._partial_best = move
                if score > alpha:
                    alpha = score

        return best_move, best_score

    # -------------------------------------------------------------- negamax

    def _negamax(self, depth: int, alpha: int, beta: int, ply: int) -> int:
        self.nodes += 1
        self._check_time()

        board = self.board

        if self._is_draw():
            return 0
        if ply >= len(self.killers) - 1:
            return evaluate(board)

        key = _transposition_key(board)
        entry = self.tt.get(key)
        tt_move: chess.Move | None = None

        if entry is not None:
            entry_depth, entry_score, entry_flag, tt_move = entry
            if entry_depth >= depth:
                score = self._from_tt_score(entry_score, ply)
                if entry_flag == _EXACT:
                    return score
                if entry_flag == _LOWER and score > alpha:
                    alpha = score
                elif entry_flag == _UPPER and score < beta:
                    beta = score
                if alpha >= beta:
                    return score

        # Fige apres l'ajustement par la table : c'est bien cet alpha-la que le
        # score final devra depasser pour etre qualifie d'exact.
        alpha_origin = alpha

        if depth <= 0:
            if self.use_quiescence:
                return self._quiescence(alpha, beta, ply)
            return evaluate(board)

        in_check = board.is_check()

        # Null move : on cede le trait. Interdit en echec (illegal), et desactive
        # quand le camp au trait n'a plus que des pions, car en zugzwang passer
        # son tour est un avantage fictif.
        if (
            depth >= _NULL_MOVE_MIN_DEPTH
            and not in_check
            and ply > 0
            and beta < MATE_THRESHOLD
            and self._has_non_pawn_material()
        ):
            board.push(chess.Move.null())
            try:
                score = -self._negamax(
                    depth - 1 - _NULL_MOVE_REDUCTION, -beta, -beta + 1, ply + 1
                )
            finally:
                board.pop()
            if score >= beta:
                return beta

        moves = list(board.legal_moves)
        if not moves:
            # Le mat est mesure en demi-coups : preferer un mat en 3 a un mat
            # en 5, et repousser le sien le plus loin possible.
            return -MATE_SCORE + ply if in_check else 0

        moves.sort(key=lambda m: self._move_score(m, tt_move, ply), reverse=True)

        best_score = -INFINITY
        best_move: chess.Move | None = None

        for index, move in enumerate(moves):
            is_capture = board.is_capture(move)
            board.push(move)
            try:
                # Extension d'echec : une sequence forcee ne doit pas etre
                # tronquee par la limite de profondeur.
                extension = 1 if board.is_check() and ply < MAX_PLY - 8 else 0
                new_depth = depth - 1 + extension

                if index == 0:
                    # Le coup le mieux trie : seul a meriter une fenetre pleine.
                    score = -self._negamax(new_depth, -beta, -alpha, ply + 1)
                else:
                    # LMR : passe les premiers, un coup calme mal classe est
                    # rarement le meilleur. On le sonde en profondeur reduite,
                    # et on ne paie le prix fort que s'il dement le pronostic.
                    reduction = 0
                    if (
                        depth >= 3
                        and index >= _LMR_MIN_MOVE
                        and extension == 0
                        and not in_check
                        and not is_capture
                        and move.promotion is None
                    ):
                        reduction = 1 if index < _LMR_DEEP_MOVE else 2

                    # PVS : on parie que le premier coup est le meilleur et on
                    # teste les suivants en fenetre nulle, bien plus rapide.
                    score = -self._negamax(
                        new_depth - reduction, -alpha - 1, -alpha, ply + 1
                    )
                    if reduction and score > alpha:
                        score = -self._negamax(
                            new_depth, -alpha - 1, -alpha, ply + 1
                        )
                    if alpha < score < beta:
                        score = -self._negamax(new_depth, -beta, -alpha, ply + 1)
            finally:
                board.pop()

            if score > best_score:
                best_score = score
                best_move = move

            if best_score > alpha:
                alpha = best_score

            if alpha >= beta:
                # Coupure : ce coup quiet est bon ici, on s'en souvient pour les
                # positions freres (killer) et pour le tri global (historique).
                if not is_capture and move.promotion is None:
                    self._record_killer(move, ply)
                    history_key = (board.turn, move.from_square, move.to_square)
                    self.history[history_key] = min(
                        self.history.get(history_key, 0) + depth * depth,
                        _HISTORY_CAP,
                    )
                break

        if best_score <= alpha_origin:
            flag = _UPPER
        elif best_score >= beta:
            flag = _LOWER
        else:
            flag = _EXACT
        self.tt[key] = (depth, self._to_tt_score(best_score, ply), flag, best_move)

        return best_score

    # ------------------------------------------------------------ quiescence

    def _quiescence(self, alpha: int, beta: int, ply: int) -> int:
        self.nodes += 1
        self._check_time()

        board = self.board
        stand_pat = evaluate(board)

        # On suppose qu'il existe toujours au moins un coup au moins aussi bon
        # que "ne rien faire" : c'est faux en zugzwang, mais l'approximation est
        # standard et evite d'explorer des positions calmes.
        if stand_pat >= beta:
            return stand_pat
        if stand_pat > alpha:
            alpha = stand_pat
        if ply >= MAX_PLY:
            return stand_pat

        # Uniquement les captures : les coups calmes sont l'affaire du negamax.
        # Les promotions non capturantes echappent donc a la quiescence, c'est
        # la simplification assumee du moteur.
        captures = list(board.generate_legal_captures())
        captures.sort(key=self._capture_score, reverse=True)

        best_score = stand_pat
        for move in captures:
            # Delta pruning : meme en empochant la piece prise sans contrepartie,
            # ce coup ne remonte pas jusqu'a alpha, inutile de l'explorer.
            victim = (
                chess.PAWN
                if board.is_en_passant(move)
                else board.piece_type_at(move.to_square)
            )
            gain = PIECE_VALUES.get(victim, 0)
            if move.promotion:
                gain += PIECE_VALUES[move.promotion] - PIECE_VALUES[chess.PAWN]
            if stand_pat + gain + _DELTA_MARGIN < alpha:
                continue

            board.push(move)
            try:
                score = -self._quiescence(-beta, -alpha, ply + 1)
            finally:
                board.pop()

            if score > best_score:
                best_score = score
            if best_score > alpha:
                alpha = best_score
            if alpha >= beta:
                break

        return best_score

    # ------------------------------------------------------------- outillage

    def _move_score(self, move: chess.Move, tt_move: chess.Move | None, ply: int) -> int:
        if tt_move is not None and move == tt_move:
            return _TT_MOVE_SCORE

        board = self.board
        if board.is_capture(move):
            return _CAPTURE_SCORE + self._capture_score(move)
        if move.promotion:
            return _PROMOTION_SCORE + _MVV_LVA[move.promotion]

        killers = self.killers[ply]
        if move == killers[0]:
            return _KILLER_SCORES[0]
        if move == killers[1]:
            return _KILLER_SCORES[1]

        return self.history.get((board.turn, move.from_square, move.to_square), 0)

    def _capture_score(self, move: chess.Move) -> int:
        """MVV-LVA : prendre gros avec petit d'abord."""
        board = self.board
        victim = (
            chess.PAWN
            if board.is_en_passant(move)
            else board.piece_type_at(move.to_square)
        )
        attacker = board.piece_type_at(move.from_square)
        return 10 * _MVV_LVA.get(victim, 0) - _MVV_LVA.get(attacker, 0)

    def _record_killer(self, move: chess.Move, ply: int) -> None:
        killers = self.killers[ply]
        if killers[0] != move:
            killers[1] = killers[0]
            killers[0] = move

    def _has_non_pawn_material(self) -> bool:
        board = self.board
        own = board.occupied_co[board.turn]
        return bool(own & (board.knights | board.bishops | board.rooks | board.queens))

    def _is_draw(self) -> bool:
        board = self.board
        if board.is_insufficient_material():
            return True
        if board.halfmove_clock >= 100:
            return True
        # Il faut au moins 4 demi-coups reversibles pour repeter une position :
        # ce garde-fou evite de parcourir la pile de coups a chaque noeud.
        if board.halfmove_clock >= 4 and board.is_repetition(2):
            return True
        return False

    def _check_time(self) -> None:
        # Un appel a time.monotonic() par noeud couterait cher : on echantillonne.
        if not self.nodes & 1023 and time.monotonic() >= self.deadline:
            raise _TimeUp

    @staticmethod
    def _to_tt_score(score: int, ply: int) -> int:
        """Rend un score de mat independant de la profondeur ou il a ete trouve.

        Un "mat dans 2 coups d'ici" doit se relire correctement depuis une autre
        branche ou la meme position apparait a une autre profondeur.
        """
        if score > MATE_THRESHOLD:
            return score + ply
        if score < -MATE_THRESHOLD:
            return score - ply
        return score

    @staticmethod
    def _from_tt_score(score: int, ply: int) -> int:
        if score > MATE_THRESHOLD:
            return score - ply
        if score < -MATE_THRESHOLD:
            return score + ply
        return score


@dataclass(frozen=True)
class MinimaxBot:
    """Bot alpha-beta a temps borne.

    L'instance ne porte que de la configuration (elle est gelee) : tout l'etat
    mutable vit dans `_Search`, cree a chaque coup. Plusieurs parties peuvent
    donc taper sur le meme bot en parallele.
    """

    name: str
    label: str
    #: Plafond de profondeur. 64 revient a se laisser guider par le temps seul.
    max_depth: int = MAX_PLY
    #: Budget de reflexion nominal, en secondes.
    time_budget: float = 0.6
    #: Desactiver la quiescence rend le bot nettement plus faible : il gaffe sur
    #: les enfilades de captures. C'est ce qui fait un niveau "facile" credible.
    use_quiescence: bool = True
    #: Fraction du temps restant qu'on s'autorise a bruler sur un coup.
    clock_fraction: float = 1 / 30

    def choose_move(
        self, board: chess.Board, ms_left: int | None = None
    ) -> chess.Move | None:
        legal_moves = list(board.legal_moves)
        if not legal_moves:
            return None
        if len(legal_moves) == 1:
            return legal_moves[0]

        budget = self.time_budget
        if ms_left is not None:
            # On ne depasse jamais une fraction du temps restant : en fin de
            # blitz le bot accelere au lieu de tomber au drapeau.
            budget = min(budget, max(ms_left / 1000 * self.clock_fraction, 0.05))

        # La recherche travaille sur une copie : elle abandonne l'arbre en cours
        # sur _TimeUp sans depiler, et le plateau de l'appelant reste intact.
        search = _Search(
            board.copy(),
            deadline=time.monotonic() + budget,
            max_depth=self.max_depth,
            use_quiescence=self.use_quiescence,
        )
        return search.run() or legal_moves[0]
