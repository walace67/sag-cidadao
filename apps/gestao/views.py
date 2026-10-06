"""
SAG-Cidadão — views da área de gestão (perfil Gestor)
App: gestao/views.py

Substitui o admin do Django para o uso do dia a dia:
    /gestao/                         dashboard com indicadores
    /gestao/cadastros/<tipo>/        secretarias, bairros, categorias, áreas
    /gestao/servidores/              servidores (cria login + perfil)
    /gestao/cidadaos/                cidadãos (consulta e bloqueio)
"""
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Exists, OuterRef, ProtectedError, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.atendimento.models import Cidadao, Secretaria, Servidor, Solicitacao
from apps.auditoria.registro import A, diferencas, registrar
from apps.doisfatores import servicos as dois_fatores
from apps.doisfatores.models import DispositivoTOTP

from . import services
from .cadastros import CADASTROS
from .forms import ServidorForm
from .permissoes import GRUPO_GESTOR, gestor_required

PERIODOS = [(7, "7 dias"), (30, "30 dias"), (90, "90 dias"), (0, "Tudo")]


# ---------------------------------------------------------------------------
# Auxiliares de apresentação
# ---------------------------------------------------------------------------
def formatar_duracao(td):
    if td is None:
        return "—"
    minutos = int(td.total_seconds() // 60)
    dias, resto = divmod(minutos, 24 * 60)
    horas, mins = divmod(resto, 60)
    if dias:
        return f"{dias} d {horas} h"
    if horas:
        return f"{horas} h {mins} min"
    return f"{mins} min"


def barras(itens):
    """Acrescenta a largura relativa (%) de cada barra horizontal."""
    maior = max((i["valor"] for i in itens), default=0) or 1
    for i in itens:
        i["pct"] = round(100 * i["valor"] / maior, 1)
    return itens


def grafico_linha(serie, largura=900, altura=230, margem_esq=36, margem_inf=26, margem_sup=12, margem_dir=28):
    """
    Converte a série diária em coordenadas de SVG, calculadas no servidor.
    Devolve o caminho da linha, a área preenchida, os pontos (com dica de
    hover) e as marcas dos eixos.
    """
    n = len(serie)
    maior = max((p["valor"] for p in serie), default=0)
    passo_y = max(1, -(-maior // 4))  # 4 divisões, arredondado para cima
    topo = passo_y * 4
    area_l, area_a = largura - margem_esq - margem_dir, altura - margem_inf - margem_sup

    def x(i):
        return margem_esq + (area_l * i / (n - 1) if n > 1 else area_l / 2)

    def y(v):
        return margem_sup + area_a - (area_a * v / topo if topo else 0)

    pontos = [
        {"x": round(x(i), 1), "y": round(y(p["valor"]), 1), "valor": p["valor"], "dia": p["dia"]}
        for i, p in enumerate(serie)
    ]
    caminho = " ".join(f"{'M' if i == 0 else 'L'}{p['x']} {p['y']}" for i, p in enumerate(pontos))
    base = round(y(0), 1)
    area = f"{caminho} L{pontos[-1]['x']} {base} L{pontos[0]['x']} {base} Z" if pontos else ""
    marcas_y = [{"y": round(y(v), 1), "valor": v} for v in range(0, topo + 1, passo_y)]
    cada = max(1, n // 6)
    marcas_x = [p for i, p in enumerate(pontos) if i % cada == 0 or i == n - 1]
    return {
        "largura": largura, "altura": altura, "caminho": caminho, "area": area,
        "pontos": pontos, "marcas_y": marcas_y, "marcas_x": marcas_x,
        "x0": margem_esq, "x1": largura - margem_dir,
    }


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@gestor_required
def dashboard(request):
    try:
        dias = int(request.GET.get("dias", 30))
    except ValueError:
        dias = 30
    if dias not in dict(PERIODOS):
        dias = 30

    secretaria = None
    if request.GET.get("secretaria"):
        secretaria = Secretaria.objects.filter(pk=request.GET["secretaria"]).first()

    dados = services.indicadores(dias=dias, secretaria=secretaria)
    k = dados["k"]
    k["tempo_medio_txt"] = formatar_duracao(k["tempo_medio"])
    for linha in dados["por_secretaria"]:
        linha["tempo_medio_txt"] = formatar_duracao(linha["tempo_medio"])

    return render(request, "gestao/dashboard.html", {
        **dados,
        "por_status": barras(dados["por_status"]),
        "por_zona": barras(dados["por_zona"]),
        "top_categorias": barras(dados["top_categorias"]),
        "linha": grafico_linha(dados["serie_diaria"]),
        "periodos": PERIODOS,
        "dias": dias,
        "secretaria_sel": secretaria,
        "secretarias": services.secretarias_ativas(),
        "cadastros": CADASTROS,
    })


# ---------------------------------------------------------------------------
# Cadastros de apoio (uma view genérica para todos)
# ---------------------------------------------------------------------------
def _cadastro(tipo):
    try:
        return CADASTROS[tipo]
    except KeyError:
        raise Http404("Cadastro inexistente.")


@gestor_required
def cadastro_lista(request, tipo):
    cad = _cadastro(tipo)
    qs = cad.model.objects.select_related(*cad.relacionados).order_by(*cad.ordem)
    q = request.GET.get("q", "").strip()
    if q and cad.busca:
        filtro = Q()
        for campo in cad.busca:
            filtro |= Q(**{campo: q})
        qs = qs.filter(filtro)
    pagina = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(request, "gestao/cadastro_lista.html", {
        "cad": cad, "tipo": tipo, "pagina": pagina, "q": q, "cadastros": CADASTROS,
    })


@gestor_required
def cadastro_form(request, tipo, pk=None):
    cad = _cadastro(tipo)
    objeto = get_object_or_404(cad.model, pk=pk) if pk else None
    form = cad.form(request.POST or None, instance=objeto)
    if request.method == "POST" and form.is_valid():
        mudou = diferencas(form)
        salvo = form.save()
        registrar(A.ALTERAR if objeto else A.CRIAR, request=request, objeto=salvo, detalhes=mudou)
        messages.success(request, f"{cad.singular.capitalize()} salva com sucesso." if cad.singular.endswith("a") else f"{cad.singular.capitalize()} salvo com sucesso.")
        return redirect("gestao:cadastro_lista", tipo=tipo)
    return render(request, "gestao/cadastro_form.html", {
        "cad": cad, "tipo": tipo, "form": form, "objeto": objeto, "cadastros": CADASTROS,
    })


@gestor_required
@require_POST
def cadastro_excluir(request, tipo, pk):
    cad = _cadastro(tipo)
    objeto = get_object_or_404(cad.model, pk=pk)
    try:
        objeto.delete()
        objeto.pk = pk  # o delete() zera a chave; o registro precisa dela
        registrar(A.EXCLUIR, request=request, objeto=objeto)
    except ProtectedError:
        # on_delete=PROTECT em ação: a integridade referencial barrou
        messages.error(request, f"Não foi possível excluir \"{objeto}\": há registros vinculados. {cad.dica_exclusao}")
    else:
        messages.success(request, f"\"{objeto}\" excluído.")
    return redirect("gestao:cadastro_lista", tipo=tipo)


# ---------------------------------------------------------------------------
# Mapa das solicitações
# ---------------------------------------------------------------------------
@gestor_required
def mapa(request):
    from django.conf import settings

    dias = _dias(request)
    secretaria = _secretaria(request)
    return render(request, "gestao/mapa.html", {
        "periodos": PERIODOS, "dias": dias, "secretarias": services.secretarias_ativas(),
        "secretaria_sel": secretaria, "cadastros": CADASTROS,
        "centro": settings.MAPA_CENTRO,
        "status": [(s.value, s.label) for s in Solicitacao.Status],
    })


@gestor_required
def mapa_dados(request):
    """
    JSON com os pontos do mapa. Minimização (LGPD): vai só o necessário
    para o mapa; nada do cidadão (nem nome, nem endereço digitado).
    """
    from django.http import JsonResponse
    from django.urls import reverse
    from django.utils import timezone

    qs = services._base(_dias(request), _secretaria(request))
    total = qs.count()
    pontos = [
        {
            "lat": float(s.latitude), "lng": float(s.longitude), "status": s.status,
            "status_rotulo": s.get_status_display(), "categoria": s.categoria.nome, "bairro": s.bairro.nome,
            "aberta_em": timezone.localtime(s.criado_em).strftime("%d/%m/%Y"),
            "protocolo": str(s.protocolo)[:8].upper(), "url": reverse("atendimento:detalhe", args=[s.pk]),
        }
        for s in qs.filter(latitude__isnull=False).select_related("categoria", "bairro").order_by("-criado_em")[:2000]
    ]
    return JsonResponse({"total": total, "pontos": pontos})


def _dias(request):
    try:
        dias = int(request.GET.get("dias", 30))
    except ValueError:
        dias = 30
    return dias if dias in dict(PERIODOS) else 30


def _secretaria(request):
    sid = request.GET.get("secretaria")
    return Secretaria.objects.filter(pk=sid, ativa=True).first() if sid and sid.isdigit() else None


# ---------------------------------------------------------------------------
# Servidores
# ---------------------------------------------------------------------------
@gestor_required
def servidores(request):
    qs = Servidor.objects.select_related("usuario", "secretaria").annotate(
        atendidas=Count("solicitacoes_atribuidas"),
        gestor=Count("usuario__groups", filter=Q(usuario__groups__name=GRUPO_GESTOR)),
        dois_fatores=Exists(DispositivoTOTP.objects.filter(usuario=OuterRef("usuario"), confirmado_em__isnull=False)),
    ).order_by("secretaria__sigla", "usuario__first_name")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(usuario__first_name__icontains=q) | Q(usuario__last_name__icontains=q)
            | Q(matricula__icontains=q) | Q(secretaria__sigla__icontains=q)
        )
    pagina = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(request, "gestao/servidores.html", {"pagina": pagina, "q": q, "cadastros": CADASTROS})


@gestor_required
def servidor_form(request, pk=None):
    servidor = get_object_or_404(Servidor.objects.select_related("usuario"), pk=pk) if pk else None
    inicial = {}
    if servidor:
        u = servidor.usuario
        inicial = {
            "first_name": u.first_name, "last_name": u.last_name, "email": u.email,
            "username": u.username, "matricula": servidor.matricula,
            "secretaria": servidor.secretaria_id,
            "gestor": u.groups.filter(name=GRUPO_GESTOR).exists(),
        }
    form = ServidorForm(request.POST or None, initial=inicial, servidor=servidor)
    if request.method == "POST" and form.is_valid():
        mudou = diferencas(form, inicial)
        salvo = services.salvar_servidor(form.cleaned_data, servidor)
        registrar(A.ALTERAR if servidor else A.CRIAR, request=request, objeto=salvo.usuario, detalhes=mudou)
        if "gestor" in form.changed_data:
            registrar(A.PAPEL, request=request, objeto=salvo.usuario,
                      detalhes={"Gestor": ["Sim" if inicial.get("gestor") else "Não",
                                           "Sim" if form.cleaned_data["gestor"] else "Não"]})
        messages.success(request, "Servidor salvo com sucesso.")
        return redirect("gestao:servidores")
    return render(request, "gestao/servidor_form.html", {"form": form, "servidor": servidor, "cadastros": CADASTROS})


@gestor_required
@require_POST
def servidor_alternar(request, pk):
    servidor = get_object_or_404(Servidor.objects.select_related("usuario"), pk=pk)
    if servidor.usuario_id == request.user.pk:
        messages.error(request, "Você não pode desativar o próprio acesso.")
    else:
        ativo = services.alternar_ativo(servidor.usuario)
        registrar(A.ATIVAR if ativo else A.DESATIVAR, request=request, objeto=servidor.usuario)
        messages.success(request, f"Acesso de {servidor.usuario.get_full_name()} {'reativado' if ativo else 'desativado'}.")
    return redirect("gestao:servidores")


@gestor_required
@require_POST
def servidor_redefinir_2fa(request, pk):
    """Celular perdido e sem códigos: o gestor apaga o dispositivo; no
    próximo login o servidor configura de novo. Fica na auditoria."""
    servidor = get_object_or_404(Servidor.objects.select_related("usuario"), pk=pk)
    if servidor.usuario_id == request.user.pk:
        messages.error(request, "Outro gestor precisa redefinir a sua verificação.")
    else:
        dois_fatores.remover(servidor.usuario)
        registrar(A.DOIS_FATORES, request=request, objeto=servidor.usuario, detalhes={"evento": "redefinida pelo gestor"})
        messages.success(request, f"Verificação em duas etapas de {servidor.usuario.get_full_name()} redefinida. "
                                  "No próximo acesso, ele vai configurar o aplicativo de novo.")
    return redirect("gestao:servidores")


# ---------------------------------------------------------------------------
# Cidadãos (consulta e bloqueio; dados pessoais mascarados)
# ---------------------------------------------------------------------------
@gestor_required
def cidadaos(request):
    qs = Cidadao.objects.select_related("usuario", "bairro").annotate(
        total=Count("solicitacoes")
    ).order_by("nome_completo")
    q = request.GET.get("q", "").strip()
    if q:
        digitos = "".join(c for c in q if c.isdigit())
        filtro = Q(nome_completo__icontains=q) | Q(bairro__nome__icontains=q)
        if len(digitos) == 11:
            filtro |= Q(cpf=digitos)  # busca por CPF só com o número completo
        qs = qs.filter(filtro)
    pagina = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(request, "gestao/cidadaos.html", {"pagina": pagina, "q": q, "cadastros": CADASTROS})


@gestor_required
@require_POST
def cidadao_alternar(request, pk):
    cidadao = get_object_or_404(Cidadao.objects.select_related("usuario"), pk=pk)
    ativo = services.alternar_ativo(cidadao.usuario)
    registrar(A.ATIVAR if ativo else A.DESATIVAR, request=request, objeto=cidadao.usuario)
    messages.success(request, f"Acesso de {cidadao.nome_completo} {'reativado' if ativo else 'bloqueado'}.")
    return redirect("gestao:cidadaos")
