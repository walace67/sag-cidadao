#!/bin/sh
# Roda antes do comando do contêiner. Só o contêiner "web" (gunicorn)
# prepara o banco; o worker apenas espera e executa tarefas.
set -e

if [ "$1" = "gunicorn" ]; then
    echo "==> Migrações do banco"
    python manage.py migrate --noinput
    python manage.py createcachetable
    echo "==> Arquivos estáticos para o Nginx"
    python manage.py collectstatic --noinput --verbosity 0
fi

# exec: o processo final vira o PID 1 do contêiner e recebe os sinais
# de parada (docker stop) diretamente, encerrando de forma limpa.
exec "$@"
