# SAG-Cidadão: imagem da aplicação (Django + Gunicorn)
#
#   docker compose --env-file .env.docker up -d --build
#
# Contêiner = um processo isolado com tudo de que precisa (Python, bibliotecas,
# código), igual em qualquer máquina. Diferente de uma máquina virtual, não
# carrega um sistema operacional inteiro: usa o núcleo (kernel) do host.

FROM python:3.12-slim

# Sem arquivos .pyc e com logs saindo na hora (não presos em buffer)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Usuário sem privilégios: se a aplicação for invadida, o atacante não é root
RUN useradd --system --uid 1000 --create-home sag

WORKDIR /app

# As dependências vêm ANTES do código: o Docker reaproveita esta camada
# (cache) enquanto o requirements.txt não mudar, e o build fica rápido.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=sag:sag . .

# Pastas que viram volumes: criadas aqui com o dono certo, para o volume
# nascer com essas permissões
RUN mkdir -p /app/staticfiles /app/media && chown -R sag:sag /app/staticfiles /app/media \
    && chmod +x /app/deploy/docker/entrypoint.sh

USER sag
EXPOSE 8000

ENTRYPOINT ["/app/deploy/docker/entrypoint.sh"]
CMD ["gunicorn", "-c", "deploy/gunicorn.conf.py", "config.wsgi"]
