import importlib.util
import json
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "ferramentas"))

import gerar_notebook_colab  # noqa: E402


def test_notebook_colab_esta_atualizado():
    """Se falhar: rode `python ferramentas/gerar_notebook_colab.py`."""
    atual = (RAIZ / "colab" / "EXPRO_Demo_Colab.ipynb").read_text(encoding="utf-8")
    assert atual == gerar_notebook_colab.gerar()


@pytest.mark.skipif(importlib.util.find_spec("ipywidgets") is None, reason="ipywidgets não instalado")
def test_codigo_do_notebook_roda_sozinho():
    celulas = json.loads(gerar_notebook_colab.gerar())["cells"]
    escopo: dict = {}
    exec("".join(celulas[1]["source"]), escopo)  # dados fictícios
    exec(compile("".join(celulas[2]["source"]), "<colab>", "exec"), escopo)  # código embutido
    escopo["CONFIG"]["simulacao"]["usar_voz"] = False
    painel = escopo["PainelExpro"](escopo["CONFIG"])
    assert "<svg" in painel.mapa.value
    painel.desligar()
