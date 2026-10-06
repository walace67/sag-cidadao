# shellcheck shell=bash
# Funções e configuração compartilhadas pelos scripts de backup.
# Não é executado sozinho: os outros scripts fazem "source" deste arquivo.

set -euo pipefail
umask 077   # backups têm DADOS PESSOAIS (LGPD): só o dono lê (permissão 600)

PROJETO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="$PROJETO/.venv/bin/python"
[[ -x "$PY" ]] || PY="python3"

# Lê as variáveis do MESMO .env que o Django usa (fonte única da verdade).
# shlex.quote protege contra senhas com espaços, aspas ou $.
eval "$("$PY" - "$PROJETO" <<'PYEOF'
import shlex, sys
from decouple import AutoConfig
config = AutoConfig(search_path=sys.argv[1])
padroes = {
    "DB_NAME": "sag_cidadao", "DB_USER": "sag", "DB_PASSWORD": "",
    "DB_HOST": "localhost", "DB_PORT": "5432",
    "BACKUP_DIR": "~/backups_sag/postgres",
    "BACKUP_SENHA_ARQUIVO": "",          # vazio = sem criptografia
    "BACKUP_MANTER_DIARIOS": "7",
    "BACKUP_MANTER_SEMANAIS": "4",
    "BACKUP_MANTER_MENSAIS": "6",
    "BACKUP_COPIA_EXTERNA": "",          # vazio = sem cópia fora da máquina
}
for chave, padrao in padroes.items():
    print(f"{chave}={shlex.quote(str(config(chave, default=padrao)))}")
PYEOF
)"
BACKUP_DIR="${BACKUP_DIR/#\~/$HOME}"
BACKUP_SENHA_ARQUIVO="${BACKUP_SENHA_ARQUIVO/#\~/$HOME}"
BACKUP_COPIA_EXTERNA="${BACKUP_COPIA_EXTERNA/#\~/$HOME}"

# Variáveis que pg_dump, pg_restore, psql, createdb e dropdb entendem.
export PGHOST="$DB_HOST" PGPORT="$DB_PORT" PGUSER="$DB_USER" PGPASSWORD="$DB_PASSWORD"

# Limpeza ao sair (sucesso OU erro): cada script registra o que apagar.
# Garante que nenhum dump descriptografado (dado pessoal) fique esquecido.
LIMPEZA=()
limpar() { local cmd; for cmd in "${LIMPEZA[@]}"; do eval "$cmd" || true; done; }
trap limpar EXIT

# Ferramentas da MESMA versão do servidor. Com mais de uma versão instalada,
# o comando "pg_dump" padrão pode ser mais novo que o servidor e gerar um
# backup que o servidor antigo não consegue restaurar (ex.: o pg_dump 17
# grava "SET transaction_timeout", parâmetro que o PostgreSQL 16 não tem).
usar_ferramentas_do_servidor() {
    local num maior
    num="$(psql -X -t -A -d postgres -c 'SHOW server_version_num')" \
        || { echo "ERRO: não consegui conectar ao PostgreSQL em $PGHOST:$PGPORT como $PGUSER" >&2; exit 1; }
    maior=$(( num / 10000 ))
    if [[ -x "/usr/lib/postgresql/$maior/bin/pg_dump" ]]; then
        PATH="/usr/lib/postgresql/$maior/bin:$PATH"
    fi
    local cliente
    cliente="$(pg_dump --version | grep -oE '[0-9]+' | head -1)"
    if (( cliente != maior )); then
        echo "AVISO: servidor PostgreSQL $maior, mas pg_dump $cliente." \
             "Instale o cliente da mesma versão: sudo apt install postgresql-client-$maior" >&2
    fi
}

log()  { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
erro() { log "ERRO: $*" >&2; exit 1; }

usar_ferramentas_do_servidor

# Executa SQL conectado ao banco de manutenção "postgres" (não ao do sistema)
sql() { psql -X -q -t -A -v ON_ERROR_STOP=1 -d postgres -c "$1"; }

banco_existe() { [[ "$(sql "SELECT 1 FROM pg_database WHERE datname = '$1'")" == "1" ]]; }

ultimo_backup() {
    find "$BACKUP_DIR/diario" -maxdepth 1 -type f \( -name '*.dump' -o -name '*.dump.gpg' \) -printf '%T@ %p\n' 2>/dev/null \
        | sort -rn | head -1 | cut -d' ' -f2-
}

# restaurar_em BANCO ARQUIVO -> cria BANCO (vazio) e restaura o ARQUIVO nele
restaurar_em() {
    local destino="$1" arquivo="$2" dump="$2" tmp=""
    [[ -f "$arquivo" ]] || erro "arquivo não encontrado: $arquivo"

    # 1. Integridade: o arquivo é exatamente o que foi gravado?
    if [[ -f "$arquivo.sha256" ]]; then
        (cd "$(dirname "$arquivo")" && sha256sum --quiet -c "$(basename "$arquivo").sha256") \
            || erro "checksum NÃO confere: arquivo corrompido ou alterado"
        log "Checksum SHA-256 confere"
    else
        log "AVISO: sem arquivo .sha256; integridade não verificada"
    fi

    # 2. Descriptografa num diretório temporário privado
    if [[ "$arquivo" == *.gpg ]]; then
        [[ -f "$BACKUP_SENHA_ARQUIVO" ]] || erro "backup criptografado: defina BACKUP_SENHA_ARQUIVO no .env"
        tmp="$(mktemp -d)"
        LIMPEZA+=("rm -rf '$tmp'")
        dump="$tmp/backup.dump"
        gpg --batch --quiet --pinentry-mode loopback --passphrase-file "$BACKUP_SENHA_ARQUIVO" \
            --output "$dump" --decrypt "$arquivo" || erro "não foi possível descriptografar"
        log "Backup descriptografado"
    fi

    # 3. Banco novo e restauração
    banco_existe "$destino" && erro "o banco $destino já existe (apague-o antes: dropdb $destino)"
    createdb --owner="$DB_USER" "$destino"
    # --no-owner/--no-privileges: os objetos ficam com o usuário que restaura
    # --exit-on-error: qualquer erro aborta (restauração pela metade é pior que nenhuma)
    # --jobs: restaura tabelas e índices em paralelo
    if ! pg_restore --no-owner --no-privileges --exit-on-error --jobs=2 --dbname="$destino" "$dump"; then
        dropdb --if-exists "$destino"
        erro "falha no pg_restore; banco $destino descartado"
    fi
}
