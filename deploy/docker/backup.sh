#!/usr/bin/env bash
# Backup do SAG-Cidadão na versão Docker: banco (pg_dump) + fotos.
#
#   deploy/docker/backup.sh
#
# Mesmas garantias do deploy/backup/backup.sh: arquivo ".parcial" até ser
# conferido, checksum SHA-256, criptografia AES-256 opcional e rotação.
# O pg_dump roda DENTRO do contêiner do banco: a versão do cliente é
# sempre a mesma do servidor (a armadilha da Parte 7 não acontece aqui).
set -euo pipefail
umask 077
cd "$(dirname "$0")/../.."

ENV_FILE="${ENV_FILE:-.env.docker}"
ler() { grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- || true; }
DB_NAME="$(ler DB_NAME)"; DB_NAME="${DB_NAME:-sag_cidadao}"
DB_USER="$(ler DB_USER)"; DB_USER="${DB_USER:-sag}"
DESTINO="${BACKUP_DIR:-$PWD/backups}"
MANTER="${BACKUP_MANTER_DIARIOS:-7}"
SENHA_ARQUIVO="${BACKUP_SENHA_ARQUIVO:-}"
dc() { docker compose --env-file "$ENV_FILE" "$@"; }
log() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }

carimbo="$(date +%Y-%m-%d_%H%M%S)"
mkdir -p "$DESTINO/diario"
# 711: ninguém LISTA a pasta, mas o monitoramento (no contêiner) consegue
# conferir a data do ULTIMO_OK. Os backups em si ficam com permissão 600.
chmod 711 "$DESTINO" "$DESTINO/diario"

banco="$DESTINO/diario/banco_${carimbo}.dump"
fotos="$DESTINO/diario/fotos_${carimbo}.tar.gz"
trap 'rm -f "$banco.parcial" "$fotos.parcial"' EXIT

log "Banco: pg_dump dentro do contêiner"
dc exec -T db pg_dump -U "$DB_USER" -d "$DB_NAME" --format=custom --compress=6 > "$banco.parcial"
dc exec -T db pg_restore --list < "$banco.parcial" > /dev/null   # o arquivo é um dump válido?

log "Fotos: cópia do volume"
dc exec -T web tar czf - -C /app media > "$fotos.parcial"

for arq in "$banco" "$fotos"; do
    if [[ -n "$SENHA_ARQUIVO" ]]; then
        gpg --batch --quiet --yes --pinentry-mode loopback --passphrase-file "$SENHA_ARQUIVO" \
            --symmetric --cipher-algo AES256 --output "$arq.gpg" "$arq.parcial"
        rm -f "$arq.parcial"; final="$arq.gpg"
    else
        mv "$arq.parcial" "$arq"; final="$arq"
    fi
    (cd "$(dirname "$final")" && sha256sum "$(basename "$final")" > "$(basename "$final").sha256")
done

# Rotação: mantém os N mais novos de cada tipo
for prefixo in banco fotos; do
    find "$DESTINO/diario" -maxdepth 1 -type f -name "${prefixo}_*" ! -name '*.sha256' -printf '%T@ %p\n' \
        | sort -rn | tail -n +"$(( MANTER + 1 ))" | cut -d' ' -f2- \
        | while read -r velho; do rm -f "$velho" "$velho.sha256"; log "Removido pela rotação: $(basename "$velho")"; done
done

echo "$carimbo" > "$DESTINO/ULTIMO_OK"
chmod 644 "$DESTINO/ULTIMO_OK"
log "Backup concluído em $DESTINO/diario ($(du -sh "$DESTINO/diario" | cut -f1) no total)"
