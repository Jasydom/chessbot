import time
import random
import chess
import streamlit as st
from streamlit_chessboard import chessboard
from streamlit_autorun import autorun

st.set_page_config(page_title="ChessBot", layout="centered")
st.title("ChessBot — V0 (Bot Aléatoire)")

# --- 1. INITIALISATION DU SESSION STATE ---
if "board" not in st.session_state:
    st.session_state.board = chess.Board()

if "white_time" not in st.session_state:
    st.session_state.white_time = 180.0  # 3 minutes en secondes
    st.session_state.black_time = 180.0
    st.session_state.last_time = time.time()
    st.session_state.game_over = False
    st.session_state.winner = None

b = st.session_state.board

# --- 2. GESTION DE LA PENDULE ---
def update_timers():
    """Met à jour le temps restant du joueur dont c'est le tour."""
    if st.session_state.game_over or b.is_game_over():
        return

    now = time.time()
    elapsed = now - st.session_state.last_time
    st.session_state.last_time = now

    if b.turn == chess.WHITE:
        st.session_state.white_time -= elapsed
        if st.session_state.white_time <= 0:
            st.session_state.white_time = 0
            st.session_state.game_over = True
            st.session_state.winner = "Noirs (Temps écoulé)"
    else:
        st.session_state.black_time -= elapsed
        if st.session_state.black_time <= 0:
            st.session_state.black_time = 0
            st.session_state.game_over = True
            st.session_state.winner = "Blancs (Temps écoulé)"

update_timers()

# Rafraîchit l'application toutes les 1000ms (1 seconde) pour la pendule
if not st.session_state.game_over and not b.is_game_over():
    autorun(interval=1000, key="clock_tick")

# Formater le temps en MM:SS
def format_time(seconds):
    mins = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{mins:02d}:{secs:02d}"

# --- 3. AFFICHAGE DE LA PENDULE ---
col1, col2 = st.columns(2)
with col1:
    st.metric("⏳ Blancs (Vous)", format_time(st.session_state.white_time))
with col2:
    st.metric("⏳ Noirs (Bot)", format_time(st.session_state.black_time))

# --- 4. LOGIQUE DU BOT ---
def make_bot_move():
    if b.is_game_over() or st.session_state.game_over:
        return
    
    legal_moves = list(b.legal_moves)
    if legal_moves:
        b.push(random.choice(legal_moves))
        # Ajout de l'incrément de 2 secondes pour les Noirs
        st.session_state.black_time += 2.0
        st.session_state.last_time = time.time()

# --- 5. ÉCHIQUIER INTERACTIF (SOURIS) ---
fen = b.fen()
move_result = chessboard(raw_fen=fen, key="board_widget")

# Vérifier si l'utilisateur a déplacé une pièce à la souris
if move_result and "fen" in move_result:
    new_fen = move_result["fen"]
    if new_fen != fen:
        # Trouver le coup correspondant à la nouvelle FEN
        for move in b.legal_moves:
            b_copy = b.copy()
            b_copy.push(move)
            if b_copy.fen().split()[0] == new_fen.split()[0]:
                b.push(move)
                # Ajout de l'incrément de 2 secondes pour les Blancs
                st.session_state.white_time += 2.0
                st.session_state.last_time = time.time()

                # Tour du Bot
                if not b.is_game_over():
                    make_bot_move()
                st.rerun()

# --- 6. FIN DE PARTIE & REINITIALISATION ---
if st.session_state.game_over:
    st.error(f"Fin du temps ! Victoire : {st.session_state.winner}")
elif b.is_checkmate():
    st.error("Échec et mat !")
elif b.is_stalemate():
    st.warning("Pat !")
elif b.is_game_over():
    st.info("Fin de partie.")

if st.button("Nouvelle partie"):
    st.session_state.board = chess.Board()
    st.session_state.white_time = 180.0
    st.session_state.black_time = 180.0
    st.session_state.last_time = time.time()
    st.session_state.game_over = False
    st.session_state.winner = None
    st.rerun()