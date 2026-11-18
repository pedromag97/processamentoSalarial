"""Gera o ícone do programa a partir da imagem do símbolo.

    uv run python scripts/gerar_icone.py caminho\\para\\simbolo.png

O fundo branco passa a transparente, a imagem é centrada num quadrado e gravam-se:
- src/lsc_presencas/recursos/icone.ico  (vários tamanhos; executável e atalhos)
- src/lsc_presencas/recursos/icone.png  (256 px; janelas do programa)
"""

import sys
from pathlib import Path

from PIL import Image

DESTINO = Path(__file__).resolve().parents[1] / "src" / "lsc_presencas" / "recursos"
TAMANHOS = [16, 20, 24, 32, 40, 48, 64, 128, 256]
MARGEM = 0.06  # espaço à volta do símbolo, em fração do lado
BRANCO = 245  # a partir daqui considera-se fundo


def gerar(origem: Path) -> None:
    original = Image.open(origem).convert("RGBA")
    # Se a imagem já tiver zonas transparentes, tratam-se como fundo branco.
    imagem = Image.new("RGBA", original.size, (255, 255, 255, 255))
    imagem.alpha_composite(original)
    # Transparência proporcional à claridade: as bordas ficam suaves, sem contorno branco.
    cinzento = imagem.convert("L")
    alfa = cinzento.point(lambda v: 0 if v >= BRANCO else min(255, int((BRANCO - v) * 4)))
    imagem.putalpha(alfa)
    imagem = imagem.crop(alfa.getbbox())

    lado = int(max(imagem.size) * (1 + 2 * MARGEM))
    quadrado = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    quadrado.paste(imagem, ((lado - imagem.width) // 2, (lado - imagem.height) // 2), imagem)

    DESTINO.mkdir(parents=True, exist_ok=True)
    grande = quadrado.resize((256, 256), Image.LANCZOS)
    grande.save(DESTINO / "icone.png")
    grande.save(DESTINO / "icone.ico", sizes=[(t, t) for t in TAMANHOS])
    print("gravado em", DESTINO)


if __name__ == "__main__":
    gerar(Path(sys.argv[1]))
