import io
import json
import time
import wave
from pathlib import Path

import pytest

from expro.adaptadores import AudioMultiplo
from expro.adaptadores.mqtt import interpretar_posicao, latlon_para_xy
from expro.config import carregar_config, montar_sistema
from expro.nucleo import criar_alertas
from expro.simulacao import AudioConsole, demonstracao
from expro.sons import gerar_wav

RAIZ = Path(__file__).resolve().parent.parent


def test_latlon_para_xy_distancias_conhecidas():
    x, y = latlon_para_xy(-16.0 + 0.001, -49.0, -16.0, -49.0)  # ~111 m ao norte
    assert abs(x) < 1e-6 and 110 < y < 112
    x, y = latlon_para_xy(-16.0, -49.0 + 0.001, -16.0, -49.0)  # ~107 m a leste (cos 16°)
    assert 106 < x < 108 and abs(y) < 1e-6


def test_interpretar_posicao_xy_e_gps():
    leitura = interpretar_posicao("expro/capacetes/CAP-07/posicao", b'{"x": 10, "y": -5, "nome": "Ana"}', 3.0)
    assert (leitura.id, leitura.x, leitura.y, leitura.instante, leitura.nome) == ("CAP-07", 10, -5, 3.0, "Ana")
    leitura = interpretar_posicao("expro/capacetes/CAP-08/posicao",
                                  json.dumps({"lat": -16.001, "lon": -49.0}).encode(), 0.0, (-16.0, -49.0))
    assert leitura.id == "CAP-08" and -112 < leitura.y < -110


@pytest.mark.parametrize("payload", [b"lixo", b'{"lat": 1, "lon": 2}', b'{"x": "a", "y": 1}',
                                     b'{"x": NaN, "y": 1}', b"[1, 2]"])
def test_interpretar_posicao_rejeita_mensagens_invalidas(payload):
    assert interpretar_posicao("expro/capacetes/CAP-01/posicao", payload, 0.0) is None


def test_sirenes_sao_wav_validos():
    for nivel in (1, 2, 3):
        with wave.open(io.BytesIO(gerar_wav(nivel))) as arquivo:
            assert arquivo.getnchannels() == 1 and arquivo.getframerate() == 16000
            assert 2.0 < arquivo.getnframes() / arquivo.getframerate() < 4.0


def test_audio_multiplo_continua_mesmo_com_falha():
    class Quebrado:
        def tocar(self, alerta):
            raise OSError("sem caixa de som")

        def parar(self):
            pass

    console = AudioConsole()
    multiplo = AudioMultiplo([Quebrado(), console])
    with pytest.raises(RuntimeError):
        multiplo.tocar(criar_alertas()[2])
    assert console.tocando.nivel == 2


def test_config_ficticia_monta_e_roda():
    config = carregar_config(RAIZ / "config" / "cenario_ficticio.toml")
    sistema, componentes = montar_sistema(config, imprimir=lambda _: None)
    assert "simulador" in componentes
    assert sistema.atualizar().dentro
    assert sistema.autenticar("tecnico", "1234")


def test_config_de_hardware_e_valida():
    config = carregar_config(RAIZ / "config" / "exemplo_hardware_real.toml")
    assert config["hardware"]["localizacao"] == "mqtt"
    assert config["hardware"]["trava"] == "gpio"


def test_demonstracao_completa():
    linhas = []
    sistema = demonstracao(carregar_config(RAIZ / "config" / "cenario_ficticio.toml"), linhas.append)
    texto = "\n".join(linhas)
    for marca in ("RN-01", "RN-02", "RN-03", "RN-04", "Detonação LIBERADA"):
        assert marca in texto
    assert sistema.audio.historico == [3, 2, 2, 3, 1]
    assert not sistema.trava.liberada


def test_trava_rele_e_botao_emergencia_gpio():
    gpiozero = pytest.importorskip("gpiozero")
    from gpiozero.pins.mock import MockFactory

    from expro.adaptadores.gpio import BotaoEmergencia, TravaRele

    gpiozero.Device.pin_factory = MockFactory()
    trava = TravaRele(17)
    assert not trava.liberada
    trava.liberar()
    assert trava.liberada
    trava.bloquear()
    assert not trava.liberada

    acionamentos = []
    pino = gpiozero.Device.pin_factory.pin(27)
    botao = BotaoEmergencia(27, lambda: acionamentos.append(1))  # noqa: F841 (precisa continuar vivo)
    assert acionamentos == [1]  # circuito aberto ao ligar (pull-up, nada conectado) = emergência
    pino.drive_low()  # contato NF fechado = normal
    acionamentos.clear()
    time.sleep(0.1)  # respeita o debounce de 50 ms
    pino.drive_high()  # botão apertado ou fio rompido
    assert acionamentos == [1]
