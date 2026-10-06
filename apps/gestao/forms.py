"""
SAG-Cidadão — formulários da área de gestão
App: gestao/forms.py
"""
from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.models import User

from apps.atendimento.models import AreaAtuacao, Bairro, CategoriaServico, Secretaria, Servidor


class SecretariaForm(forms.ModelForm):
    class Meta:
        model = Secretaria
        fields = ["sigla", "nome", "email", "ativa"]


class BairroForm(forms.ModelForm):
    class Meta:
        model = Bairro
        fields = ["nome", "zona"]


class CategoriaForm(forms.ModelForm):
    class Meta:
        model = CategoriaServico
        fields = ["secretaria", "nome", "prazo_dias", "ativa"]
        labels = {"prazo_dias": "Prazo de atendimento (dias)"}


class AreaAtuacaoForm(forms.ModelForm):
    class Meta:
        model = AreaAtuacao
        fields = ["secretaria", "bairro", "data_inicio"]
        widgets = {"data_inicio": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}
        labels = {"data_inicio": "Atende desde"}


class ServidorForm(forms.Form):
    """
    Cria ou edita um servidor = usuário de login (User) + perfil (Servidor).
    Mesma ideia do autocadastro: um Form que grava em duas tabelas.
    """

    first_name = forms.CharField(label="Nome", max_length=150)
    last_name = forms.CharField(label="Sobrenome", max_length=150)
    email = forms.EmailField(label="E-mail institucional")
    username = forms.CharField(label="Usuário de login", max_length=150)
    matricula = forms.CharField(label="Matrícula", max_length=20)
    secretaria = forms.ModelChoiceField(queryset=Secretaria.objects.filter(ativa=True), empty_label="Selecione")
    gestor = forms.BooleanField(label="Também é gestor (acesso ao dashboard e aos cadastros)", required=False)
    senha = forms.CharField(
        label="Senha inicial", widget=forms.PasswordInput, required=False, strip=False,
        help_text="Obrigatória no cadastro. Na edição, deixe em branco para manter a atual.",
    )

    def __init__(self, *args, servidor=None, **kwargs):
        self.servidor = servidor
        super().__init__(*args, **kwargs)

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        outros = User.objects.filter(username=username)
        if self.servidor:
            outros = outros.exclude(pk=self.servidor.usuario_id)
        if outros.exists():
            raise forms.ValidationError("Já existe um usuário com este login.")
        return username

    def clean_matricula(self):
        matricula = self.cleaned_data["matricula"].strip()
        outros = Servidor.objects.filter(matricula=matricula)
        if self.servidor:
            outros = outros.exclude(pk=self.servidor.pk)
        if outros.exists():
            raise forms.ValidationError("Matrícula já cadastrada.")
        return matricula

    def clean(self):
        dados = super().clean()
        senha = dados.get("senha")
        if not self.servidor and not senha:
            self.add_error("senha", "Informe a senha inicial.")
        elif senha:
            try:
                password_validation.validate_password(senha, User(username=dados.get("username", "")))
            except forms.ValidationError as erros:
                self.add_error("senha", erros)
        return dados
