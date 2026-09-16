"""Suivi de version via l'API Lichess : mesure les performances reelles du
bot sur lichess.org en repartissant ses parties par version du moteur.

Lichess n'a aucune notion de "version" cote partie : ce script maintient son
propre repere temporel (tools/lichess_versions.json) qui associe chaque
version a la date depuis laquelle elle tourne sur le compte bot, puis decoupe
l'historique recupere via l'API en fonction de ces bornes.

Usage (depuis la racine du projet) :
    # A chaque deploiement d'une nouvelle version sur le compte bot :
    python -m tools.lichess_stats tag v2-king-safety

    # Score par version pour le compte bot `chessbotmontaigne` :
    python -m tools.lichess_stats stats chessbotmontaigne

Un jeton API (--token ou variable LICHESS_TOKEN) n'est pas requis pour lire
l'historique public d'un compte, mais releve la limite de requetes.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

VERSIONS_FILE = Path(__file__).resolve().parent / "lichess_versions.json"
API_BASE = "https://lichess.org/api/games/user"
UNVERSIONED_LABEL = "non versionne"


def _load_versions() -> list[dict]:
    if not VERSIONS_FILE.exists():
        return []
    return json.loads(VERSIONS_FILE.read_text(encoding="utf-8"))


def _save_versions(versions: list[dict]) -> None:
    VERSIONS_FILE.write_text(json.dumps(versions, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def cmd_tag(version: str) -> None:
    versions = _load_versions()
    if any(v["version"] == version for v in versions):
        raise SystemExit(f"Version deja enregistree : {version}")
    since = datetime.now(timezone.utc).isoformat()
    versions.append({"version": version, "since": since})
    _save_versions(versions)
    print(f"Version '{version}' enregistree depuis {since}")


@dataclass
class _Score:
    wins: int = 0
    losses: int = 0
    draws: int = 0

    @property
    def games(self) -> int:
        return self.wins + self.losses + self.draws

    @property
    def score_pct(self) -> float:
        if self.games == 0:
            return 0.0
        return 100 * (self.wins + 0.5 * self.draws) / self.games


def _version_for(created_at_ms: int, versions: list[dict]) -> str:
    """Renvoie la version en vigueur au moment de la partie.

    `versions` est trie par date croissante : on prend la derniere version
    dont le `since` precede la partie, et on peut s'arreter des qu'on en
    depasse une (le reste est forcement plus tard).
    """
    label = UNVERSIONED_LABEL
    for entry in versions:
        since_ms = int(datetime.fromisoformat(entry["since"]).timestamp() * 1000)
        if since_ms > created_at_ms:
            break
        label = entry["version"]
    return label


def _fetch_games(username: str, since_ms: int | None, token: str | None, max_games: int | None):
    params = {"pgnInBase64": "false", "opening": "false", "moves": "false"}
    if since_ms is not None:
        params["since"] = str(since_ms)
    if max_games is not None:
        params["max"] = str(max_games)
    url = f"{API_BASE}/{urllib.parse.quote(username)}?{urllib.parse.urlencode(params)}"

    headers = {"Accept": "application/x-ndjson"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request) as response:
            for raw_line in response:
                line = raw_line.strip()
                if line:
                    yield json.loads(line)
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"Erreur API Lichess ({exc.code}) : {exc.reason}") from exc


def cmd_stats(username: str, token: str | None, max_games: int | None) -> None:
    versions = sorted(_load_versions(), key=lambda v: v["since"])
    since_ms = None
    if versions:
        since_ms = int(datetime.fromisoformat(versions[0]["since"]).timestamp() * 1000)

    scores: dict[str, _Score] = {}
    total = 0
    for game in _fetch_games(username, since_ms, token, max_games):
        total += 1
        players = game.get("players", {})
        white = players.get("white", {}).get("user", {}).get("name", "")
        black = players.get("black", {}).get("user", {}).get("name", "")
        if white.lower() == username.lower():
            bot_color = "white"
        elif black.lower() == username.lower():
            bot_color = "black"
        else:
            continue  # partie sans le compte cible (ne devrait pas arriver)

        winner = game.get("winner")
        score = scores.setdefault(_version_for(game["createdAt"], versions), _Score())
        if winner is None:
            score.draws += 1
        elif winner == bot_color:
            score.wins += 1
        else:
            score.losses += 1

    if total == 0:
        print(f"Aucune partie trouvee pour {username}.")
        return

    print(f"{total} partie(s) recuperee(s) pour {username}\n")
    order = [v["version"] for v in versions] + [UNVERSIONED_LABEL]
    for label in order:
        if label not in scores:
            continue
        s = scores[label]
        print(f"{label:20s} {s.games:4d} parties  V:{s.wins} N:{s.draws} P:{s.losses}  score {s.score_pct:.1f}%")


def main() -> None:
    parser = argparse.ArgumentParser(description="Suivi de version du bot via l'historique de parties Lichess.")
    sub = parser.add_subparsers(dest="command", required=True)

    tag_parser = sub.add_parser("tag", help="Enregistre une nouvelle version a partir de maintenant.")
    tag_parser.add_argument("version", help="Nom/etiquette de la version (ex: v2-king-safety)")

    stats_parser = sub.add_parser("stats", help="Affiche le score par version pour un compte bot.")
    stats_parser.add_argument("username", help="Nom d'utilisateur du compte bot sur lichess.org")
    stats_parser.add_argument(
        "--token", default=os.environ.get("LICHESS_TOKEN"), help="Jeton API (ou variable LICHESS_TOKEN) pour un quota plus eleve"
    )
    stats_parser.add_argument("--max", type=int, default=None, help="Nombre maximum de parties a recuperer")

    args = parser.parse_args()

    if args.command == "tag":
        cmd_tag(args.version)
    elif args.command == "stats":
        cmd_stats(args.username, args.token, args.max)


if __name__ == "__main__":
    main()
