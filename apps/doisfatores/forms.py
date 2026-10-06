from django import forms


class CodigoForm(forms.Form):
    codigo = forms.CharField(
        label="Código de 6 dígitos do aplicativo", max_length=20,
        widget=forms.TextInput(attrs={"autocomplete": "one-time-code", "inputmode": "numeric", "autofocus": True}),
    )


class VerificacaoForm(forms.Form):
    codigo = forms.CharField(
        label="Código do aplicativo (ou um código de recuperação)", max_length=20,
        widget=forms.TextInput(attrs={"autocomplete": "one-time-code", "autofocus": True}),
    )
