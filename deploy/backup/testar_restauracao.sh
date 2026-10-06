#!/usr/bin/env bash
# "Backup que nunca foi restaurado não é backup, é esperança."
#
#   deploy/backup/testar_restauracao.sh
#
# Restaura o ÚLTIMO backup num banco temporário, confere as tabelas e as
# migrações do Django, compara com o banco em uso, mede o tempo (base do RTO)
# e apaga o banco temporário. Código de saída 0 = backup restaurável.
source "$(dirname "$0")/_comum.sh"

arquivo="$(ultimo_backup)"
[[ -n "$arquivo" ]] || erro "nenhum backup encontrado em $BACKUP_DIR/diario"
teste="${DB_NAME}_teste_restauracao"
banco_existe "$teste" && dropdb "$teste"
LIMPEZA+=("dropdb --if-exists '$teste' 2>/dev/null")

idade_h=$(( ( $(date +%s) - $(stat -c %Y "$arquivo") ) / 3600 ))
log "Testando: $(basename "$arquivo") (gerado há ${idade_h}h)"

inicio=$SECONDS
restaurar_em "$teste" "$arquivo"
tempo=$(( SECONDS - inicio ))

# Falha de verdade se a consulta falhar: "$(...)" sozinho engoliria o erro
# e o teste passaria mesmo com o backup quebrado (falso positivo).
contar() { psql -X -q -t -A -v ON_ERROR_STOP=1 -d "$1" -c "SELECT count(*) FROM \"$2\"" || erro "não consegui ler $2 em $1"; }
tabelas() { psql -X -t -A -v ON_ERROR_STOP=1 -d "$1" -c \
    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY 1"; }

lista_backup="$(tabelas "$teste")"
lista_uso="$(tabelas "$DB_NAME")"
[[ "$(wc -l <<< "$lista_backup")" -gt 5 ]] || erro "o backup restaurado quase não tem tabelas"
grep -qx django_migrations <<< "$lista_backup" || erro "backup sem as tabelas do Django"

printf '\n%-32s %10s %10s\n' "Tabela" "Backup" "Em uso"
while read -r tabela; do
    no_backup="$(contar "$teste" "$tabela")" || exit 1
    if grep -qx "$tabela" <<< "$lista_uso"; then em_uso="$(contar "$DB_NAME" "$tabela")" || exit 1; else em_uso="(não existe)"; fi
    printf '%-32s %10s %10s\n' "$tabela" "$no_backup" "$em_uso"
done <<< "$lista_backup"
echo

faltando="$(comm -13 <(echo "$lista_backup") <(echo "$lista_uso"))"
[[ -z "$faltando" ]] || log "AVISO: tabelas que existem hoje mas não no backup: $(echo "$faltando" | tr '\n' ' ')"
if (( idade_h > 26 )); then
    log "AVISO: o último backup tem mais de 1 dia; o agendamento está rodando?"
fi

log "OK: backup restaurável em ${tempo}s (tempo mínimo de recuperação, RTO)."
log "Dados que se perderiam se o desastre fosse agora: as últimas ${idade_h}h (RPO)."
