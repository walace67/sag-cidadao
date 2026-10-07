"""
Teste de carga do SAG-Cidadão com o Locust.

    python manage.py preparar_carga --saida deploy/qa/carga.json
    locust -f deploy/qa/locustfile.py --host http://localhost \
           --headless -u 100 -r 10 -t 2m --html relatorio-carga.html

-u = usuários simultâneos; -r = quantos entram por segundo; -t = duração.

Cada "usuário" do Locust é um robô que repete um comportamento realista,
com pausas entre as ações (wait_time), como uma pessoa lendo a tela.
A proporção entre os perfis vem do peso (weight): para cada gestor,
há 3 servidores e 12 cidadãos.

Rode contra o ensaio de PRODUÇÃO (Nginx + Gunicorn, DEBUG=False), nunca
contra o runserver, e nunca contra o servidor de produção de verdade.
"""
import json
import random
import re
from pathlib import Path

from locust import HttpUser, between, task

DADOS = json.loads((Path(__file__).parent / "carga.json").read_text(encoding="utf-8"))
CSRF = re.compile(r'name="csrfmiddlewaretoken" value="([^"]+)"')


class Base(HttpUser):
    abstract = True
    perfil = None

    def on_start(self):
        sessao = random.choice(DADOS[self.perfil])
        self.dados = sessao
        self.client.cookies.set(sessao["name"], sessao["value"])


class Cidadao(Base):
    perfil = "cidadaos"
    weight = 12
    wait_time = between(3, 8)

    @task(5)
    def minhas(self):
        self.client.get("/minhas/", name="cidadão: minhas solicitações")

    @task(2)
    def meus_dados(self):
        self.client.get("/meus-dados/", name="cidadão: meus dados")

    @task(1)
    def abrir_solicitacao(self):
        tela = self.client.get("/nova/", name="cidadão: tela nova")
        token = CSRF.search(tela.text)
        if not token:
            return
        self.client.post("/nova/", name="cidadão: enviar solicitação", data={
            "csrfmiddlewaretoken": token.group(1),
            "categoria": random.choice(DADOS["categorias"]), "bairro": self.dados["bairro"],
            "endereco_referencia": "Rua do teste de carga, 100",
            "descricao": "Solicitação criada pelo teste de carga automatizado.",
            "latitude": f"{-8.76 + random.uniform(-0.03, 0.03):.6f}",
            "longitude": f"{-63.88 + random.uniform(-0.03, 0.03):.6f}",
        }, headers={"Referer": self.host + "/nova/"})


class Servidor(Base):
    perfil = "servidores"
    weight = 3
    wait_time = between(2, 5)

    @task(4)
    def painel(self):
        self.client.get("/painel/", name="servidor: painel")

    @task(2)
    def painel_filtrado(self):
        self.client.get("/painel/?status=ABE", name="servidor: painel filtrado")

    @task(3)
    def detalhe(self):
        if self.dados["solicitacoes"]:
            pk = random.choice(self.dados["solicitacoes"])
            self.client.get(f"/solicitacao/{pk}/", name="servidor: detalhe")


class Gestor(Base):
    perfil = "gestores"
    weight = 1
    wait_time = between(5, 10)

    @task(3)
    def dashboard(self):
        self.client.get("/gestao/?dias=30", name="gestor: dashboard")

    @task(1)
    def mapa(self):
        self.client.get("/gestao/mapa/dados/?dias=30", name="gestor: dados do mapa")


class Monitor(HttpUser):
    """Como o Uptime Kuma: consulta a saúde a cada poucos segundos."""

    weight = 1
    fixed_count = 1
    wait_time = between(5, 5)

    @task
    def saude(self):
        self.client.get("/saude/", name="monitor: /saude/")
