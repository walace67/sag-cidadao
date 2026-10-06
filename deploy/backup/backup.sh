#!/usr/bin/env bash
# Backup LÓGICO do banco do SAG-Cidadão com pg_dump.
#
#   deploy/backup/backup.sh
#
# - Formato custom (-Fc): compactado e permite restaurar tabelas avulsas e em paralelo
# - Grava primeiro como ".parcial" e só renomeia no fim: um backup que falhou
#   no meio nunca é confundido com um backup bom
# - Confere o arquivo (pg_restore --list) e grava o checksum SHA-256
# - Criptografia AES-256 opcional (BACKUP_SENHA_ARQUIVO no .env)
# - Rotação GFS (avô-pai-filho): 7 diários, 4 semanais (domingo), 6 mensais (dia 1)
# - Cópia externa opcional (BACKUP_COPIA_EXTERNA): regra 3-2-1 = 3 cópias,
#   2 mídias diferentes, 1 fora do local (HD externo ou outro servidor)
source "$(dirname "$0")/_comum.sh"

inicio=$SECONDS
carimbo="$(date +%Y-%m-%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"/{diario,semanal,mensal}
chmod 700 "$BACKUP_DIR"

nome="${DB_NAME}_${carimbo}.dump"
destino="$BACKUP_DIR/diario/$nome"
parcial="$destino.parcial"
LIMPEZA+=("rm -f '$parcial' '$parcial.gpg'")

log "Iniciando backup do banco $DB_NAME"
# pg_dump lê uma FOTO consistente do banco (snapshot MVCC): o sistema
# continua funcionando durante o backup, sem bloquear os usuários.
pg_dump --format=custom --compress=6 --dbname="$DB_NAME" --file="$parcial"
pg_restore --list "$parcial" > /dev/null || erro "o arquivo gerado não é um dump válido"

if [[ -n "$BACKUP_SENHA_ARQUIVO" ]]; then
    [[ -f "$BACKUP_SENHA_ARQUIVO" ]] || erro "BACKUP_SENHA_ARQUIVO não encontrado: $BACKUP_SENHA_ARQUIVO"
    gpg --batch --quiet --yes --pinentry-mode loopback --passphrase-file "$BACKUP_SENHA_ARQUIVO" \
        --symmetric --cipher-algo AES256 --output "$parcial.gpg" "$parcial"
    rm -f "$parcial"
    parcial="$parcial.gpg"; destino="$destino.gpg"; nome="$nome.gpg"
    log "Criptografado (AES-256)"
fi

mv "$parcial" "$destino"
(cd "$BACKUP_DIR/diario" && sha256sum "$nome" > "$nome.sha256")

# GFS: hard link (ln) não ocupa espaço extra; o arquivo só some do disco
# quando sair de TODAS as pastas.
if [[ "$(date +%u)" == "7" ]]; then ln -f "$destino" "$destino.sha256" "$BACKUP_DIR/semanal/"; fi
if [[ "$(date +%d)" == "01" ]]; then ln -f "$destino" "$destino.sha256" "$BACKUP_DIR/mensal/"; fi

rotacionar() {  # rotacionar PASTA QUANTOS_MANTER
    find "$1" -maxdepth 1 -type f \( -name '*.dump' -o -name '*.dump.gpg' \) -printf '%T@ %p\n' \
        | sort -rn | tail -n +"$(( $2 + 1 ))" | cut -d' ' -f2- \
        | while read -r velho; do rm -f "$velho" "$velho.sha256"; log "Removido pela rotação: $(basename "$velho")"; done
}
rotacionar "$BACKUP_DIR/diario"  "$BACKUP_MANTER_DIARIOS"
rotacionar "$BACKUP_DIR/semanal" "$BACKUP_MANTER_SEMANAIS"
rotacionar "$BACKUP_DIR/mensal"  "$BACKUP_MANTER_MENSAIS"

# Marca para o monitoramento: "o último backup bom foi este, nesta hora"
echo "$destino" > "$BACKUP_DIR/ULTIMO_OK"

# Regra 3-2-1: espelha a pasta de backups num HD externo ou outro servidor.
# Ex.: BACKUP_COPIA_EXTERNA=/media/walace/HD_BACKUP/sag
#      BACKUP_COPIA_EXTERNA=backup@outro-servidor:/srv/backups/sag   (via SSH)
# -H preserva os hard links do GFS; --delete replica também a rotação. Se a cópia falhar, o backup local vale,
# mas o script termina com erro para o agendamento acusar a falha.
if [[ -n "$BACKUP_COPIA_EXTERNA" ]]; then
    if [[ "$BACKUP_COPIA_EXTERNA" != *:* ]]; then mkdir -p "$BACKUP_COPIA_EXTERNA"; fi
    rsync -aH --delete "$BACKUP_DIR/" "$BACKUP_COPIA_EXTERNA/" \
        || erro "backup local OK, mas a cópia externa falhou ($BACKUP_COPIA_EXTERNA)"
    log "Cópia externa atualizada: $BACKUP_COPIA_EXTERNA"
fi


tamanho="$(du -h "$destino" | cut -f1)"
log "Backup concluído: $destino ($tamanho, $(( SECONDS - inicio ))s)"
