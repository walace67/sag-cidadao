"""
SAG-Cidadão — serializers da API REST
App: atendimento/serializers.py

Um serializer faz para a API o que o Form faz para as telas HTML:
    - SERIALIZA: objeto Python -> JSON (resposta)
    - DESSERIALIZA e VALIDA: JSON recebido -> dados limpos (requisição)

Serializers separados para leitura e escrita deixam claro o que o
cliente pode ver e o que ele pode enviar (proteção contra mass assignment).
"""
from rest_framework import serializers

from . import services
from .models import Bairro, CategoriaServico, HistoricoSolicitacao, Solicitacao


class HistoricoSerializer(serializers.ModelSerializer):
    status_anterior = serializers.CharField(source="get_status_anterior_display")
    status_novo = serializers.CharField(source="get_status_novo_display")
    usuario = serializers.SerializerMethodField()

    class Meta:
        model = HistoricoSolicitacao
        fields = ["registrado_em", "status_anterior", "status_novo", "usuario", "observacao"]

    def get_usuario(self, h):
        if h.usuario is None:
            return None
        return h.usuario.get_full_name() or h.usuario.username


class SolicitacaoSerializer(serializers.ModelSerializer):
    """Leitura (GET). Mostra nomes legíveis em vez de só ids."""

    status_codigo = serializers.CharField(source="status")
    status = serializers.CharField(source="get_status_display")
    prioridade = serializers.CharField(source="get_prioridade_display")
    categoria = serializers.CharField(source="categoria.nome")
    secretaria = serializers.CharField(source="categoria.secretaria.sigla")
    bairro = serializers.CharField(source="bairro.nome")
    zona = serializers.CharField(source="bairro.get_zona_display")
    cidadao = serializers.CharField(source="cidadao.nome_completo")
    responsavel = serializers.SerializerMethodField()

    class Meta:
        model = Solicitacao
        fields = [
            "id", "protocolo", "status", "status_codigo", "prioridade",
            "categoria", "secretaria", "bairro", "zona", "endereco_referencia",
            "descricao", "cidadao", "responsavel", "criado_em", "concluida_em",
        ]

    def get_responsavel(self, s):
        if s.responsavel is None:
            return None
        return s.responsavel.usuario.get_full_name() or s.responsavel.matricula


class SolicitacaoDetalheSerializer(SolicitacaoSerializer):
    """Detalhe (GET /{id}/): inclui o histórico."""

    historico = HistoricoSerializer(many=True, read_only=True)

    class Meta(SolicitacaoSerializer.Meta):
        fields = SolicitacaoSerializer.Meta.fields + ["historico"]


class NovaSolicitacaoSerializer(serializers.Serializer):
    """
    Escrita (POST). Só estes 4 campos são aceitos; status, prioridade,
    responsável e cidadão NUNCA vêm do cliente.
    """

    categoria = serializers.PrimaryKeyRelatedField(
        queryset=CategoriaServico.objects.filter(ativa=True)
    )
    bairro = serializers.PrimaryKeyRelatedField(queryset=Bairro.objects.all())
    endereco_referencia = serializers.CharField(max_length=255)
    descricao = serializers.CharField()

    def validate_descricao(self, valor):
        """Mesma regra do formulário HTML: validação em um lugar só seria o ideal."""
        valor = valor.strip()
        if len(valor) < 15:
            raise serializers.ValidationError("Descreva o problema com pelo menos 15 caracteres.")
        return valor


class AlterarStatusSerializer(serializers.Serializer):
    novo_status = serializers.ChoiceField(choices=Solicitacao.Status.choices)
    observacao = serializers.CharField(required=False, allow_blank=True, max_length=500)


class CancelarSerializer(serializers.Serializer):
    motivo = serializers.CharField(required=False, allow_blank=True, max_length=200)


class ConsultaPublicaSerializer(serializers.ModelSerializer):
    """Consulta pública: sem nome, CPF ou descrição (LGPD, minimização)."""

    status = serializers.CharField(source="get_status_display")
    categoria = serializers.CharField(source="categoria.nome")
    bairro = serializers.CharField(source="bairro.nome")
    andamento = serializers.SerializerMethodField()

    class Meta:
        model = Solicitacao
        fields = ["protocolo", "status", "categoria", "bairro", "criado_em", "concluida_em", "andamento"]

    def get_andamento(self, s):
        # DateTimeField converte para o fuso do projeto (America/Porto_Velho),
        # igual aos demais campos de data da resposta.
        data = serializers.DateTimeField()
        return [
            {
                "data": data.to_representation(h.registrado_em),
                "situacao": h.get_status_novo_display(),
                "observacao": h.observacao,
            }
            for h in services.historico(s)
        ]
