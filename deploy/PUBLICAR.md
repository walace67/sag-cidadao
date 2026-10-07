# Publicar o SAG-Cidadão num servidor real

Roteiro para colocar o sistema na internet com HTTPS, usando Docker. Tempo estimado: 30 a 60 minutos.

```
Internet ──HTTPS──▶ Caddy (certificado automático) ──▶ Nginx :8088 ──▶ Gunicorn/Django ──▶ PostgreSQL
                    no servidor                         contêineres Docker
```

## 1. O que você precisa

| Item | Recomendação |
|---|---|
| Servidor (VPS) | Ubuntu 24.04 LTS, 2 vCPU e 4 GB de RAM para piloto; 4 vCPU para a cidade toda (repita o teste de carga) |
| Domínio | Um nome como `sag.seudominio.com.br`, com acesso ao painel de DNS |
| E-mail | Uma conta SMTP para os avisos (provedor de e-mail transacional ou o servidor de e-mail da instituição) |

## 2. DNS

No painel do seu domínio, crie um registro **A** apontando `sag.seudominio.com.br` para o **IP do servidor**. A propagação pode levar de minutos a algumas horas: confira com `ping sag.seudominio.com.br`.

## 3. Primeiro acesso e segurança do servidor

```bash
ssh root@IP_DO_SERVIDOR

# Usuário próprio (não trabalhar como root) com acesso por chave SSH
adduser deploy && usermod -aG sudo deploy
rsync --archive --chown=deploy:deploy ~/.ssh /home/deploy

# Firewall: só SSH, HTTP e HTTPS. O PostgreSQL NÃO fica exposto.
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw enable

# Atualizações de segurança automáticas
apt update && apt -y upgrade && apt -y install unattended-upgrades
dpkg-reconfigure -plow unattended-upgrades
```

Depois, entre como `deploy` (`ssh deploy@IP_DO_SERVIDOR`) e, de preferência, desligue o login por senha no SSH (`PasswordAuthentication no` em `/etc/ssh/sshd_config`).

## 4. Docker e Caddy

```bash
curl -fsSL https://get.docker.com | sudo sh        # instalador oficial do Docker
sudo usermod -aG docker deploy && newgrp docker
sudo apt -y install caddy                           # servidor HTTPS com certificado automático
```

## 5. Código e configuração

```bash
sudo mkdir -p /opt/sag-cidadao && sudo chown deploy: /opt/sag-cidadao
git clone https://github.com/walace67/sag-cidadao.git /opt/sag-cidadao
cd /opt/sag-cidadao
mkdir -p backups
cp .env.docker.example .env.docker && chmod 600 .env.docker
nano .env.docker
```

No `.env.docker`, para produção:

```
SECRET_KEY=(gere uma nova: python3 -c "import secrets; print(secrets.token_urlsafe(50))")
DEBUG=False
ALLOWED_HOSTS=sag.seudominio.com.br,localhost
CSRF_TRUSTED_ORIGINS=https://sag.seudominio.com.br
HTTPS=True
PROXIES_CONFIAVEIS=2
SITE_URL=https://sag.seudominio.com.br
ADMIN_URL=um-endereco-dificil-de-adivinhar/
DB_PASSWORD=(gere uma senha longa)
PORTA_PUBLICA=127.0.0.1:8088
ADMINS=voce@seudominio.com.br
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=...   EMAIL_PORT=587   EMAIL_HOST_USER=...   EMAIL_HOST_PASSWORD=...
DEFAULT_FROM_EMAIL=SAG-Cidadão <nao-responda@seudominio.com.br>
```

Por que esses valores:

- `PORTA_PUBLICA=127.0.0.1:8088`: o Nginx só aceita conexões do próprio servidor. Ninguém na internet chega nele sem passar pelo Caddy e pelo HTTPS.
- `PROXIES_CONFIAVEIS=2`: Caddy e Nginx ficam na frente do Django. O IP real do cidadão é o segundo a contar do fim do `X-Forwarded-For` (Parte 4, seção 23).
- `localhost` em `ALLOWED_HOSTS`: é por ele que o próprio contêiner confere a saúde (`/saude/`).

## 6. Subir o sistema

```bash
docker compose --env-file .env.docker up -d --build
docker compose --env-file .env.docker ps          # os 4 serviços: db, web, worker, nginx
docker compose --env-file .env.docker exec web python manage.py check --deploy
docker compose --env-file .env.docker exec web python manage.py createsuperuser
docker compose --env-file .env.docker exec web python manage.py tornar_gestor SEU_LOGIN
```

## 7. HTTPS com o Caddy

```bash
sudo tee /etc/caddy/Caddyfile <<'CADDY'
sag.seudominio.com.br {
    reverse_proxy 127.0.0.1:8088
}
CADDY
sudo systemctl reload caddy
```

O Caddy obtém e renova sozinho o certificado Let's Encrypt e redireciona `http://` para `https://`. Abra `https://sag.seudominio.com.br/saude/`: deve aparecer `{"status": "ok", "banco": "ok"}`.

## 8. Agendamentos

`crontab -e` (usuário `deploy`):

```
# Backup do banco e das fotos, todo dia às 2h15
15 2 * * * cd /opt/sag-cidadao && deploy/docker/backup.sh >> backups/backup.log 2>&1
# Monitoramento interno a cada 10 minutos (e-mail para ADMINS se algo falhar)
*/10 * * * * cd /opt/sag-cidadao && docker compose --env-file .env.docker exec -T web python manage.py verificar_sistema > /dev/null
# Retenção LGPD: cadastros não confirmados e sessões vencidas
30 3 * * * cd /opt/sag-cidadao && docker compose --env-file .env.docker exec -T web sh -c "python manage.py limpar_cadastros_pendentes && python manage.py clearsessions"
```

**Cópia fora do servidor (regra 3-2-1):** copie a pasta `backups/` para outro lugar, por exemplo com `rsync` para outra máquina ou para um armazenamento de objetos. Com criptografia ligada (`BACKUP_SENHA_ARQUIVO`), guarde a senha fora do servidor.

**Monitor externo:** em outra máquina, um Uptime Kuma (gratuito) consultando `https://sag.seudominio.com.br/saude/` a cada minuto avisa se o servidor inteiro cair.

## 9. Atualizar para uma nova versão

```bash
cd /opt/sag-cidadao
deploy/docker/backup.sh                                 # sempre um backup antes
git pull --ff-only
docker compose --env-file .env.docker up -d --build     # migrações rodam sozinhas ao subir
docker compose --env-file .env.docker exec web python manage.py check --deploy
```

## 10. Restaurar um backup

```bash
cd /opt/sag-cidadao
docker compose --env-file .env.docker stop web worker nginx
# Banco (descriptografe antes, se usar .gpg: gpg -d arquivo.dump.gpg > arquivo.dump)
docker compose --env-file .env.docker exec -T db pg_restore -U sag -d sag_cidadao --clean --if-exists < backups/diario/banco_AAAA-MM-DD_HHMMSS.dump
docker compose --env-file .env.docker start web
# Fotos
docker compose --env-file .env.docker exec -T web sh -c "rm -rf /app/media/* && tar xzf - -C /app" < backups/diario/fotos_AAAA-MM-DD_HHMMSS.tar.gz
docker compose --env-file .env.docker start worker nginx
```

Ensaie a restauração num servidor de teste antes de precisar dela: backup que nunca foi restaurado não é backup.

## 11. Conferência final

- [ ] `https://sag.seudominio.com.br/saude/` responde `ok`
- [ ] `check --deploy` sem avisos
- [ ] Cadeado do HTTPS válido (teste em ssllabs.com/ssltest)
- [ ] Cabeçalhos de segurança (teste em securityheaders.com)
- [ ] E-mail de ativação de cadastro chega de verdade
- [ ] Verificação em duas etapas configurada para todos os gestores
- [ ] Primeiro backup feito e restaurado num teste
- [ ] `verificar_sistema` sem alertas
