"""
Backend de e-mail para DESENVOLVIMENTO: imprime a mensagem legível no terminal.

O backend de console padrão imprime o e-mail já codificado (quoted-printable),
que quebra linhas longas com "=" no fim e parte os links ao meio. Este mostra
o texto como o destinatário veria, com o link inteiro em uma linha.
Em produção, use o backend SMTP (configurado no .env).
"""
from django.core.mail.backends.console import EmailBackend as ConsoleBackend


class EmailBackend(ConsoleBackend):
    def write_message(self, message):
        linha = "=" * 72
        self.stream.write(
            f"\n{linha}\n E-MAIL (modo desenvolvimento, não foi enviado de verdade)\n{linha}\n"
            f"De: {message.from_email}\nPara: {', '.join(message.to)}\nAssunto: {message.subject}\n\n"
            f"{message.body}\n{linha}\n"
        )
