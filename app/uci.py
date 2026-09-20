"""Moteur UCI : pont entre lichess-bot (ou toute interface UCI) et MinimaxBot.

`lichess-bot` lance cet executable et lui parle en UCI sur stdin/stdout. Ce
script importe directement `MinimaxBot` et traduit les commandes UCI
(`position`, `go`, ...) en appels a `choose_move(board, ms_left)`, sans
dependance reseau.

Lancement : `python app/uci.py` depuis la racine du projet (ou en donnant ce
chemin comme `EngineDir`/executable a lichess-bot).
"""

from __future__ import annotations

import itertools
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chess

from app.bots.minimax import MinimaxBot

ENGINE_NAME = "ChessbotMinimax"
ENGINE_AUTHOR = "Montaigne"

# Plafond de temps large : la vraie limite vient de wtime/btime traduits en
# ms_left, ce time_budget ne doit pas etre la contrainte active sur les
# cadences lentes (rapid/classical).
ENGINE = MinimaxBot(name="uci", label="UCI", time_budget=120.0)

board = chess.Board()

# Positions sur lesquelles on fait chauffer le JIT : ouverture, milieu de
# partie et finale, pour que les trois familles de chemins de code soient
# compilees avant le premier vrai coup.
_WARMUP_FENS = (
    chess.STARTING_FEN,
    "r1bqkb1r/pp1n1ppp/2p1pn2/3p4/2PP4/2N1PN2/PP3PPP/R1BQKB1R w KQkq - 0 6",
    "8/5pk1/6p1/7p/7P/6P1/5PK1/8 w - - 0 1",
)
#: Duree d'une recherche de chauffe : c'est aussi le delai maximal que subit un
#: `go` arrive pendant la chauffe, le temps de la voir s'interrompre.
_WARMUP_SEARCH_SECONDS = 0.1
#: Temps de recherche cumule au-dela duquel le JIT est chaud (mesure avec
#: tools/bench_nps.py : le regime stable arrive apres une quarantaine de
#: secondes de recherche).
_WARMUP_TOTAL_SECONDS = 40.0


class _Warmup:
    """Chauffe le JIT de PyPy pendant que le moteur attend un `go`.

    lichess-bot lance un nouveau moteur a chaque partie, donc le JIT repart a
    froid : les premiers coups tournent 3 a 4 fois moins vite qu'avec CPython.
    On met a profit le temps de reflexion de l'adversaire, pendant lequel le
    moteur est de toute facon inactif. Sous CPython, il n'y a rien a chauffer :
    la classe ne fait alors rien.
    """

    def __init__(self) -> None:
        self._bot = MinimaxBot(name="warmup", label="warmup", time_budget=_WARMUP_SEARCH_SECONDS)
        self._enabled = sys.implementation.name == "pypy"
        self._spent = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self._enabled or self._spent >= _WARMUP_TOTAL_SECONDS:
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Interrompt la chauffe et rend la main une fois la recherche en cours
        terminee (au plus `_WARMUP_SEARCH_SECONDS`), pour ne pas disputer le
        processeur au vrai coup."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join()

    def _run(self) -> None:
        for fen in itertools.cycle(_WARMUP_FENS):
            if self._stop.is_set() or self._spent >= _WARMUP_TOTAL_SECONDS:
                return
            started = time.monotonic()
            self._bot.choose_move(chess.Board(fen))
            self._spent += time.monotonic() - started


WARMUP = _Warmup()


def send(msg: str) -> None:
    print(msg, flush=True)


def handle_position(tokens: list[str]) -> None:
    global board
    if not tokens:
        return

    if tokens[0] == "startpos":
        board = chess.Board()
        rest = tokens[1:]
    elif tokens[0] == "fen":
        fen_tokens = tokens[1:]
        split_at = fen_tokens.index("moves") if "moves" in fen_tokens else len(fen_tokens)
        board = chess.Board(" ".join(fen_tokens[:split_at]))
        rest = fen_tokens[split_at:]
    else:
        return

    if rest and rest[0] == "moves":
        for uci_move in rest[1:]:
            board.push(chess.Move.from_uci(uci_move))


def handle_go(tokens: list[str]) -> None:
    params: dict[str, int] = {}
    i = 0
    while i < len(tokens):
        key = tokens[i]
        if key in ("wtime", "btime", "winc", "binc", "movetime", "depth", "movestogo"):
            if i + 1 < len(tokens):
                params[key] = int(tokens[i + 1])
                i += 2
                continue
        i += 1

    # MinimaxBot ne raisonne qu'en fraction du temps restant (clock_fraction) :
    # pour un `movetime` fixe, on gonfle ms_left par l'inverse de cette
    # fraction pour que le budget resultant retombe exactement sur movetime.
    if "movetime" in params:
        scale = round(1 / ENGINE.clock_fraction)
        ms_left = params["movetime"] * scale
        increment = 0
    else:
        is_white = board.turn == chess.WHITE
        ms_left = params.get("wtime" if is_white else "btime")
        increment = params.get("winc" if is_white else "binc", 0)

    WARMUP.stop()
    move = ENGINE.choose_move(board, ms_left=ms_left, increment_ms=increment)
    send(f"bestmove {move.uci() if move is not None else '0000'}")
    # Le moteur redevient inactif jusqu'au prochain `go` : on reprend la chauffe.
    WARMUP.start()


def main() -> None:
    global board
    WARMUP.start()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        tokens = line.split()
        cmd, args = tokens[0], tokens[1:]

        if cmd == "uci":
            send(f"id name {ENGINE_NAME}")
            send(f"id author {ENGINE_AUTHOR}")
            send("uciok")
        elif cmd == "isready":
            send("readyok")
        elif cmd == "ucinewgame":
            board = chess.Board()
        elif cmd == "position":
            handle_position(args)
        elif cmd == "go":
            handle_go(args)
        elif cmd == "quit":
            break
        # setoption / stop / ponderhit : sans effet, ce moteur n'a pas
        # d'options et une recherche a temps borne ne se laisse pas arreter
        # en cours de route.


if __name__ == "__main__":
    main()
