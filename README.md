# SAG-Cidadão

![Testes](https://github.com/walace67/sag-cidadao/actions/workflows/testes.yml/badge.svg)

**Sistema de Atendimento e Gestão de Solicitações ao Cidadão.** Com ele, o morador registra um problema urbano (buraco, iluminação, lixo), acompanha o andamento pelo número de protocolo, e cada secretaria municipal trata as solicitações da sua área. O gestor acompanha tudo por um dashboard de indicadores.

Projeto de estudo e portfólio construído com **Python, Django e PostgreSQL**. Ele aplica na prática os conteúdos de Banco de Dados, Engenharia de Software, Desenvolvimento Web e Segurança da Informação/LGPD.

---

## Funcionalidades

| Perfil | O que faz |
|---|---|
| **Cidadão** | Faz o autocadastro com confirmação por e-mail, abre solicitações com fotos e o ponto no mapa (clique ou GPS do celular), recebe avisos por e-mail a cada mudança, acompanha o andamento e cancela enquanto a solicitação está aberta. Em "Meus dados", vê, corrige e exporta os próprios dados (LGPD). |
| **Servidor** | Usa o painel da sua secretaria com filtros e busca, muda o status de acordo com um fluxo validado, define prioridades e consulta o relatório por zona da cidade. |
| **Gestor** | Vê as solicitações num mapa da cidade, consulta a trilha de auditoria, acompanha o dashboard (volume, cumprimento de prazo, tempo médio, atrasadas e séries diárias), cuida dos cadastros (secretarias, bairros, serviços e áreas de atuação) e gerencia servidores e cidadãos sem usar o admin do Django. |
| **Público** | Consulta pelo protocolo, sem login e sem ver dados pessoais. |
| **API REST** | Autenticação por token, listagem, abertura, mudança de status e cancelamento, com limite de requisições. |

## Arquitetura

```
Navegador ──HTTPS──▶ Nginx ──socket──▶ Gunicorn ──▶ Django ──▶ PostgreSQL
                      │                              │
                 estáticos                    cache (Redis ou tabela)
```

O código é organizado em camadas:

- **Templates** (apresentação)
- **Views** (recebem a requisição e decidem a resposta)
- **services.py**: regras de negócio, como o fluxo de status, o cancelamento e os indicadores
- **Models** (dados e restrições do banco)

As telas e a API chamam os **mesmos** serviços, então uma regra nunca fica duplicada.

## Tecnologias

- Python 3.12, Django 6.1, Django REST Framework
- PostgreSQL 16 (constraints `CHECK` e `UNIQUE`, índices, `UUID`, `select_for_update`)
- Gunicorn, Nginx e systemd
- GitHub Actions (os testes e o `check --deploy` rodam a cada push)
- Nenhuma biblioteca de front-end: o gráfico do dashboard é SVG gerado no servidor

## Segurança e LGPD

- **Controle de acesso por perfil (RBAC):** cada servidor só vê a própria secretaria. Pedir o registro de outra secretaria resulta em 404 (proteção contra IDOR).
- **Proteção contra enumeração de usuários:** o cadastro responde sempre da mesma forma, e o titular verdadeiro recebe um aviso por e-mail.
- **Contas e tokens:** a conta fica inativa até a confirmação. Os links de ativação e de redefinição de senha são de uso único e expiram em 24 h.
- **Limite de tentativas (HTTP 429):** vale para cadastro, login, redefinição de senha, consulta de protocolo e token da API. Depois de 5 senhas erradas, a conta fica bloqueada por 15 minutos.
- **Cabeçalhos de segurança:** CSP com *nonce*, HSTS, `X-Frame-Options: DENY`, `nosniff` e cookies `Secure`, `HttpOnly` e `SameSite`.
- **IP do cliente atrás do proxy:** o sistema só confia no IP informado pelo proxy próprio (o cliente pode forjar o `X-Forwarded-For`).
- **Logs de segurança:** bloqueios e excessos de tentativas são registrados sem CPF e sem senha.
- **LGPD:**
  - aviso de privacidade;
  - minimização de dados (o CPF aparece mascarado);
  - direitos de acesso, correção e portabilidade em JSON (art. 18);
  - cadastros não confirmados são apagados após 24 h.
- **Verificação em duas etapas (TOTP)** obrigatória para servidores e gestores: QR code, códigos de recuperação, segredo cifrado no banco, proteção contra repetição do código; vale também para o admin e para o token da API.
- **Trilha de auditoria imutável:** entradas, falhas de login, alterações de cadastro (antes e depois), papéis, bloqueios e exportação de dados. Um trigger do PostgreSQL recusa `UPDATE` e `DELETE`.
- **Fotos sem dados escondidos:** cada imagem é regravada do zero, o que apaga a localização GPS e os demais metadados EXIF. Arquivos disfarçados e bombas de descompressão são recusados. As fotos não têm endereço público: cada acesso passa pela autorização, e o Nginx entrega o arquivo (`X-Accel-Redirect`).
- **Segredos:** ficam só no `.env`, que não vai para o Git.

## Como rodar (desenvolvimento)

```bash
git clone https://github.com/walace67/sag-cidadao.git
cd sag-cidadao
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # preencha SECRET_KEY e DB_PASSWORD
python manage.py migrate
python manage.py createsuperuser
python manage.py tornar_gestor SEU_LOGIN
python manage.py popular_demo  # dados de demonstração para o dashboard
python manage.py runserver
```

Em desenvolvimento, os e-mails (ativação, redefinição de senha) aparecem **no terminal** do `runserver`.

## Testes

```bash
python manage.py test
```

São 104 testes automatizados. Eles cobrem:

- o fluxo de status e as constraints do banco;
- o controle de acesso (403/404);
- a ausência de N+1 (`assertNumQueries`);
- a API (200, 201, 401, 403, 404, 405, 409, 429);
- a proteção contra enumeração, os bloqueios e os cabeçalhos de segurança.

## Implantação (produção)

Os arquivos ficam em [`deploy/`](deploy/):

| Arquivo | Função |
|---|---|
| `gunicorn.conf.py` | Servidor de aplicação: workers, timeouts e socket Unix |
| `nginx/sag-cidadao.conf` | Proxy reverso: HTTPS, estáticos e cabeçalhos do proxy |
| `systemd/sag-cidadao.service` | Mantém o serviço no ar com usuário sem privilégios |
| `systemd/sag-limpeza.timer` | Retenção LGPD diária (cadastros pendentes e sessões expiradas) |
| `atualizar.sh` | Atualiza a versão: `git pull`, `migrate`, `collectstatic`, reload e health check |

O endpoint `GET /saude/` responde 200 quando a aplicação e o banco estão funcionando, e 503 quando não estão. Ele serve para o monitoramento.

## Backup e restauração

Os scripts ficam em [`deploy/backup/`](deploy/backup/) e leem as credenciais do mesmo `.env` do Django.

```bash
deploy/backup/backup.sh                  # pg_dump -Fc + SHA-256 + rotação + cópia externa
deploy/backup/testar_restauracao.sh      # restaura num banco temporário e compara tabela a tabela
deploy/backup/restaurar.sh               # restaura numa CÓPIA (<banco>_restaurado), sem tocar no banco em uso
deploy/backup/restaurar.sh --substituir  # desastre: troca o banco, guardando o anterior para desfazer
```

O que os scripts garantem:

- **Consistência:** o `pg_dump` lê uma foto do banco (snapshot MVCC), e o sistema continua no ar durante o backup.
- **Nenhum arquivo pela metade:** o backup é gravado como `.parcial` e só é renomeado depois de conferido com `pg_restore --list`.
- **Integridade:** um checksum SHA-256 é conferido antes de qualquer restauração.
- **Proteção dos dados (LGPD, art. 46):**
  - criptografia AES-256 opcional;
  - permissão `600` nos arquivos;
  - o arquivo descriptografado nunca fica no disco.
- **Rotação GFS:** 7 backups diários, 4 semanais e 6 mensais, usando *hard links* (não ocupa espaço extra).
- **Regra 3-2-1:** cópia opcional para um HD externo ou outro servidor (`rsync`).
- **Restauração reversível:** o banco substituído é renomeado, nunca apagado.
- **Teste semanal automático:** ele informa o tempo de restauração (base do RTO) e a idade do último backup (o RPO).

Para agendar, use os arquivos `systemd/sag-backup.timer` (diário, 2h) e `systemd/sag-teste-backup.timer` (domingo, 4h).

## Conteúdos de concurso aplicados

| Matéria | Onde está no projeto |
|---|---|
| Banco de Dados | Modelagem ER, chaves, N:N com tabela associativa, constraints, índices, transações (ACID), `SELECT ... FOR UPDATE`, agregações |
| Engenharia de Software | Requisitos, camadas, MVT/MVC, máquina de estados, testes automatizados, CI |
| Desenvolvimento Web | HTTP (métodos e códigos), REST, PRG, CSRF, sessões e cookies, templates |
| Segurança | OWASP Top 10 (A01, A05, A07), autenticação x autorização, hash de senha, rate limiting, CSP, HSTS, menor privilégio |
| LGPD | Bases legais (art. 7º, III e art. 23), princípios (art. 6º), direitos do titular (art. 18), retenção |
| Infraestrutura | Proxy reverso, WSGI, systemd, variáveis de ambiente (12-Factor), Git |
| Backup | Backup lógico x físico, completo/incremental/diferencial, RPO e RTO, regra 3-2-1, GFS, teste de restauração |

---

Projeto educacional. Os dados de demonstração são fictícios.
