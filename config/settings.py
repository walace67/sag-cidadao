"""
SAG-Cidadão — configurações do projeto (Django 6.1)

Regra de ouro (12-Factor App, fator III): o CÓDIGO é o mesmo em todo lugar;
o que muda entre desenvolvimento e produção vem do AMBIENTE (arquivo .env,
lido pelo python-decouple). Segredos nunca ficam no código nem no Git.

Seguro por padrão (fail-safe defaults): sem .env, o sistema sobe em modo
PRODUÇÃO (DEBUG desligado, HTTPS obrigatório). Para desenvolver, o .env da
sua máquina liga DEBUG=True. Esquecer o .env no servidor nunca deixa o
sistema aberto; no máximo, ele se recusa a subir.

Veja o .env.example para a lista completa de variáveis.
"""
import sys
from pathlib import Path

from decouple import Csv, config
from django.utils.csp import CSP

BASE_DIR = Path(__file__).resolve().parent.parent

# Rodando "manage.py test"? Alguns ajustes valem só para os testes.
TESTANDO = len(sys.argv) > 1 and sys.argv[1] == "test"


# ---------------------------------------------------------------------------
# Núcleo: chave, modo e hosts
# ---------------------------------------------------------------------------
# A SECRET_KEY assina sessões, tokens de ativação e de redefinição de senha.
# Quem a conhece consegue forjar esses tokens. Sem default: se faltar no
# .env, o Django NÃO sobe (melhor quebrar do que rodar com chave conhecida).
SECRET_KEY = config("SECRET_KEY", default="chave-apenas-para-testes" if TESTANDO else None)

# DEBUG=True mostra código-fonte, variáveis e SQL na tela de erro.
# Em produção isso é vazamento de informação (OWASP A05).
DEBUG = config("DEBUG", default=False, cast=bool)

# Hosts aceitos no cabeçalho Host. Protege contra "Host header injection",
# por exemplo, links de redefinição de senha apontando para outro domínio.
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())

# Origens confiáveis para POST via HTTPS (proteção CSRF), ex.:
#   CSRF_TRUSTED_ORIGINS=https://sag.exemplo.gov.br
CSRF_TRUSTED_ORIGINS = config("CSRF_TRUSTED_ORIGINS", default="", cast=Csv())

# Endereço do admin do Django. Trocar o padrão "admin/" reduz o ruído de
# robôs que varrem a internet (não é proteção suficiente sozinho: o admin
# continua exigindo login e o limite de tentativas).
ADMIN_URL = config("ADMIN_URL", default="admin/")


# ---------------------------------------------------------------------------
# Aplicações e middlewares
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework.authtoken",
    "apps.atendimento",
    "apps.gestao",
    "apps.auditoria",
    "django_tasks_db",  # fila de tarefas guardada no PostgreSQL
    "apps.doisfatores",
    "apps.govbr",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",          # HTTPS, HSTS, nosniff
    "django.middleware.csp.ContentSecurityPolicyMiddleware",  # CSP (novo no Django 6)
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "apps.doisfatores.middleware.VerificacaoDuasEtapasMiddleware",  # segunda etapa em todas as rotas
    "django.middleware.clickjacking.XFrameOptionsMiddleware",  # X-Frame-Options
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.template.context_processors.csp",  # {{ csp_nonce }}
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.atendimento.contexto.mapa",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# ---------------------------------------------------------------------------
# Banco de dados (PostgreSQL)
# ---------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("DB_NAME", default="sag_cidadao"),
        "USER": config("DB_USER", default="sag"),
        "PASSWORD": config("DB_PASSWORD", default=""),
        "HOST": config("DB_HOST", default="localhost"),
        "PORT": config("DB_PORT", default="5432"),
        # Reaproveita a conexão por até 60 s em vez de abrir uma por requisição
        "CONN_MAX_AGE": config("DB_CONN_MAX_AGE", default=60, cast=int),
        "CONN_HEALTH_CHECKS": True,  # testa a conexão reaproveitada antes de usar
    }
}


# ---------------------------------------------------------------------------
# Cache: onde ficam os contadores de tentativas (rate limiting)
# ---------------------------------------------------------------------------
# Em produção o Gunicorn roda VÁRIOS processos. Com cache em memória, cada
# processo contaria separado e o limite real seria multiplicado. Por isso:
#   - REDIS_URL definido -> Redis (compartilhado e rápido)
#   - produção sem Redis -> tabela no próprio PostgreSQL (compartilhada)
#   - desenvolvimento/testes -> memória local
REDIS_URL = config("REDIS_URL", default="")
if REDIS_URL:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL}}
elif DEBUG or TESTANDO:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
else:
    # Requer, uma vez: python manage.py createcachetable
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.db.DatabaseCache", "LOCATION": "sag_cache"}}


# ---------------------------------------------------------------------------
# Senhas
# ---------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

if TESTANDO:
    # O PBKDF2 é lento DE PROPÓSITO (centenas de milhares de iterações) para
    # atrasar quem tenta quebrar senhas vazadas. Nos testes isso só gasta
    # tempo, então usamos um hash rápido. NUNCA em produção.
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


# ---------------------------------------------------------------------------
# Idioma, fuso e arquivos estáticos
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Porto_Velho"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
# Destino do "collectstatic": o Nginx serve esta pasta direto, sem passar
# pelo Python (mais rápido). O runserver só serve estáticos com DEBUG=True.
STATIC_ROOT = config("STATIC_ROOT", default=str(BASE_DIR / "staticfiles"))


# Fotos enviadas: FORA da pasta de estáticos e sem URL pública.
# Quem entrega é a view atendimento:foto, depois de checar a permissão.
MEDIA_ROOT = config("MEDIA_ROOT", default=str(BASE_DIR / "media"))
# Em produção, o Nginx entrega o arquivo autorizado (X-Accel-Redirect)
SERVIR_MIDIA_COM_NGINX = config("SERVIR_MIDIA_COM_NGINX", default=False, cast=bool)

# Mapa (OpenStreetMap). Limites aproximados do município de Porto Velho
# (sul, norte, oeste, leste), usados para recusar pontos fora da cidade.
MAPA_CENTRO = (-8.7612, -63.9004)
MAPA_LIMITES = (-10.95, -7.95, -66.85, -62.20)
MAPA_TILES = config("MAPA_TILES", default="https://tile.openstreetmap.org/{z}/{x}/{y}.png")
MAPA_TILES_ORIGEM = config("MAPA_TILES_ORIGEM", default="https://tile.openstreetmap.org")


# ---------------------------------------------------------------------------
# HTTPS e cabeçalhos de segurança
# ---------------------------------------------------------------------------
# HTTPS=True exige certificado (Let's Encrypt). Para ensaiar a produção na
# sua máquina, sem certificado, use DEBUG=False e HTTPS=False.
HTTPS = config("HTTPS", default=not DEBUG, cast=bool) and not TESTANDO

# O Nginx recebe o HTTPS e repassa ao Gunicorn em HTTP; este cabeçalho
# avisa o Django de que a conexão original era segura.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = HTTPS        # http:// -> https://
SESSION_COOKIE_SECURE = HTTPS      # cookie de sessão só trafega em HTTPS
CSRF_COOKIE_SECURE = HTTPS
# HSTS: o NAVEGADOR passa a recusar http:// para este site pelo tempo
# indicado. Comece com 1 hora; depois de confirmar que o HTTPS está
# estável, aumente para 1 ano (31536000).
SECURE_HSTS_SECONDS = config("SECURE_HSTS_SECONDS", default=3600, cast=int) if HTTPS else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = config("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=True, cast=bool)
SECURE_HSTS_PRELOAD = config("SECURE_HSTS_PRELOAD", default=False, cast=bool)
# HSTS preload grava o domínio na lista embutida dos navegadores; é difícil
# de desfazer, então fica como decisão explícita de quem administra o domínio.
SILENCED_SYSTEM_CHECKS = ["security.W021"]

SESSION_COOKIE_HTTPONLY = True     # JavaScript não lê o cookie de sessão (XSS)
SESSION_COOKIE_SAMESITE = "Lax"    # não vai em POSTs vindos de outros sites (CSRF)
SESSION_COOKIE_AGE = 60 * 60 * 8   # sessão de 8 horas (uma jornada de trabalho)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"           # ninguém exibe o sistema num <iframe>

# CSP (Content Security Policy): lista do que o navegador pode carregar.
# Scripts só do próprio site ou com o "nonce" (número único por resposta)
# que o servidor coloca nos <script> legítimos. Um <script> injetado por um
# atacante (XSS) não tem o nonce e é bloqueado pelo navegador.
# Estilos inline são permitidos: o layout usa style="..." (risco baixo).
SECURE_CSP = {
    "default-src": [CSP.SELF],
    "script-src": [CSP.SELF, CSP.NONCE],
    "style-src": [CSP.SELF, CSP.UNSAFE_INLINE],
    # Mapa: as imagens dos "azulejos" (tiles) vêm do servidor de mapas
    "img-src": [CSP.SELF, "data:", MAPA_TILES_ORIGEM],
    "object-src": [CSP.NONE],
    "base-uri": [CSP.SELF],
    "form-action": [CSP.SELF],
    "frame-ancestors": [CSP.NONE],
}


# ---------------------------------------------------------------------------
# Proxy reverso: em qual cabeçalho confiar para saber o IP do cliente
# ---------------------------------------------------------------------------
# Atrás do Nginx, REMOTE_ADDR é sempre 127.0.0.1 (o próprio Nginx). O IP
# real vem no X-Forwarded-For, mas o CLIENTE também pode escrever esse
# cabeçalho, então só se confia nele quando há um proxy nosso na frente.
# CONFIAR_PROXY=True apenas quando o Gunicorn estiver acessível SÓ pelo Nginx.
CONFIAR_PROXY = config("CONFIAR_PROXY", default=False, cast=bool)
# Quantos proxies NOSSOS ficam na frente do Django. Cada um ACRESCENTA um
# endereço ao X-Forwarded-For; o IP real do cliente é o N-ésimo a contar
# do fim. Nginx sozinho = 1; Caddy (HTTPS) + Nginx (Docker) = 2.
PROXIES_CONFIAVEIS = config("PROXIES_CONFIAVEIS", default=1 if CONFIAR_PROXY else 0, cast=int)


# ---------------------------------------------------------------------------
# E-mail (formato MAILERS do Django 6.1)
# ---------------------------------------------------------------------------
# Em desenvolvimento, as mensagens aparecem no TERMINAL do runserver.
# Em produção: EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
MAILERS = {
    "default": {
        "BACKEND": config("EMAIL_BACKEND", default="apps.atendimento.email_console.EmailBackend"),
        "OPTIONS": {
            k: v for k, v in {
                "host": config("EMAIL_HOST", default=""),
                "port": config("EMAIL_PORT", default=587, cast=int),
                "username": config("EMAIL_HOST_USER", default=""),
                "password": config("EMAIL_HOST_PASSWORD", default=""),
                "use_tls": config("EMAIL_USE_TLS", default=True, cast=bool),
            }.items()
            if "smtp" in config("EMAIL_BACKEND", default="console")
        },
    },
}
# Endereço público do sistema, usado nos links dos e-mails enviados em
# segundo plano (lá não existe requisição para descobrir o domínio).
SITE_URL = config("SITE_URL", default="http://127.0.0.1:8000").rstrip("/")


# ---------------------------------------------------------------------------
# Tarefas em segundo plano (django.tasks, nativo do Django 6)
# ---------------------------------------------------------------------------
# Enviar e-mail é LENTO e pode FALHAR (servidor SMTP fora do ar). Por isso
# a tela só ENFILEIRA o envio, e um processo separado (o "worker") executa:
#     python manage.py db_worker
# Em desenvolvimento e nos testes, o envio acontece na hora (Immediate).
TASKS = {
    "default": {
        "BACKEND": config(
            "TASKS_BACKEND",
            default="django.tasks.backends.immediate.ImmediateBackend"
            if (DEBUG or TESTANDO) else "django_tasks_db.DatabaseBackend",
        ),
    }
}

DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="SAG-Cidadão <nao-responda@sag-cidadao.local>")

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "atendimento:inicio"
LOGOUT_REDIRECT_URL = "atendimento:inicio"

# Verificação em duas etapas obrigatória para a equipe (servidores,
# gestores e administradores). Desligue só em desenvolvimento, se quiser.
EXIGIR_2FA_EQUIPE = config("EXIGIR_2FA_EQUIPE", default=not TESTANDO, cast=bool)

# Login com a conta gov.br (OpenID Connect). Desligado enquanto não houver
# credenciais: a Prefeitura solicita o credenciamento no Login Único e
# recebe client_id e client_secret, primeiro em homologação.
GOVBR_CLIENT_ID = config("GOVBR_CLIENT_ID", default="")
GOVBR_CLIENT_SECRET = config("GOVBR_CLIENT_SECRET", default="")
GOVBR_AMBIENTE = config("GOVBR_AMBIENTE", default="homologacao")  # ou "producao"
# Endereço de retorno cadastrado no gov.br (vazio = calculado pela requisição)
GOVBR_REDIRECT_URI = config("GOVBR_REDIRECT_URI", default="")

# Validade dos links de ativação de cadastro e de redefinição de senha
PASSWORD_RESET_TIMEOUT = 60 * 60 * 24  # 24 horas


# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    # Token para clientes externos (app, outro sistema); sessão para a
    # API navegável no navegador, já logado.
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    # Fechado por padrão: cada endpoint público precisa liberar explicitamente.
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    # Limite de requisições (responde 429 Too Many Requests)
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/min",
        "user": "300/min",
        "token": "10/min",      # POST /api/token/ (força bruta de senha)
        "protocolo": "30/min",  # consulta pública por protocolo
    },
    # ATENÇÃO: o padrão do DRF (None) usa o X-Forwarded-For INTEIRO como
    # identidade, e o cliente pode inventar esse cabeçalho a cada requisição
    # para escapar do limite. 0 = usa REMOTE_ADDR; 1 = confia no último
    # endereço, o que o nosso Nginx acrescentou.
    "NUM_PROXIES": PROXIES_CONFIAVEIS,
}
# Em produção, só JSON: a API "navegável" (HTML) fica para desenvolvimento.
if not DEBUG:
    REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = ["rest_framework.renderers.JSONRenderer"]


# ---------------------------------------------------------------------------
# Logs e alertas
# ---------------------------------------------------------------------------
# Quem recebe os alertas de erro e do monitoramento (separe por vírgula):
#   ADMINS=ti@portovelho.ro.gov.br,plantao@portovelho.ro.gov.br
ADMINS = config("ADMINS", default="", cast=Csv())
SERVER_EMAIL = config("SERVER_EMAIL", default=DEFAULT_FROM_EMAIL)
# Tudo vai para a saída padrão; em produção o systemd guarda no journal:
#   journalctl -u sag-cidadao -f
# O logger "sag.seguranca" registra bloqueios e limites estourados (trilha de
# auditoria, útil para incidentes: LGPD art. 46 e 48). Sem CPF completo nem
# senha no log: dado pessoal em log também é tratamento de dado pessoal.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "padrao": {"format": "{asctime} {levelname} {name}: {message}", "style": "{"},
    },
    "filters": {
        # Só manda e-mail de erro com DEBUG desligado (em produção)
        "producao": {"()": "django.utils.log.RequireDebugFalse"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "padrao"},
        "alerta_email": {
            "class": "apps.atendimento.alertas.AlertaPorEmail",
            "level": "ERROR", "filters": ["producao"],
            "include_html": False,  # sem a página de erro completa (pode ter dados pessoais)
        },
    },
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        "django": {"handlers": ["console"], "level": config("LOG_LEVEL", default="INFO"), "propagate": False},
        # Erros 500: log + e-mail para os ADMINS
        "django.request": {"handlers": ["console", "alerta_email"], "level": "WARNING", "propagate": False},
        "sag": {"handlers": ["console", "alerta_email"], "level": "INFO", "propagate": False},
    },
}
if TESTANDO:
    # Nos testes, os bloqueios são provocados de propósito: não poluir a saída.
    LOGGING["loggers"]["sag"]["level"] = "CRITICAL"
    LOGGING["loggers"]["django"]["level"] = "CRITICAL"
    LOGGING["loggers"]["django.request"]["level"] = "CRITICAL"
