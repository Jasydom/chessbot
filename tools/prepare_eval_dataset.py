"""Extrait un sous-echantillon du dataset Lichess evaluations stocke sur Azure Blob.

Le blob source (lichess_db_eval.jsonl.zst, ~22 Go compresse) n'est jamais
telecharge en entier : on le lit en streaming (decompression zstd a la volee)
et on s'arrete des qu'on a assez de positions, pour ne rien stocker de plus
que necessaire en local.

Usage:
    python tools/prepare_eval_dataset.py --count 300000 --out data/eval_sample.jsonl

La cle du compte de stockage est lue dans la variable d'environnement
AZURE_STORAGE_KEY (ne jamais la passer en argument, elle finirait dans
l'historique du shell).
"""

import argparse
import io
import json
import os
import sys

import zstandard as zstd
from azure.storage.blob import BlobClient

ACCOUNT_URL = "https://stchessbotdata.blob.core.windows.net"
CONTAINER = "datasets"
BLOB_NAME = "lichess_db_eval.jsonl.zst"


class _ChunkedReader:
    """Adapte l'iterateur .chunks() d'Azure en objet .read(size), ce que le
    decompresseur zstd attend. Les chunks sont recuperes a la demande (lazy),
    donc on ne telecharge que ce qu'il faut pour atteindre --count lignes.
    """

    def __init__(self, chunks):
        self._chunks = chunks
        self._buf = b""

    def read(self, size=-1):
        if size is None or size < 0:
            parts = [self._buf]
            parts.extend(self._chunks)
            self._buf = b""
            return b"".join(parts)
        while len(self._buf) < size:
            try:
                self._buf += next(self._chunks)
            except StopIteration:
                break
        result, self._buf = self._buf[:size], self._buf[size:]
        return result


def _best_eval(evals: list) -> dict | None:
    """Garde l'analyse la plus profonde parmi les eventuelles reanalyses."""
    if not evals:
        return None
    return max(evals, key=lambda e: e.get("depth", 0))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=300_000)
    parser.add_argument("--out", default="data/eval_sample.jsonl")
    args = parser.parse_args()

    account_key = os.environ.get("AZURE_STORAGE_KEY")
    if not account_key:
        sys.exit("AZURE_STORAGE_KEY n'est pas defini")

    blob = BlobClient(
        account_url=ACCOUNT_URL,
        container_name=CONTAINER,
        blob_name=BLOB_NAME,
        credential=account_key,
    )
    downloader = blob.download_blob(max_concurrency=1)
    reader = _ChunkedReader(downloader.chunks())
    decompressor = zstd.ZstdDecompressor().stream_reader(reader)
    text_stream = io.TextIOWrapper(decompressor, encoding="utf-8")

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)

    kept = 0
    with open(args.out, "w", encoding="utf-8") as out:
        for line in text_stream:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            best = _best_eval(record.get("evals", []))
            if not best or not best.get("pvs"):
                continue
            top_pv = best["pvs"][0]
            out.write(
                json.dumps(
                    {
                        "fen": record["fen"],
                        "cp": top_pv.get("cp"),
                        "mate": top_pv.get("mate"),
                        "depth": best.get("depth"),
                    }
                )
                + "\n"
            )
            kept += 1
            if kept % 20_000 == 0:
                print(f"{kept}/{args.count}", flush=True)
            if kept >= args.count:
                break

    print(f"DONE: {kept} positions -> {args.out}", flush=True)


if __name__ == "__main__":
    main()
