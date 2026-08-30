import time

import chess
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.bots import DEFAULT_BOT, get_bot, list_bots

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class MoveRequest(BaseModel):
    fen: str
    move: str
    #: Adversaire choisi dans le menu du front.
    bot: str = DEFAULT_BOT
    #: Temps restant au bot sur la pendule, en millisecondes. Laisse les
    #: moteurs a temps borne adapter leur reflexion a la cadence.
    ms_left: int | None = None


@app.get("/api/bots")
def get_bots():
    return {"bots": list_bots(), "default": DEFAULT_BOT}


@app.post("/api/move")
def play_move(req: MoveRequest):
    bot = get_bot(req.bot)
    if bot is None:
        return {"error": f"Bot inconnu : {req.bot}"}

    try:
        board = chess.Board(req.fen)
    except ValueError:
        return {"error": "Position invalide"}

    try:
        user_move = chess.Move.from_uci(req.move)
    except ValueError:
        return {"error": "Format de coup invalide"}

    if user_move not in board.legal_moves:
        return {"error": "Coup illégal"}

    # 1. Jouer le coup de l'utilisateur (Blancs)
    board.push(user_move)

    if board.is_game_over():
        return {
            "fen": board.fen(),
            "bot_move": None,
            "game_over": True,
            "status": "Partie terminée !"
        }

    # 2. Jouer le coup du Bot (Noirs)
    started = time.monotonic()
    bot_move = bot.choose_move(board, ms_left=req.ms_left)
    elapsed_ms = int((time.monotonic() - started) * 1000)

    bot_move_uci = None
    if bot_move is not None:
        bot_move_uci = bot_move.uci()
        board.push(bot_move)

    return {
        "fen": board.fen(),
        "bot_move": bot_move_uci,
        "bot": bot.name,
        "thinking_ms": elapsed_ms,
        "game_over": board.is_game_over(),
        "status": "À votre tour !" if not board.is_game_over() else "Partie terminée !"
    }


class NoCacheStaticFiles(StaticFiles):
    """Force le navigateur a revalider a chaque visite.

    StaticFiles envoie un ETag mais aucun Cache-Control. Sans cette directive,
    le navigateur applique un cache heuristique et peut resservir une version
    obsolete apres un deploiement, sans meme interroger le serveur.
    "no-cache" n'empeche pas la mise en cache : il impose la revalidation, qui
    renvoie un 304 vide tant que le fichier n'a pas change.
    """

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/", NoCacheStaticFiles(directory="app/static", html=True), name="static")
