#!/usr/bin/env bash
# Restaura um backup do SAG-Cidadão.
#
#   deploy/backup/restaurar.sh                       # último backup -> banco <DB_NAME>_restaurado
#   deploy/backup/restaurar.sh ARQUIVO               # backup escolhido -> banco <DB_NAME>_restaurado
#   deploy/backup/restaurar.sh --substituir [ARQUIVO]
#
# Sem --substituir, o banco em uso NUNCA é tocado: a cópia vai para um banco
# separado, para você consultar ou recuperar só alguns registros.
#
# Com --substituir (desastre: banco perdido ou corrompido):
#   1. restaura num banco novo e confere
#   2. pede confirmação digitada
#   3. renomeia o banco atual para <DB_NAME>_antes_<data> (NÃO apaga: é o seu "desfazer")
#   4. renomeia o restaurado para <DB_NAME>
# Pare o sistema antes (Ctrl+C no runserver ou: sudo systemctl stop sag-cidadao).
source "$(dirname "$0")/_comum.sh"

substituir=false
if [[ "${1:-}" == "--substituir" ]]; then substituir=true; shift; fi
arquivo="${1:-$(ultimo_backup)}"
[[ -n "$arquivo" ]] || erro "nenhum backup encontrado em $BACKUP_DIR/diario"

restaurado="${DB_NAME}_restaurado"
log "Backup: $arquivo"
if banco_existe "$restaurado"; then
    log "Apagando a restauração anterior ($restaurado)"
    dropdb "$restaurado"
fi

inicio=$SECONDS
restaurar_em "$restaurado" "$arquivo"
tabelas="$(psql -X -t -A -v ON_ERROR_STOP=1 -d "$restaurado" -c "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")" \
    || erro "não consegui ler o banco restaurado"
migracoes="$(psql -X -t -A -v ON_ERROR_STOP=1 -d "$restaurado" -c "SELECT count(*) FROM django_migrations")" \
    || erro "o banco restaurado não tem as tabelas do Django"
log "Restaurado em $restaurado: $tabelas tabelas, $migracoes migrações ($(( SECONDS - inicio ))s)"

if ! $substituir; then
    log "Pronto. O banco em uso ($DB_NAME) não foi alterado."
    log "Consultar: psql -d $restaurado      Apagar quando terminar: dropdb $restaurado"
    exit 0
fi

echo
echo "ATENÇÃO: o banco $DB_NAME será trocado pela cópia do backup."
echo "Tudo o que foi gravado DEPOIS do backup ficará só no banco antigo."
read -r -p "Digite o nome do banco ($DB_NAME) para confirmar: " resposta
[[ "$resposta" == "$DB_NAME" ]] || erro "confirmação não confere; nada foi alterado"

antigo="${DB_NAME}_antes_$(date +%Y%m%d_%H%M%S)"
# Encerra conexões abertas no banco atual (um usuário pode encerrar as próprias)
sql "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$DB_NAME' AND pid <> pg_backend_pid()" > /dev/null
sql "ALTER DATABASE \"$DB_NAME\" RENAME TO \"$antigo\""
sql "ALTER DATABASE \"$restaurado\" RENAME TO \"$DB_NAME\""

log "Troca concluída: $DB_NAME agora contém o backup."
log "Banco anterior guardado como $antigo"
log "Desfazer: dropdb $DB_NAME && psql -d postgres -c 'ALTER DATABASE \"$antigo\" RENAME TO \"$DB_NAME\"'"
log "Quando tiver certeza de que está tudo certo: dropdb $antigo"
