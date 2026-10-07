from django import forms

from apps.atendimento.models import Bairro


class CompletarCadastroForm(forms.Form):
    """O gov.br já garantiu nome, CPF e e-mail; faltam os dados do serviço."""

    bairro = forms.ModelChoiceField(label="Bairro onde mora", queryset=Bairro.objects.all(), empty_label="Selecione o bairro")
    telefone = forms.CharField(label="Telefone (opcional)", max_length=15, required=False)
    aceite = forms.BooleanField(label="Li e estou ciente do aviso de privacidade")

    def clean_telefone(self):
        return "".join(c for c in self.cleaned_data.get("telefone", "") if c.isdigit())
