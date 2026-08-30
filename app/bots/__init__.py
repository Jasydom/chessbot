"""Registre des adversaires disponibles.

Ajouter un bot = l'instancier ici. L'endpoint et le <select> du front se
mettent a jour tout seuls a partir de cette liste.
"""

from app.bots.base import Bot
from app.bots.minimax import MinimaxBot
from app.bots.random_bot import RandomBot

_REGISTRY: dict[str, Bot] = {
    bot.name: bot
    for bot in (
        RandomBot(),
        MinimaxBot(
            name="easy",
            label="Minimax - Facile",
            max_depth=2,
            time_budget=0.20,
            # Sans quiescence il ne voit pas le bout des echanges : il gaffe
            # comme un debutant au lieu de jouer juste mais court.
            use_quiescence=False,
        ),
        MinimaxBot(name="normal", label="Minimax - Normal", time_budget=0.60),
        MinimaxBot(name="hard", label="Minimax - Difficile", time_budget=1.50),
    )
}

DEFAULT_BOT = "normal"


def get_bot(name: str | None) -> Bot | None:
    """Renvoie le bot demande, ou None si le nom est inconnu."""
    return _REGISTRY.get(name or DEFAULT_BOT)


def list_bots() -> list[dict[str, str]]:
    return [{"name": bot.name, "label": bot.label} for bot in _REGISTRY.values()]


__all__ = ["Bot", "DEFAULT_BOT", "get_bot", "list_bots"]
