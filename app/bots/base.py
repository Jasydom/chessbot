"""Interface commune a tous les bots.

Tout bot expose `choose_move(board, ms_left)` et renvoie un `chess.Move` legal
(ou None s'il n'y a aucun coup possible). Le reste de l'application ne connait
rien d'autre : c'est ce qui permet d'ajouter un moteur neuronal plus tard sans
toucher a l'endpoint ni au front.
"""

from typing import Protocol

import chess


class Bot(Protocol):
    #: identifiant stable, utilise dans l'API et dans le <select> du front
    name: str
    #: libelle affiche a l'utilisateur
    label: str

    def choose_move(
        self, board: chess.Board, ms_left: int | None = None
    ) -> chess.Move | None:
        """Choisit un coup pour le camp au trait.

        `ms_left` est le temps restant au bot sur la pendule, en millisecondes.
        Un bot qui reflechit a temps borne s'en sert pour ne pas tomber au drapeau ;
        les autres l'ignorent.
        """
        ...
