"""Adaptadores de hardware. Cada um implementa uma das interfaces de expro.nucleo:

- FonteLocalizacao: ler(agora) -> lista de Leitura      (localizadores nos capacetes)
- SaidaAudio:       tocar(alerta) / parar()             (central de som, rádios, capacetes)
- TravaDetonacao:   liberar() / bloquear()              (relé no circuito de disparo)
"""

from __future__ import annotations

from ..nucleo import Alerta


class AudioMultiplo:
    """Envia o mesmo alerta para várias saídas; a falha de uma não impede as outras."""

    def __init__(self, saidas: list):
        self.saidas = saidas

    def tocar(self, alerta: Alerta) -> None:
        self._em_todas("tocar", alerta)

    def parar(self) -> None:
        self._em_todas("parar")

    def _em_todas(self, metodo: str, *args) -> None:
        erros = []
        for saida in self.saidas:
            try:
                getattr(saida, metodo)(*args)
            except Exception as erro:
                erros.append(f"{type(saida).__name__}: {erro}")
        if erros:
            raise RuntimeError("; ".join(erros))
