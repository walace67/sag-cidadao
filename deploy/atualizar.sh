#!/usr/bin/env bash
# Atualiza o SAG-Cidadão no servidor com a versão mais recente do Git.
#   cd /srv/sag_cidadao && sudo -u sag deploy/atualizar.sh
# Para no primeiro erro (set -e): nunca reinicia com migração pela metade.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Baixando a versão nova"
git pull --ff-only

echo "==> Dependências"
.venv/bin/pip install -q -r requirements.txt

echo "==> Verificações de produção"
.venv/bin/python manage.py check --deploy --fail-level WARNING

echo "==> Banco (migrações) e arquivos estáticos"
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py createcachetable
.venv/bin/python manage.py collectstatic --noinput

echo "==> Reiniciando sem derrubar conexões (HUP = reload gracioso)"
sudo systemctl reload sag-cidadao
sleep 3

echo "==> Verificação de saúde"
curl -fsS --unix-socket /run/sag-cidadao/gunicorn.sock -H "Host: $(.venv/bin/python -c 'from decouple import config, Csv; print(config("ALLOWED_HOSTS", cast=Csv())[0])')" \
     -H "X-Forwarded-Proto: https" http://localhost/saude/ && echo && echo "OK: nova versão no ar"
