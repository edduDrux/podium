#!/usr/bin/env sh
# Instala ou atualiza a API na VM: código novo, imagem nova, migrations, containers.
# Uso, na pasta do projeto: sh deploy/update.sh
# Usa os dois arquivos do Compose por causa do COMPOSE_FILE do .env.
set -eu
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
    echo "Falta o .env: cp deploy/production.env.example .env e preencha." >&2
    exit 1
fi

git pull --ff-only
docker compose build api

# As migrations rodam num container avulso ANTES de a API nova subir: a API nunca roda
# contra um banco no esquema anterior. O `run` sobe o banco antes, se precisar.
docker compose run --rm api alembic upgrade head

docker compose up -d
docker compose ps
