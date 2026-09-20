"""Moteur UCI : pont entre lichess-bot (ou toute interface UCI) et MinimaxBot.

`lichess-bot` lance cet executable et lui parle en UCI sur stdin/stdout. Ce
script importe directement `MinimaxBot` et traduit les commandes UCI
(`position`, `go`, ...) en appels a `choose_move(board, ms_left)`, sans
dependance reseau.

Lancement : `python app/uci.py` depuis la racine du projet (ou en donnant ce
chemin comme `EngineDir`/executable a lichess-bot).
"""

from __future__ import annotations

import sys
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
    else:
        is_white = board.turn == chess.WHITE
        ms_left = params.get("wtime" if is_white else "btime")
        increment = params.get("winc" if is_white else "binc", 0)
        if ms_left is not None:
            # Approximation simple : le bonus d'increment s'ajoute au temps
            # restant plutot que d'etre gere coup par coup.
            ms_left += increment

    move = ENGINE.choose_move(board, ms_left=ms_left)
    send(f"bestmove {move.uci() if move is not None else '0000'}")


def main() -> None:
    global board
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
