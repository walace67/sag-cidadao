"""
SAG-Cidadão — Sistema de Atendimento e Gestão ao Cidadão
App: atendimento/models.py

Requer Django >= 5.1 (usa CheckConstraint(condition=...)).
Banco recomendado: PostgreSQL.
"""
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q


# ---------------------------------------------------------------------------
# Validadores de domínio (regra de negócio próxima do dado)
# ---------------------------------------------------------------------------
def validar_cpf(valor: str) -> None:
    """Valida os dígitos verificadores do CPF (apenas números, 11 dígitos)."""
    cpf = "".join(filter(str.isdigit, valor))
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        raise ValidationError("CPF inválido.")
    for i in (9, 10):
        soma = sum(int(cpf[n]) * ((i + 1) - n) for n in range(i))
        digito = (soma * 10 % 11) % 10
        if digito != int(cpf[i]):
            raise ValidationError("CPF inválido.")


# ---------------------------------------------------------------------------
# Classe base abstrata: não gera tabela; só reaproveita colunas (DRY)
# ---------------------------------------------------------------------------
class ModeloAuditavel(models.Model):
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# ---------------------------------------------------------------------------
# 1. Secretaria — entidade forte (não depende de nenhuma outra)
# ---------------------------------------------------------------------------
class Secretaria(ModeloAuditavel):
    # PK substituta (surrogate key) automática: id BIGINT AUTO_INCREMENT
    sigla = models.CharField(max_length=15, unique=True)  # chave candidata
    nome = models.CharField(max_length=150, unique=True)
    email = models.EmailField(blank=True)
    ativa = models.BooleanField(default=True)

    class Meta:
        db_table = "secretaria"
        ordering = ["sigla"]
        verbose_name = "Secretaria"
        verbose_name_plural = "Secretarias"

    def __str__(self):
        return f"{self.sigla} - {self.nome}"


# ---------------------------------------------------------------------------
# 2. Bairro — tabela de domínio (evita texto livre repetido = normalização)
# ---------------------------------------------------------------------------
class Bairro(models.Model):
    class Zona(models.TextChoices):
        CENTRO = "CEN", "Centro"
        NORTE = "NOR", "Zona Norte"
        SUL = "SUL", "Zona Sul"
        LESTE = "LES", "Zona Leste"
        DISTRITO = "DIS", "Distrito"

    nome = models.CharField(max_length=100)
    zona = models.CharField(max_length=3, choices=Zona.choices)

    # N:N com Secretaria usando tabela associativa explícita (through)
    secretarias = models.ManyToManyField(
        Secretaria,
        through="AreaAtuacao",
        related_name="bairros_atendidos",
    )

    class Meta:
        db_table = "bairro"
        ordering = ["nome"]
        constraints = [
            # Não pode haver dois bairros com o mesmo nome na mesma zona
            models.UniqueConstraint(fields=["nome", "zona"], name="uq_bairro_nome_zona"),
        ]

    def __str__(self):
        return f"{self.nome} ({self.get_zona_display()})"


# ---------------------------------------------------------------------------
# 3. AreaAtuacao — entidade associativa (resolve o N:N Secretaria x Bairro)
# ---------------------------------------------------------------------------
class AreaAtuacao(models.Model):
    secretaria = models.ForeignKey(Secretaria, on_delete=models.CASCADE)
    bairro = models.ForeignKey(Bairro, on_delete=models.CASCADE)
    # Atributo do RELACIONAMENTO (por isso o through é necessário)
    data_inicio = models.DateField()

    class Meta:
        db_table = "area_atuacao"
        constraints = [
            # Equivale a uma chave composta (secretaria_id, bairro_id)
            models.UniqueConstraint(
                fields=["secretaria", "bairro"], name="uq_area_secretaria_bairro"
            ),
        ]


# ---------------------------------------------------------------------------
# 4. Cidadao — especialização do usuário (relacionamento 1:1)
# ---------------------------------------------------------------------------
class Cidadao(ModeloAuditavel):
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,  # sem usuário, o perfil não faz sentido
        related_name="cidadao",
    )
    cpf = models.CharField(
        max_length=11,
        unique=True,  # chave candidata / natural (mas NÃO usada como PK)
        validators=[RegexValidator(r"^\d{11}$", "Use apenas 11 dígitos."), validar_cpf],
    )
    nome_completo = models.CharField(max_length=150)
    telefone = models.CharField(max_length=15, blank=True)
    bairro = models.ForeignKey(
        Bairro,
        on_delete=models.PROTECT,  # impede apagar bairro com cidadãos vinculados
        related_name="moradores",
    )
    # LGPD: quando o cidadão declarou ciência do aviso de privacidade.
    # Nulo para quem foi cadastrado pelo gestor (e não por autocadastro).
    termo_aceito_em = models.DateTimeField(null=True, blank=True)
    # Quando o cidadão confirmou o e-mail pelo link de ativação.
    email_confirmado_em = models.DateTimeField(null=True, blank=True)

    @property
    def pendente(self):
        """
        Autocadastro ainda não confirmado: aceitou o termo, não confirmou o
        e-mail, está inativo e nunca entrou. Cidadãos criados pela prefeitura
        (sem termo) ou bloqueados pelo gestor depois de usar o sistema
        nunca são considerados pendentes.
        """
        u = self.usuario
        return (
            self.termo_aceito_em is not None and self.email_confirmado_em is None
            and not u.is_active and u.last_login is None
        )

    class Meta:
        db_table = "cidadao"
        ordering = ["nome_completo"]

    def __str__(self):
        return self.nome_completo


# ---------------------------------------------------------------------------
# 5. Servidor — funcionário da prefeitura (1:1 com User, N:1 com Secretaria)
# ---------------------------------------------------------------------------
class Servidor(ModeloAuditavel):
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="servidor"
    )
    matricula = models.CharField(max_length=20, unique=True)
    secretaria = models.ForeignKey(
        Secretaria, on_delete=models.PROTECT, related_name="servidores"
    )

    class Meta:
        db_table = "servidor"

    def __str__(self):
        return f"{self.matricula} - {self.usuario.get_full_name()}"


# ---------------------------------------------------------------------------
# 6. CategoriaServico — catálogo de serviços (N:1 com Secretaria)
# ---------------------------------------------------------------------------
class CategoriaServico(models.Model):
    secretaria = models.ForeignKey(
        Secretaria, on_delete=models.PROTECT, related_name="categorias"
    )
    nome = models.CharField(max_length=100)  # ex.: "Tapa-buraco", "Iluminação"
    prazo_dias = models.PositiveSmallIntegerField(default=15)  # SLA
    ativa = models.BooleanField(default=True)

    class Meta:
        db_table = "categoria_servico"
        ordering = ["nome"]
        constraints = [
            models.UniqueConstraint(
                fields=["secretaria", "nome"], name="uq_categoria_por_secretaria"
            ),
            models.CheckConstraint(
                condition=Q(prazo_dias__gte=1), name="ck_categoria_prazo_positivo"
            ),
        ]

    def __str__(self):
        return self.nome


# ---------------------------------------------------------------------------
# 7. Solicitacao — entidade central (tabela "fato" do sistema)
# ---------------------------------------------------------------------------
class Solicitacao(ModeloAuditavel):
    class Status(models.TextChoices):
        ABERTA = "ABE", "Aberta"
        EM_ANALISE = "ANA", "Em análise"
        EM_EXECUCAO = "EXE", "Em execução"
        CONCLUIDA = "CON", "Concluída"
        INDEFERIDA = "IND", "Indeferida"
        CANCELADA = "CAN", "Cancelada pelo cidadão"

    class Prioridade(models.IntegerChoices):
        BAIXA = 1, "Baixa"
        MEDIA = 2, "Média"
        ALTA = 3, "Alta"

    # Protocolo público não sequencial (não expõe o volume de registros)
    protocolo = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    cidadao = models.ForeignKey(
        Cidadao, on_delete=models.PROTECT, related_name="solicitacoes"
    )
    categoria = models.ForeignKey(
        CategoriaServico, on_delete=models.PROTECT, related_name="solicitacoes"
    )
    bairro = models.ForeignKey(
        Bairro, on_delete=models.PROTECT, related_name="solicitacoes"
    )
    responsavel = models.ForeignKey(
        Servidor,
        on_delete=models.SET_NULL,  # se o servidor sair, a solicitação continua
        null=True,
        blank=True,
        related_name="solicitacoes_atribuidas",
    )

    descricao = models.TextField()
    endereco_referencia = models.CharField(max_length=255)
    status = models.CharField(max_length=3, choices=Status.choices, default=Status.ABERTA)
    prioridade = models.PositiveSmallIntegerField(
        choices=Prioridade.choices, default=Prioridade.MEDIA
    )
    concluida_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "solicitacao"
        ordering = ["-criado_em"]
        indexes = [
            # Índice composto: acelera o filtro mais comum do painel
            models.Index(fields=["status", "prioridade"], name="ix_solic_status_prior"),
            models.Index(fields=["bairro", "status"], name="ix_solic_bairro_status"),
        ]
        constraints = [
            # Integridade: só pode ter data de conclusão se estiver concluída
            models.CheckConstraint(
                condition=(
                    Q(status="CON", concluida_em__isnull=False)
                    | (~Q(status="CON") & Q(concluida_em__isnull=True))
                ),
                name="ck_solic_conclusao_coerente",
            ),
        ]

    def __str__(self):
        return f"{str(self.protocolo)[:8].upper()} - {self.categoria}"


# ---------------------------------------------------------------------------
# 8. HistoricoSolicitacao — trilha de auditoria (entidade fraca, 1:N)
# ---------------------------------------------------------------------------
class HistoricoSolicitacao(models.Model):
    solicitacao = models.ForeignKey(
        Solicitacao,
        on_delete=models.CASCADE,  # histórico não existe sem a solicitação
        related_name="historico",
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True
    )
    status_anterior = models.CharField(max_length=3, choices=Solicitacao.Status.choices)
    status_novo = models.CharField(max_length=3, choices=Solicitacao.Status.choices)
    observacao = models.TextField(blank=True)
    registrado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "historico_solicitacao"
        ordering = ["registrado_em"]

    def __str__(self):
        return f"{self.solicitacao} : {self.status_anterior} -> {self.status_novo}"
