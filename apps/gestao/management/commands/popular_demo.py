"""
Gera dados de DEMONSTRAÇÃO para o dashboard (portfólio e estudo).

    python manage.py popular_demo                 # 150 solicitações nos últimos 60 dias
    python manage.py popular_demo --quantidade 300
    python manage.py popular_demo --limpar        # remove só os dados de demonstração

Os dados de demonstração são marcados pelo e-mail @demo.sag, para que
possam ser removidos sem tocar nos seus registros reais. Senha dos
usuários de demonstração: Teste@2026. As zonas dos bairros são ilustrativas.
"""
import random
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.atendimento.models import (
    AreaAtuacao, Bairro, CategoriaServico, Cidadao, HistoricoSolicitacao,
    Secretaria, Servidor, Solicitacao,
)

DOMINIO = "@demo.sag"
SENHA = "Teste@2026"

SECRETARIAS = {
    "SEMOB": ("Secretaria Municipal de Obras", [("Tapa-buraco", 30), ("Drenagem", 45), ("Calçada danificada", 30)]),
    "SEMUSB": ("Secretaria Municipal de Serviços Básicos", [("Iluminação pública", 10), ("Coleta de lixo", 3), ("Limpeza de terreno", 15)]),
    "SEMA": ("Secretaria Municipal de Meio Ambiente", [("Poda de árvore", 20), ("Descarte irregular", 10)]),
    "SEMTRAN": ("Secretaria Municipal de Trânsito", [("Sinalização", 15), ("Semáforo com defeito", 2)]),
}
BAIRROS = [
    ("Centro", "CEN"), ("Nova Porto Velho", "SUL"), ("Embratel", "SUL"), ("Caladinho", "SUL"),
    ("Aponiã", "NOR"), ("Nacional", "NOR"), ("Ulisses Guimarães", "LES"), ("Tancredo Neves", "LES"),
    ("Lagoa", "LES"), ("Jaci-Paraná", "DIS"),
]
NOMES = ["Ana", "Bruno", "Carla", "Diego", "Elaine", "Felipe", "Gabriela", "Hugo", "Isabela", "João",
         "Karen", "Lucas", "Mariana", "Nelson", "Olívia", "Paulo", "Rafaela", "Sérgio", "Tatiane", "Vítor"]
SOBRENOMES = ["Almeida", "Barbosa", "Cardoso", "Dias", "Ferreira", "Gomes", "Lima", "Moura", "Nunes", "Pereira", "Rocha", "Souza"]
DESCRICOES = {
    "Tapa-buraco": "Buraco grande na pista, carros desviando pela contramão.",
    "Drenagem": "Bueiro entupido; a rua alaga em qualquer chuva.",
    "Calçada danificada": "Calçada quebrada em frente à escola, risco para pedestres.",
    "Iluminação pública": "Postes apagados no quarteirão inteiro há uma semana.",
    "Coleta de lixo": "Coleta não passou nos últimos dias; lixo acumulado na esquina.",
    "Limpeza de terreno": "Terreno baldio com mato alto e foco de mosquitos.",
    "Poda de árvore": "Galhos encostando na rede elétrica.",
    "Descarte irregular": "Entulho e móveis descartados na calçada.",
    "Sinalização": "Faixa de pedestres apagada perto do posto de saúde.",
    "Semáforo com defeito": "Semáforo piscando amarelo no cruzamento, trânsito confuso.",
}


def gerar_cpf(rng):
    """Gera um CPF com dígitos verificadores válidos (apenas para testes)."""
    base = [rng.randint(0, 9) for _ in range(9)]
    for tamanho in (9, 10):
        soma = sum(d * (tamanho + 1 - i) for i, d in enumerate(base[:tamanho]))
        base.append((soma * 10 % 11) % 10)
    return "".join(map(str, base))


class Command(BaseCommand):
    help = "Gera (ou remove) dados de demonstração para o dashboard."

    def add_arguments(self, parser):
        parser.add_argument("--quantidade", type=int, default=150)
        parser.add_argument("--dias", type=int, default=60)
        parser.add_argument("--limpar", action="store_true")
        parser.add_argument("--semente", type=int, default=42)

    @transaction.atomic
    def handle(self, quantidade, dias, limpar, semente, **_):
        if limpar:
            sol = Solicitacao.objects.filter(cidadao__usuario__email__endswith=DOMINIO)
            n = sol.count()
            sol.delete()  # o histórico vai junto (CASCADE)
            Cidadao.objects.filter(usuario__email__endswith=DOMINIO).delete()
            Servidor.objects.filter(usuario__email__endswith=DOMINIO).delete()
            User.objects.filter(email__endswith=DOMINIO).delete()
            self.stdout.write(self.style.SUCCESS(f"Removidos os dados de demonstração ({n} solicitações)."))
            return

        rng = random.Random(semente)
        agora = timezone.now()

        # Cadastros de apoio (reaproveita os que já existem)
        secretarias, categorias = {}, []
        for sigla, (nome, cats) in SECRETARIAS.items():
            sec, _ = Secretaria.objects.get_or_create(sigla=sigla, defaults={"nome": nome})
            secretarias[sigla] = sec
            for nome_cat, prazo in cats:
                cat = CategoriaServico.objects.filter(secretaria=sec, nome__iexact=nome_cat).first()
                if cat is None:
                    cat = CategoriaServico.objects.create(secretaria=sec, nome=nome_cat, prazo_dias=prazo)
                categorias.append(cat)
        bairros = []
        for nome, zona in BAIRROS:
            b = Bairro.objects.filter(nome__iexact=nome).first() or Bairro.objects.create(nome=nome, zona=zona)
            bairros.append(b)
            for sec in secretarias.values():
                AreaAtuacao.objects.get_or_create(secretaria=sec, bairro=b, defaults={"data_inicio": (agora - timedelta(days=365)).date()})

        # Um servidor de demonstração por secretaria
        servidores = {}
        for sigla, sec in secretarias.items():
            login = f"demo.{sigla.lower()}"
            u, criado = User.objects.get_or_create(
                username=login,
                defaults={"first_name": rng.choice(NOMES), "last_name": rng.choice(SOBRENOMES), "email": f"{login}{DOMINIO}"},
            )
            if criado:
                u.set_password(SENHA)
                u.save()
            srv, _ = Servidor.objects.get_or_create(usuario=u, defaults={"matricula": f"DEMO-{sigla}", "secretaria": sec})
            servidores[sigla] = srv

        # Cidadãos de demonstração
        cidadaos = []
        for i in range(20):
            cpf = gerar_cpf(rng)
            if Cidadao.objects.filter(cpf=cpf).exists():
                continue
            nome, sobrenome = rng.choice(NOMES), rng.choice(SOBRENOMES)
            u = User.objects.create_user(username=cpf, password=SENHA, first_name=nome, last_name=sobrenome,
                                         email=f"cidadao{i}{DOMINIO}")
            cidadaos.append(Cidadao.objects.create(usuario=u, cpf=cpf, nome_completo=f"{nome} {sobrenome}",
                                                   bairro=rng.choice(bairros), termo_aceito_em=agora,
                                                   email_confirmado_em=agora))

        # Solicitações com histórico coerente e datas espalhadas no período
        pesos_cat = [5, 2, 2, 5, 3, 2, 2, 1, 1, 2][: len(categorias)] + [1] * max(0, len(categorias) - 10)
        criadas = 0
        for _ in range(quantidade):
            cat = rng.choices(categorias, weights=pesos_cat)[0]
            srv = servidores[cat.secretaria.sigla]
            cid = rng.choice(cidadaos) if cidadaos else Cidadao.objects.order_by("?").first()
            # Mais solicitações nos dias recentes (crescimento do uso)
            idade = min(dias - 0.01, rng.expovariate(1 / (dias / 2.5)))
            aberta_em = agora - timedelta(days=idade, hours=rng.randint(0, 10))
            s = Solicitacao.objects.create(
                cidadao=cid, categoria=cat, bairro=rng.choice(bairros),
                descricao=DESCRICOES.get(cat.nome, "Problema relatado pelo cidadão."),
                endereco_referencia=f"Rua {rng.choice(SOBRENOMES)}, {rng.randint(10, 2000)}",
                prioridade=rng.choices([1, 2, 3], weights=[2, 5, 2])[0],
            )
            eventos = [(aberta_em, "ABE", "ABE", cid.usuario, "Solicitação aberta pelo cidadão.")]
            t = aberta_em
            # Quanto mais antiga, mais provável que já tenha andado no fluxo
            sorteio = rng.random()
            prazo_h = cat.prazo_dias * 24
            if sorteio < 0.05:
                t += timedelta(hours=rng.uniform(1, 24))
                eventos.append((t, "ABE", "CAN", cid.usuario, "Cancelada pelo cidadão."))
            elif idade > 2 and sorteio < 0.95:
                t += timedelta(hours=rng.uniform(2, 48))
                eventos.append((t, "ABE", "ANA", srv.usuario, "Vistoria agendada."))
                if rng.random() < 0.08:
                    t += timedelta(hours=rng.uniform(4, 48))
                    eventos.append((t, "ANA", "IND", srv.usuario, "Fora da competência do município."))
                elif rng.random() < 0.85:
                    t += timedelta(hours=rng.uniform(4, 72))
                    eventos.append((t, "ANA", "EXE", srv.usuario, "Equipe designada."))
                    fim = aberta_em + timedelta(hours=rng.uniform(0.3, 1.4) * prazo_h)
                    if fim < agora and rng.random() < 0.85:
                        eventos.append((max(fim, t + timedelta(hours=1)), "EXE", "CON", srv.usuario, "Serviço concluído."))
            eventos = [e for e in eventos if e[0] <= agora]

            final = eventos[-1][2]
            Solicitacao.objects.filter(pk=s.pk).update(
                criado_em=aberta_em,
                status=final,
                concluida_em=eventos[-1][0] if final == "CON" else None,
                responsavel=srv if len(eventos) > 1 and eventos[1][2] != "CAN" else None,
            )
            for quando, de, para, usuario, obs in eventos:
                h = HistoricoSolicitacao.objects.create(solicitacao=s, usuario=usuario, status_anterior=de,
                                                        status_novo=para, observacao=obs)
                HistoricoSolicitacao.objects.filter(pk=h.pk).update(registrado_em=quando)
            criadas += 1

        self.stdout.write(self.style.SUCCESS(
            f"Criadas {criadas} solicitações de demonstração, {len(cidadaos)} cidadãos e "
            f"{len(servidores)} servidores (logins demo.<sigla>, senha {SENHA})."
        ))
