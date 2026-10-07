"""
Gunicorn: o servidor de aplicação WSGI que roda o Django em produção.
(O runserver é só para desenvolvimento: um processo, sem segurança.)

    gunicorn -c deploy/gunicorn.conf.py config.wsgi

Arquitetura:
    Navegador --HTTPS--> Nginx (porta 443) --socket--> Gunicorn --> Django --> PostgreSQL
    O Nginx cuida de HTTPS, arquivos estáticos e clientes lentos;
    o Gunicorn só executa Python.
"""
import multiprocessing

# "config" é o nome de uma opção do próprio Gunicorn: todo nome de nível de
# módulo neste arquivo vira configuração. Por isso o apelido "ler_env".
from decouple import config as ler_env

# Socket Unix: só processos da própria máquina (o Nginx) alcançam o Gunicorn.
# Para ensaio local sem socket: GUNICORN_BIND=127.0.0.1:8000
bind = ler_env("GUNICORN_BIND", default="unix:/run/sag-cidadao/gunicorn.sock")
# Permissão padrão do que o Gunicorn cria. 0o007 (padrão): socket e pastas
# de fotos acessíveis ao dono e ao grupo www-data (o do Nginx). No Docker,
# o Nginx roda com outro usuário: lá se usa 0o022 (leitura para todos).
umask = int(ler_env("GUNICORN_UMASK", default="0o007"), 8)

# Fórmula clássica: 2 x núcleos + 1 processos (workers)
workers = ler_env("GUNICORN_WORKERS", default=multiprocessing.cpu_count() * 2 + 1, cast=int)
timeout = 30            # requisição presa por mais de 30 s: o worker é reiniciado
graceful_timeout = 30
max_requests = 1000     # recicla o worker a cada 1000 requisições (contém vazamento de memória)
max_requests_jitter = 100

accesslog = "-"         # logs na saída padrão -> journal do systemd
errorlog = "-"
loglevel = "info"
