# Le moteur est du Python pur et limite par le temps reel : sous PyPy il fait
# environ deux fois plus de noeuds/s qu'avec CPython une fois le JIT chaud
# (mesure : tools/bench_nps.py, cf. la chauffe dans app/uci.py). lichess-bot
# lui-meme reste sous CPython ; on ne prend de PyPy que l'interpreteur et
# python-chess. Image epinglee par digest pour un build reproductible.
FROM pypy:3.11-slim@sha256:277df42aeda3071e6d92d976e0976afeb5092c2030cf461545d8fccf9c66a6ba AS pypy
RUN pypy3 -m pip install --no-cache-dir python-chess

FROM python:3.11-slim

COPY --from=pypy /opt/pypy /opt/pypy
RUN ln -s /opt/pypy/bin/pypy3 /usr/local/bin/pypy3

# lichess-bot n'est pas un paquet pip : on clone le repo officiel a un
# commit fixe pour que le build reste reproductible. Les tags type "1.1.3"
# sont un ancien schema de versions (deps python-chess/PyYAML obsoletes) ;
# le projet est desormais versionne en CalVer via des commits automatiques
# sur master, d'ou l'epingle sur un SHA plutot qu'un tag.
ARG LICHESS_BOT_REF=df7e730de58cc3ef2f1415a0dc2eeda842d39167

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /lichess-bot
RUN git init -q . \
    && git fetch -q --depth 1 https://github.com/lichess-bot-devs/lichess-bot.git ${LICHESS_BOT_REF} \
    && git checkout -q FETCH_HEAD \
    && rm -rf .git
RUN pip install --no-cache-dir -r requirements.txt

# Notre moteur : app/uci.py, qui importe MinimaxBot directement (voir
# app/uci.py pour le detail du protocole).
COPY app/ /app/app/

# lichess-bot attend un executable dans engine.dir ; on l'enveloppe dans un
# petit wrapper shell puisque notre moteur est un script Python, lance sous PyPy.
RUN mkdir -p /lichess-bot/engines \
    && printf '#!/bin/sh\nexec pypy3 /app/app/uci.py\n' > /lichess-bot/engines/chessbot-uci \
    && chmod +x /lichess-bot/engines/chessbot-uci

COPY lichess-bot-service/config.yml /lichess-bot/config.yml

CMD ["python3", "lichess-bot.py"]
