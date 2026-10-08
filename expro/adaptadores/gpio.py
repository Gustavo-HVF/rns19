"""Raspberry Pi: relé da trava de detonação e botão físico de emergência.

Requer: pip install gpiozero  (no Raspberry Pi OS já vem instalado)
"""

from __future__ import annotations

from typing import Callable


class TravaRele:
    """Relé em série com o circuito de disparo. Desenergizado = BLOQUEADO (fail-safe).

    Se a central desligar, travar ou perder energia, o relé abre e a detonação fica impedida.
    """

    def __init__(self, pino: int = 17, ativo_em_alto: bool = True):
        from gpiozero import OutputDevice

        self._rele = OutputDevice(pino, active_high=ativo_em_alto, initial_value=False)

    @property
    def liberada(self) -> bool:
        return bool(self._rele.value)

    def liberar(self) -> None:
        self._rele.on()

    def bloquear(self) -> None:
        self._rele.off()


class BotaoEmergencia:
    """Botão de emergência (RN-03).

    Use contato normalmente fechado (NF) ligado ao GND: apertar o botão OU um fio rompido
    abrem o circuito e disparam a emergência.
    """

    def __init__(self, pino: int, ao_acionar: Callable[[], None], normalmente_fechado: bool = True):
        from gpiozero import Button

        self._botao = Button(pino, pull_up=True, bounce_time=0.05)
        if normalmente_fechado:
            self._botao.when_released = ao_acionar
            if not self._botao.is_pressed:  # circuito já aberto ao ligar
                ao_acionar()
        else:
            self._botao.when_pressed = ao_acionar
