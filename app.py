import time
import random
import chess
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="ChessBot", layout="centered")
st.title("ChessBot — V0")

# --- 1. SESSION STATE ---
if "board" not in st.session_state:
    st.session_state.board = chess.Board()
if "white_time" not in st.session_state:
    st.session_state.white_time = 180.0  # 3 minutes
    st.session_state.black_time = 180.0
    st.session_state.last_time = time.time()
    st.session_state.game_over = False
    st.session_state.winner = None

b = st.session_state.board

# --- 2. PENDULE (3 min + 2s) ---
def update_timers():
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
            st.session_state.winner = "Noirs (Temps)"
    else:
        st.session_state.black_time -= elapsed
        if st.session_state.black_time <= 0:
            st.session_state.black_time = 0
            st.session_state.game_over = True
            st.session_state.winner = "Blancs (Temps)"

update_timers()

def format_time(seconds):
    mins = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{mins:02d}:{secs:02d}"

col1, col2 = st.columns(2)
with col1:
    st.metric("⏳ Blancs (Vous)", format_time(st.session_state.white_time))
with col2:
    st.metric("⏳ Noirs (Bot)", format_time(st.session_state.black_time))

# --- 3. BOT ALÉATOIRE ---
def make_bot_move():
    if b.is_game_over() or st.session_state.game_over:
        return
    legal_moves = list(b.legal_moves)
    if legal_moves:
        b.push(random.choice(legal_moves))
        st.session_state.black_time += 2.0
        st.session_state.last_time = time.time()

# --- 4. ÉCHIQUIER INTERACTIF JS (DRAG & DROP) ---
chessboard_html = f"""
<!DOCTYPE html>
<html>
<head>
    <link rel="stylesheet" href="https://unpkg.com/@chrisoakman/chessboardjs@1.0.0/dist/chessboard-1.0.0.min.css">
    <script src="https://code.jquery.com/jquery-3.5.1.min.js"></script>
    <script src="https://unpkg.com/@chrisoakman/chessboardjs@1.0.0/dist/chessboard-1.0.0.min.js"></script>
</head>
<body>
    <div id="myBoard" style="width: 400px; margin: 0 auto;"></div>
    <script>
        var board = Chessboard('myBoard', {{
            draggable: true,
            position: '{b.fen()}',
            onDrop: function(source, target) {{
                const move = source + target;
                window.parent.postMessage({{type: 'streamlit:setComponentValue', value: move}}, '*');
            }}
        }});
    </script>
</body>
</html>
"""

components.html(chessboard_html, height=430)

# Saisie manuelle de secours / Confirmation du coup
user_move = st.text_input("Validation du coup à la souris (ou tape le coup ex: e2e4) :", key="move_input")

if st.button("Jouer le coup"):
    try:
        move = chess.Move.from_uci(user_move.strip())
        if move in b.legal_moves:
            b.push(move)
            st.session_state.white_time += 2.0
            st.session_state.last_time = time.time()

            if not b.is_game_over():
                make_bot_move()
            st.rerun()
        else:
            st.warning("Coup illégal !")
    except ValueError:
        st.error("Format invalide.")

# --- 5. FIN DE PARTIE & REBOOT ---
if st.session_state.game_over:
    st.error(f"Fin du temps ! Victoire : {st.session_state.winner}")
elif b.is_checkmate():
    st.error("Échec et mat !")
elif b.is_stalemate():
    st.warning("Pat !")

if st.button("Nouvelle partie"):
    st.session_state.board = chess.Board()
    st.session_state.white_time = 180.0
    st.session_state.black_time = 180.0
    st.session_state.last_time = time.time()
    st.session_state.game_over = False
    st.rerun()