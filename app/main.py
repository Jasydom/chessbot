import random
import chess
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

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

def get_random_bot_move(board: chess.Board) -> str | None:
    legal_moves = list(board.legal_moves)
    if not legal_moves:
        return None
    return random.choice(legal_moves).uci()

@app.post("/api/move")
def play_move(req: MoveRequest):
    board = chess.Board(req.fen)
    
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
    bot_move_uci = get_random_bot_move(board)
    if bot_move_uci:
        board.push(chess.Move.from_uci(bot_move_uci))

    return {
        "fen": board.fen(),
        "bot_move": bot_move_uci,
        "game_over": board.is_game_over(),
        "status": "À votre tour !" if not board.is_game_over() else "Partie terminée !"
    }

app.mount("/", StaticFiles(directory="app/static", html=True), name="static")