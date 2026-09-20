"""Interface commune a tous les bots.

Tout bot expose `choose_move(board, ms_left)` et renvoie un `chess.Move` legal
(ou None s'il n'y a aucun coup possible). Le reste du projet (pont UCI, arene)
ne connait rien d'autre : c'est ce qui permet d'ajouter un moteur neuronal plus
tard sans toucher a ces appelants.
"""

from typing import Protocol

import chess


class Bot(Protocol):
    #: identifiant stable, utilise pour designer le bot dans l'arene
    name: str
    #: libelle lisible du bot
    label: str

    def choose_move(
        self,
        board: chess.Board,
        ms_left: int | None = None,
        increment_ms: int = 0,
    ) -> chess.Move | None:
        """Choisit un coup pour le camp au trait.

        `ms_left` est le temps restant au bot sur la pendule, en millisecondes,
        et `increment_ms` l'increment par coup. Un bot qui reflechit a temps
        borne s'en sert pour ne pas tomber au drapeau ; les autres les ignorent.
        """
        ...
