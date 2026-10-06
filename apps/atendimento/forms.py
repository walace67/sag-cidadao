"""
SAG-Cidadão — formulários
App: atendimento/forms.py

Um Form do Django faz três coisas:
    1. Desenha os campos HTML no template.
    2. VALIDA o que o usuário enviou (nunca confie no navegador).
    3. Entrega os dados limpos em form.cleaned_data.

ModelForm gera os campos a partir do Model e já aplica as regras
declaradas lá (max_length, blank, validators, constraints).
"""
from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User

from .models import Bairro, CategoriaServico, Cidadao, Solicitacao, validar_cpf
from .services import proximos_status


def so_digitos(texto):
    return "".join(c for c in (texto or "") if c.isdigit())


class LoginForm(AuthenticationForm):
    """
    Login aceita usuário OU CPF, com ou sem pontuação.
    "529.982.247-25" vira "52998224725" antes de procurar o usuário.
    """

    def clean_username(self):
        valor = self.cleaned_data["username"].strip()
        digitos = so_digitos(valor)
        if len(digitos) == 11 and len(valor) <= 14 and not any(c.isalpha() for c in valor):
            return digitos
        return valor


class MeusDadosForm(forms.ModelForm):
    """Correção de dados pelo titular (LGPD, art. 18, III)."""

    class Meta:
        model = Cidadao
        fields = ["telefone", "bairro", "receber_avisos"]
        labels = {
            "telefone": "Telefone", "bairro": "Bairro onde mora",
            "receber_avisos": "Quero receber por e-mail os avisos de andamento das minhas solicitações",
        }

    def clean_telefone(self):
        return so_digitos(self.cleaned_data.get("telefone"))


class CadastroCidadaoForm(forms.Form):
    """Autocadastro (RF01). Um Form comum, e não ModelForm, porque grava em DUAS tabelas."""

    nome_completo = forms.CharField(label="Nome completo", max_length=150)
    cpf = forms.CharField(label="CPF", max_length=14, help_text="Somente números ou no formato 000.000.000-00.")
    email = forms.EmailField(label="E-mail")
    telefone = forms.CharField(label="Telefone (opcional)", max_length=15, required=False)
    bairro = forms.ModelChoiceField(label="Bairro onde mora", queryset=Bairro.objects.all(), empty_label="Selecione o bairro")
    senha1 = forms.CharField(label="Senha", widget=forms.PasswordInput, strip=False)
    senha2 = forms.CharField(label="Confirme a senha", widget=forms.PasswordInput, strip=False)
    aceite = forms.BooleanField(
        label="Li o aviso de privacidade e estou ciente de como meus dados serão tratados.",
        error_messages={"required": "É preciso declarar ciência do aviso de privacidade."},
    )

    def clean_nome_completo(self):
        nome = " ".join(self.cleaned_data["nome_completo"].split())
        if len(nome.split()) < 2:
            raise forms.ValidationError("Informe nome e sobrenome.")
        return nome

    def clean_cpf(self):
        cpf = so_digitos(self.cleaned_data["cpf"])
        validar_cpf(cpf)  # dígitos verificadores: regra matemática, não revela nada da base
        # NÃO verificamos aqui se o CPF já existe: um erro diferente para CPF
        # cadastrado permitiria enumerar a base. Quem trata o caso é o
        # services.solicitar_cadastro, sem mudar a resposta da tela.
        return cpf

    def clean_telefone(self):
        return so_digitos(self.cleaned_data.get("telefone"))

    def clean(self):
        dados = super().clean()
        s1, s2 = dados.get("senha1"), dados.get("senha2")
        if s1 and s2 and s1 != s2:
            self.add_error("senha2", "As senhas não conferem.")
        elif s1:
            # Validadores do settings.AUTH_PASSWORD_VALIDATORS: tamanho mínimo,
            # senha comum, só números, parecida com os dados do usuário.
            provisorio = User(
                username=dados.get("cpf", ""),
                email=dados.get("email", ""),
                first_name=(dados.get("nome_completo") or "").split(" ")[0],
            )
            try:
                password_validation.validate_password(s1, provisorio)
            except forms.ValidationError as erros:
                self.add_error("senha1", erros)
        return dados


class VariosArquivosInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class FotosField(forms.FileField):
    """Campo que aceita vários arquivos e devolve as fotos já tratadas."""

    def __init__(self, *args, maximo=3, **kwargs):
        self.maximo = maximo
        kwargs.setdefault("widget", VariosArquivosInput(attrs={"accept": "image/jpeg,image/png,image/webp"}))
        kwargs.setdefault("required", False)
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        from .imagens import processar_foto

        arquivos = [a for a in (data if isinstance(data, (list, tuple)) else [data]) if a]
        if len(arquivos) > self.maximo:
            raise forms.ValidationError(f"Envie no máximo {self.maximo} foto{'s' if self.maximo > 1 else ''}.")
        return [processar_foto(a) for a in arquivos]


class NovaSolicitacaoForm(forms.ModelForm):
    """Usado pelo cidadão para abrir uma solicitação (RF02)."""

    class Meta:
        model = Solicitacao
        # Lista explícita de campos: o cidadão NÃO pode enviar status,
        # prioridade ou responsável, mesmo editando o HTML no navegador.
        # (Proteção contra "mass assignment".)
        fields = ["categoria", "bairro", "endereco_referencia", "descricao", "latitude", "longitude"]
        labels = {
            "categoria": "Tipo de serviço",
            "endereco_referencia": "Endereço ou ponto de referência",
            "descricao": "Descreva o problema",
        }
        widgets = {
            "descricao": forms.Textarea(attrs={"rows": 4}),
            "latitude": forms.HiddenInput(),
            "longitude": forms.HiddenInput(),
        }

    fotos = FotosField(label="Fotos do problema (até 3, opcional)", maximo=3)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Só categorias ativas aparecem para o cidadão
        self.fields["categoria"].queryset = (
            CategoriaServico.objects.filter(ativa=True).select_related("secretaria")
        )
        # Mostra a secretaria junto do nome: duas secretarias podem ter
        # categorias com o mesmo nome (o UNIQUE é do par secretaria + nome).
        self.fields["categoria"].label_from_instance = (
            lambda c: f"{c.nome} ({c.secretaria.sigla})"
        )
        self.fields["categoria"].empty_label = "Selecione o serviço"
        self.fields["bairro"].empty_label = "Selecione o bairro"

    def clean_descricao(self):
        """Validação de um campo: método clean_<nome_do_campo>."""
        texto = self.cleaned_data["descricao"].strip()
        if len(texto) < 15:
            raise forms.ValidationError("Descreva o problema com pelo menos 15 caracteres.")
        return texto

    def clean(self):
        """Validação que envolve DOIS campos: método clean() do formulário."""
        from django.conf import settings

        dados = super().clean()
        lat, lng = dados.get("latitude"), dados.get("longitude")
        if (lat is None) != (lng is None):
            raise forms.ValidationError("Marque o ponto no mapa novamente.")
        if lat is not None:
            sul, norte, oeste, leste = settings.MAPA_LIMITES
            if not (sul <= lat <= norte and oeste <= lng <= leste):
                raise forms.ValidationError("O ponto marcado fica fora do município. Confira o mapa.")
        return dados


class AlterarStatusForm(forms.Form):
    """Usado pelo servidor na tela de detalhe (RF05)."""

    novo_status = forms.ChoiceField(label="Novo status")
    observacao = forms.CharField(
        label="Observação", required=False, widget=forms.Textarea(attrs={"rows": 2})
    )
    foto = FotosField(label="Foto do serviço (opcional)", maximo=1)

    def __init__(self, *args, status_atual, **kwargs):
        super().__init__(*args, **kwargs)
        # As opções mudam conforme o status atual (máquina de estados).
        # Mesmo que alguém force outro valor no HTML, o ChoiceField recusa.
        self.fields["novo_status"].choices = proximos_status(status_atual)


class PrioridadeForm(forms.Form):
    prioridade = forms.TypedChoiceField(label="Prioridade", choices=Solicitacao.Prioridade.choices, coerce=int)


class FiltroPainelForm(forms.Form):
    """Filtros do painel. Enviado por GET: os filtros ficam na URL."""

    status = forms.ChoiceField(
        required=False, choices=[("", "Todos")] + list(Solicitacao.Status.choices)
    )
    bairro = forms.ModelChoiceField(
        required=False, queryset=Bairro.objects.all(), empty_label="Todos"
    )
    busca = forms.CharField(required=False, label="Buscar", max_length=100)
    secretaria = forms.ModelChoiceField(required=False, queryset=None, empty_label="Todas")

    def __init__(self, *args, gestor=False, **kwargs):
        super().__init__(*args, **kwargs)
        if gestor:
            from .models import Secretaria
            self.fields["secretaria"].queryset = Secretaria.objects.order_by("sigla")
        else:
            del self.fields["secretaria"]  # servidor só vê a própria secretaria


class ConsultaProtocoloForm(forms.Form):
    """Consulta pública (RF03). UUIDField recusa texto que não seja UUID."""

    protocolo = forms.UUIDField(
        label="Número do protocolo",
        error_messages={"invalid": "Protocolo inválido. Confira o número recebido."},
    )
