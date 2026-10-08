"""Leitura do arquivo de configuração (TOML) e montagem do sistema com o hardware escolhido."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from .nucleo import Configuracao, SistemaExpro, usuarios_de_config
from .simulacao import AudioConsole, LocalizadorSimulado, TravaSimulada

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib


def carregar_config(caminho: str | Path) -> dict:
    with open(caminho, "rb") as arquivo:
        return tomllib.load(arquivo)


def montar_sistema(config: dict, relogio: Callable[[], float] = time.monotonic,
                   imprimir: Callable[[str], None] = print) -> tuple[SistemaExpro, dict]:
    """Cria o sistema conforme a seção [hardware]. Devolve também os componentes criados."""
    hw = config.get("hardware", {})
    componentes: dict = {}
    conexao = None

    def mqtt():
        nonlocal conexao
        if conexao is None:
            from .adaptadores.mqtt import ConexaoMQTT
            opcoes = hw.get("mqtt", {})
            conexao = ConexaoMQTT(opcoes.get("host", "localhost"), int(opcoes.get("porta", 1883)),
                                  opcoes.get("usuario", ""), opcoes.get("senha", ""))
            componentes["mqtt"] = conexao
        return conexao

    # Localização dos capacetes
    tipo_localizacao = hw.get("localizacao", "simulado")
    if tipo_localizacao == "simulado":
        velocidade = config.get("simulacao", {}).get("velocidade_evacuacao_m_s", 8.0)
        localizador = LocalizadorSimulado(config.get("trabalhadores_simulados", []), velocidade)
        componentes["simulador"] = localizador
    elif tipo_localizacao == "mqtt":
        from .adaptadores.mqtt import LocalizadorMQTT
        origem = hw.get("mqtt", {}).get("origem_gps")
        localizador = LocalizadorMQTT(mqtt(), hw.get("mqtt", {}).get("topico_posicao", "expro/capacetes/+/posicao"),
                                      tuple(origem) if origem else None, relogio)
    else:
        raise ValueError(f"hardware.localizacao inválido: {tipo_localizacao}")

    # Saídas de áudio
    saidas = []
    for tipo in hw.get("audio", ["console"]):
        if tipo == "console":
            saidas.append(AudioConsole(imprimir))
        elif tipo == "local":
            from .adaptadores.audio_local import AudioLocal
            saidas.append(AudioLocal(hw.get("audio_local", {}).get("pasta", "audios")))
        elif tipo == "mqtt":
            from .adaptadores.mqtt import AudioMQTT
            saidas.append(AudioMQTT(mqtt(), hw.get("mqtt", {}).get("topico_alerta", "expro/alerta")))
        else:
            raise ValueError(f"hardware.audio inválido: {tipo}")
    if len(saidas) == 1:
        audio = saidas[0]
    else:
        from .adaptadores import AudioMultiplo
        audio = AudioMultiplo(saidas)

    # Trava da detonação
    tipo_trava = hw.get("trava", "simulada")
    if tipo_trava == "simulada":
        trava = TravaSimulada()
    elif tipo_trava == "gpio":
        from .adaptadores.gpio import TravaRele
        gpio = hw.get("gpio", {})
        trava = TravaRele(int(gpio.get("pino_rele", 17)), bool(gpio.get("rele_ativo_em_alto", True)))
    else:
        raise ValueError(f"hardware.trava inválido: {tipo_trava}")

    sistema = SistemaExpro(Configuracao.de_dict(config.get("sistema", {})), localizador, audio, trava,
                           usuarios_de_config(config.get("usuarios", [])), relogio)

    # Entradas de emergência (RN-03)
    gpio = hw.get("gpio", {})
    if "pino_emergencia" in gpio:
        from .adaptadores.gpio import BotaoEmergencia
        componentes["botao_emergencia"] = BotaoEmergencia(
            int(gpio["pino_emergencia"]), lambda: sistema.acionar_emergencia("botão físico"),
            bool(gpio.get("emergencia_nf", True)))
    if conexao is not None:
        topico = hw.get("mqtt", {}).get("topico_emergencia", "expro/emergencia")
        conexao.assinar(topico, lambda t, p: sistema.acionar_emergencia(f"MQTT {t}"))
    return sistema, componentes
