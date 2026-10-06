"""
SAG-Cidadão — tratamento das fotos enviadas
App: atendimento/imagens.py

Nunca guardamos o arquivo como ele chegou. Cada foto é ABERTA, conferida
e REGRAVADA do zero como JPEG. Isso resolve de uma vez:

    - Metadados EXIF: fotos de celular trazem a localização GPS exata de
      onde foram tiradas (muitas vezes, a casa do cidadão), o modelo do
      aparelho e a data. Ao regravar só os pixels, tudo isso é descartado
      (LGPD: necessidade/minimização).
    - Arquivo disfarçado: um script com extensão .jpg não é imagem; o
      Pillow não consegue abrir e o envio é recusado.
    - Bomba de descompressão: um PNG de poucos KB que, aberto, ocupa
      gigabytes de memória (negação de serviço). Limitamos os pixels.
    - Tamanho: lado maior reduzido a 1600 px; ~200 KB por foto.
"""
import io
import warnings

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

TAMANHO_MAXIMO = 8 * 1024 * 1024        # 8 MB por arquivo enviado
PIXELS_MAXIMOS = 40_000_000              # ~ 40 megapixels
LADO_MAXIMO = 1600
FORMATOS_ACEITOS = {"JPEG", "PNG", "WEBP"}


def processar_foto(arquivo):
    """Recebe o arquivo enviado e devolve um ContentFile JPEG limpo."""
    if arquivo.size > TAMANHO_MAXIMO:
        raise ValidationError("Cada foto pode ter no máximo 8 MB.")
    try:
        with warnings.catch_warnings():
            # O aviso de "imagem grande demais" vira erro
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            Image.MAX_IMAGE_PIXELS = PIXELS_MAXIMOS
            imagem = Image.open(arquivo)
            if imagem.format not in FORMATOS_ACEITOS:
                raise ValidationError("Envie fotos em JPEG, PNG ou WebP.")
            imagem.verify()                  # detecta arquivo corrompido
            arquivo.seek(0)
            imagem = Image.open(arquivo)     # verify() inutiliza o objeto: abre de novo
            imagem.load()
    except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning, OSError, SyntaxError):
        raise ValidationError("O arquivo não é uma imagem válida ou é grande demais.")

    imagem = ImageOps.exif_transpose(imagem)  # aplica a rotação do celular antes de jogar o EXIF fora
    imagem = imagem.convert("RGB")             # remove transparência e perfis exóticos
    imagem.thumbnail((LADO_MAXIMO, LADO_MAXIMO))

    saida = io.BytesIO()
    # Sem exif= e sem icc_profile=: o JPEG novo sai SEM metadados
    imagem.save(saida, format="JPEG", quality=82, optimize=True, progressive=True)
    return ContentFile(saida.getvalue(), name="foto.jpg")
