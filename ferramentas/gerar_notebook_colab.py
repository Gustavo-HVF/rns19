"""Gera colab/EXPRO_Demo_Colab.ipynb embutindo o código do pacote expro (versão autossuficiente).

    python ferramentas/gerar_notebook_colab.py

Rode de novo sempre que alterar expro/nucleo.py, sons.py, simulacao.py ou painel_jupyter.py.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "colab" / "EXPRO_Demo_Colab.ipynb"
MODULOS = ["expro/nucleo.py", "expro/sons.py", "expro/simulacao.py", "expro/painel_jupyter.py"]

INTRODUCAO = """\
# PROJETO EXPRO — EXplosion PROtection
**ER Dynamics Group** · Demonstração do sistema de bloqueio e alerta para detonações (NR-19), com **dados fictícios**.

1. Rode as células **1**, **2** e **3** em ordem (▶ de cada uma, ou *Ambiente de execução → Executar tudo*).
2. No painel, entre com um usuário: **Ana** (Técnica de Segurança) PIN `1234` · **Carlos** (Blaster) PIN `0000`.
3. Para mudar os dados fictícios, edite a célula 1 e rode tudo de novo.
"""

CELULA_DADOS = """\
#@title 1. Dados fictícios (edite à vontade) { display-mode: "form" }
TERRENO = "rocha_dura"  #@param ["solo", "rocha_branda", "rocha_dura"]
ACELERAR_TEMPO = 1  #@param {type:"slider", min:1, max:5, step:1}
USAR_VOZ = True  #@param {type:"boolean"}

CONFIG = {
    "sistema": {
        "explosivo_xy": (0, 0),  # metros (x = leste, y = norte)
        "raios_terreno_m": {"solo": 150, "rocha_branda": 200, "rocha_dura": 250},
        "terreno": TERRENO,
        "duracao_nivel3_s": 15,
        "duracao_nivel2_s": 30,
        "intervalo_entre_avisos_s": 30,
        "contagem_regressiva_s": 30,
        "janela_disparo_s": 60,
        "timeout_sinal_s": 10,
        "bloquear_sem_sinal": True,
    },
    "usuarios": [
        {"login": "tecnico", "nome": "Ana", "perfil": "tecnico", "pin": "1234"},
        {"login": "blaster", "nome": "Carlos", "perfil": "operario", "pin": "0000"},
    ],
    # "Capacetes" com localizador: posição inicial de cada trabalhador (metros)
    "trabalhadores_simulados": [
        {"id": "CAP-01", "nome": "João", "x": 60, "y": 40},
        {"id": "CAP-02", "nome": "Maria", "x": -120, "y": 90},
        {"id": "CAP-03", "nome": "Pedro", "x": 150, "y": -170},
        {"id": "CAP-04", "nome": "Lucas", "x": 320, "y": 210},
        {"id": "CAP-05", "nome": "Rafaela", "x": -290, "y": -240},
    ],
    "simulacao": {
        "velocidade_evacuacao_m_s": 8,
        "acelerar_tempo": ACELERAR_TEMPO,
        "usar_voz": USAR_VOZ,
    },
}
print("Dados carregados.")
"""

CELULA_PAINEL = """\
#@title 3. Painel do sistema { display-mode: "form" }
import importlib.util, subprocess, sys
if CONFIG["simulacao"]["usar_voz"] and importlib.util.find_spec("gtts") is None:
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "gTTS"], check=False)

painel = PainelExpro(CONFIG)
painel.mostrar()
"""

CELULA_ROTEIRO = """\
#@title 4. (Opcional) Roteiro automático, sem cliques { display-mode: "form" }
demonstracao(CONFIG);
"""


def codigo_embutido() -> str:
    partes = ["#@title 2. Código do sistema (só rodar) { display-mode: \"form\" }",
              "from __future__ import annotations"]
    for caminho in MODULOS:
        fonte = (RAIZ / caminho).read_text(encoding="utf-8")
        arvore = ast.parse(fonte)
        remover: set[int] = set()
        corpo = arvore.body
        if corpo and isinstance(corpo[0], ast.Expr) and isinstance(getattr(corpo[0], "value", None), ast.Constant):
            remover.update(range(corpo[0].lineno, corpo[0].end_lineno + 1))  # docstring do módulo
        for no in corpo:
            if isinstance(no, ast.ImportFrom) and (no.level > 0 or no.module == "__future__"):
                remover.update(range(no.lineno, no.end_lineno + 1))
        linhas = [linha for numero, linha in enumerate(fonte.splitlines(), 1) if numero not in remover]
        partes.append(f"\n# {'=' * 76}\n# {caminho}\n# {'=' * 76}\n" + "\n".join(linhas).strip())
    partes.append('\nprint("Sistema EXPRO carregado.")')
    return "\n".join(partes) + "\n"


def _celula(tipo: str, fonte: str, oculta: bool = False) -> dict:
    celula = {"cell_type": tipo, "metadata": {}, "source": fonte.splitlines(keepends=True)}
    if tipo == "code":
        celula.update(execution_count=None, outputs=[])
        if oculta:
            celula["metadata"]["cellView"] = "form"
    return celula


def gerar() -> str:
    notebook = {
        "nbformat": 4,
        "nbformat_minor": 0,
        "metadata": {
            "colab": {"provenance": [], "name": "EXPRO_Demo_Colab.ipynb"},
            "kernelspec": {"name": "python3", "display_name": "Python 3"},
            "language_info": {"name": "python"},
        },
        "cells": [
            _celula("markdown", INTRODUCAO),
            _celula("code", CELULA_DADOS, oculta=True),
            _celula("code", codigo_embutido(), oculta=True),
            _celula("code", CELULA_PAINEL, oculta=True),
            _celula("code", CELULA_ROTEIRO, oculta=True),
        ],
    }
    return json.dumps(notebook, ensure_ascii=False, indent=1) + "\n"


if __name__ == "__main__":
    DESTINO.parent.mkdir(exist_ok=True)
    DESTINO.write_text(gerar(), encoding="utf-8")
    print(f"Gerado: {DESTINO.relative_to(RAIZ)}")
