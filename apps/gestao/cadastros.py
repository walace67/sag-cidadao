"""
SAG-Cidadão — registro dos cadastros de apoio
App: gestao/cadastros.py

Em vez de escrever 4 x 4 views quase iguais (listar, criar, editar,
excluir para secretarias, bairros, categorias e áreas), descrevemos cada
cadastro numa estrutura de dados e usamos UMA view genérica para todos.
É o princípio DRY (Don't Repeat Yourself) aplicado com uma tabela de
configuração - a mesma ideia que o admin do Django usa internamente.
"""
from dataclasses import dataclass, field

from apps.atendimento.models import AreaAtuacao, Bairro, CategoriaServico, Secretaria

from .forms import AreaAtuacaoForm, BairroForm, CategoriaForm, SecretariaForm


@dataclass
class Cadastro:
    model: type
    form: type
    titulo: str           # "Secretarias"
    singular: str         # "secretaria"
    colunas: list         # [("Rótulo", "caminho.do.atributo"), ...]
    busca: list = field(default_factory=list)       # campos para o ?q=
    relacionados: list = field(default_factory=list)  # select_related
    ordem: list = field(default_factory=list)
    dica_exclusao: str = ""


CADASTROS = {
    "secretarias": Cadastro(
        model=Secretaria, form=SecretariaForm, titulo="Secretarias", singular="secretaria",
        colunas=[("Sigla", "sigla"), ("Nome", "nome"), ("E-mail", "email"), ("Ativa", "ativa")],
        busca=["sigla__icontains", "nome__icontains"], ordem=["sigla"],
        dica_exclusao="Secretarias com servidores ou categorias não podem ser excluídas. Desmarque \"Ativa\".",
    ),
    "bairros": Cadastro(
        model=Bairro, form=BairroForm, titulo="Bairros", singular="bairro",
        colunas=[("Nome", "nome"), ("Zona", "zona")],
        busca=["nome__icontains"], ordem=["nome"],
        dica_exclusao="Bairros com moradores ou solicitações não podem ser excluídos.",
    ),
    "categorias": Cadastro(
        model=CategoriaServico, form=CategoriaForm, titulo="Categorias de serviço", singular="categoria",
        colunas=[("Serviço", "nome"), ("Secretaria", "secretaria.sigla"), ("Prazo (dias)", "prazo_dias"), ("Ativa", "ativa")],
        busca=["nome__icontains", "secretaria__sigla__icontains"],
        relacionados=["secretaria"], ordem=["secretaria__sigla", "nome"],
        dica_exclusao="Categorias com solicitações não podem ser excluídas. Desmarque \"Ativa\" (exclusão lógica).",
    ),
    "areas": Cadastro(
        model=AreaAtuacao, form=AreaAtuacaoForm, titulo="Áreas de atuação", singular="área de atuação",
        colunas=[("Secretaria", "secretaria.sigla"), ("Bairro", "bairro.nome"), ("Zona", "bairro.zona"), ("Atende desde", "data_inicio")],
        busca=["secretaria__sigla__icontains", "bairro__nome__icontains"],
        relacionados=["secretaria", "bairro"], ordem=["secretaria__sigla", "bairro__nome"],
    ),
}
