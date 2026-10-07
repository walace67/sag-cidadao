"""
Auditoria AUTOMÁTICA de acessibilidade em todas as telas do sistema.

    python manage.py auditar_acessibilidade --url http://127.0.0.1:8000

Abre cada tela num navegador de verdade (Chromium, pelo Playwright), como
cidadão, servidor e gestor, e roda o axe-core, o motor de testes de
acessibilidade mais usado no mercado, com as regras da WCAG 2.1 níveis A
e AA, que são a base do eMAG 3.1 (Modelo de Acessibilidade em Governo
Eletrônico).

Requer as ferramentas de desenvolvimento:  pip install -r requirements-dev.txt
                                           playwright install chromium

Atenção: a ferramenta encontra uns 30 a 40% dos problemas. O resto exige
teste humano: navegar só pelo teclado e usar um leitor de tela (NVDA,
Orca). Código de saída diferente de 0 = há violações.
"""
import json
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.urls import reverse

from apps.atendimento.ferramentas import criar_sessao
from apps.atendimento.models import Cidadao, Servidor, Solicitacao
from apps.gestao.permissoes import GRUPO_GESTOR

AXE = Path(settings.BASE_DIR) / "deploy" / "qa" / "vendor" / "axe.min.js"
REGRAS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]
User = get_user_model()


class Command(BaseCommand):
    help = "Audita a acessibilidade (WCAG 2.1 AA / eMAG) de todas as telas com o axe-core."

    def add_arguments(self, parser):
        parser.add_argument("--url", default="http://127.0.0.1:8000")
        parser.add_argument("--relatorio", default="relatorio-acessibilidade.json")

    def telas(self):
        anonimo = [("Início", "/"), ("Entrar", reverse("login")), ("Criar conta", reverse("atendimento:cadastro")),
                   ("Consultar protocolo", reverse("atendimento:consulta")), ("Privacidade", reverse("atendimento:privacidade")),
                   ("Acessibilidade", reverse("atendimento:acessibilidade")), ("Esqueci a senha", reverse("password_reset"))]
        cidadao = Cidadao.objects.filter(usuario__is_active=True, solicitacoes__isnull=False).select_related("usuario").first()
        servidor = Servidor.objects.filter(usuario__is_active=True, secretaria__categorias__solicitacoes__isnull=False).select_related("usuario").first()
        gestor = User.objects.filter(is_active=True, groups__name=GRUPO_GESTOR).first() or User.objects.filter(is_superuser=True, is_active=True).first()
        if not (cidadao and servidor and gestor):
            raise CommandError("Faltam dados: rode 'python manage.py popular_demo' e tenha um gestor (tornar_gestor).")
        sol = Solicitacao.objects.filter(categoria__secretaria=servidor.secretaria).first()
        return [
            (None, anonimo),
            (cidadao.usuario, [("Minhas solicitações", reverse("atendimento:minhas")), ("Nova solicitação", reverse("atendimento:nova")),
                               ("Meus dados", reverse("atendimento:meus_dados")), ("Segurança da conta", reverse("doisfatores:situacao"))]),
            (servidor.usuario, [("Painel", reverse("atendimento:painel")), ("Detalhe", reverse("atendimento:detalhe", args=[sol.pk])),
                                ("Relatório", reverse("atendimento:relatorio"))]),
            (gestor, [("Dashboard", reverse("gestao:dashboard")), ("Mapa", reverse("gestao:mapa")),
                      ("Cadastro: secretarias", reverse("gestao:cadastro_lista", args=["secretarias"])),
                      ("Nova categoria", reverse("gestao:cadastro_novo", args=["categorias"])),
                      ("Servidores", reverse("gestao:servidores")), ("Cidadãos", reverse("gestao:cidadaos")),
                      ("Auditoria", reverse("auditoria:lista"))]),
        ]

    def handle(self, url, relatorio, **opcoes):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise CommandError("Instale as ferramentas de desenvolvimento: pip install -r requirements-dev.txt")
        import os
        os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")  # ORM + Playwright no mesmo processo

        resultado, total = [], 0
        grupos = self.telas()
        with sync_playwright() as p:
            navegador = p.chromium.launch()
            for usuario, telas in grupos:
                # bypass_csp: a nossa CSP bloquearia o script do axe (prova de que funciona)
                contexto = navegador.new_context(viewport={"width": 1280, "height": 900}, locale="pt-BR", bypass_csp=True)
                if usuario is not None:
                    cookie = criar_sessao(usuario)
                    contexto.add_cookies([{**cookie, "url": url}])
                pagina = contexto.new_page()
                for nome, caminho in telas:
                    pagina.goto(url + caminho, wait_until="networkidle")
                    pagina.add_script_tag(path=str(AXE))
                    achados = pagina.evaluate(
                        "regras => axe.run(document, {runOnly: {type: 'tag', values: regras}}).then(r => r.violations)", REGRAS)
                    total += len(achados)
                    perfil = "visitante" if usuario is None else usuario.get_username()
                    marca = self.style.SUCCESS("OK ") if not achados else self.style.ERROR(f"{len(achados)} problema(s)")
                    self.stdout.write(f"{marca}  {nome}  ({perfil})")
                    for a in achados:
                        self.stdout.write(f"      [{a['impact']}] {a['id']}: {a['help']} ({len(a['nodes'])} elemento(s))")
                        for n in a["nodes"][:3]:
                            self.stdout.write(f"          {n['target']}")
                    resultado.append({"tela": nome, "caminho": caminho, "perfil": perfil, "violacoes": achados})
                contexto.close()
            navegador.close()

        Path(relatorio).write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
        telas = sum(len(t) for _, t in grupos)
        if total:
            raise CommandError(f"{total} violação(ões) em {telas} telas. Detalhes em {relatorio}.")
        self.stdout.write(self.style.SUCCESS(f"Nenhuma violação automática nas {telas} telas (WCAG 2.1 A/AA)."))
