"""Integração via MQTT: capacetes enviam posição; alto-falantes e capacetes recebem os alertas.

Tópicos (padrão):
  expro/capacetes/<ID>/posicao  <- {"x": 12.5, "y": -40.0}  ou  {"lat": -16.68, "lon": -49.25}
  expro/emergencia              <- qualquer mensagem aciona o RN-03
  expro/alerta                  -> {"nivel": 2, "titulo": "...", "mensagem": "...", "duracao_s": 30}
                                   {"nivel": 0} = silêncio (mensagem retida)

Requer: pip install paho-mqtt
"""

from __future__ import annotations

import json
import math
import threading
import time
from typing import Callable, Optional

from ..nucleo import Alerta, Leitura

RAIO_TERRA_M = 6_371_000.0


def latlon_para_xy(lat: float, lon: float, lat0: float, lon0: float) -> tuple[float, float]:
    """Converte GPS para metros (x = leste, y = norte) a partir da origem (lat0, lon0).

    Aproximação equirretangular: erro desprezível para distâncias de poucos quilômetros.
    """
    x = math.radians(lon - lon0) * RAIO_TERRA_M * math.cos(math.radians(lat0))
    y = math.radians(lat - lat0) * RAIO_TERRA_M
    return x, y


def interpretar_posicao(topico: str, payload: bytes, agora: float,
                        origem_gps: Optional[tuple[float, float]] = None) -> Optional[Leitura]:
    """Transforma uma mensagem MQTT de posição em Leitura (ou None se inválida)."""
    partes = topico.split("/")
    if len(partes) < 2:
        return None
    id_capacete = partes[-2]
    try:
        dados = json.loads(payload.decode("utf-8"))
        if "x" in dados and "y" in dados:
            x, y = float(dados["x"]), float(dados["y"])
        elif "lat" in dados and "lon" in dados and origem_gps is not None:
            x, y = latlon_para_xy(float(dados["lat"]), float(dados["lon"]), *origem_gps)
        else:
            return None
    except (ValueError, TypeError, AttributeError, UnicodeDecodeError):
        return None
    if not (math.isfinite(x) and math.isfinite(y)):
        return None
    return Leitura(id_capacete, x, y, agora, str(dados.get("nome", "")))


class ConexaoMQTT:
    """Uma conexão compartilhada com o broker (ex.: Mosquitto num Raspberry Pi)."""

    def __init__(self, host: str = "localhost", porta: int = 1883, usuario: str = "", senha: str = "",
                 cliente_id: str = "expro-central"):
        import paho.mqtt.client as mqtt

        self._assinaturas: dict[str, Callable[[str, bytes], None]] = {}
        self.cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=cliente_id)
        if usuario:
            self.cliente.username_pw_set(usuario, senha)
        self.cliente.on_connect = self._ao_conectar
        self.cliente.on_message = self._ao_receber
        self.cliente.connect(host, porta, keepalive=30)
        self.cliente.loop_start()

    def assinar(self, filtro: str, callback: Callable[[str, bytes], None]) -> None:
        self._assinaturas[filtro] = callback
        self.cliente.subscribe(filtro, qos=1)

    def publicar(self, topico: str, dados: dict, reter: bool = False) -> None:
        self.cliente.publish(topico, json.dumps(dados, ensure_ascii=False), qos=1, retain=reter)

    def _ao_conectar(self, cliente, userdata, flags, reason_code, properties) -> None:
        for filtro in self._assinaturas:  # reassina após reconexão
            cliente.subscribe(filtro, qos=1)

    def _ao_receber(self, cliente, userdata, mensagem) -> None:
        import paho.mqtt.client as mqtt

        for filtro, callback in self._assinaturas.items():
            if mqtt.topic_matches_sub(filtro, mensagem.topic):
                callback(mensagem.topic, mensagem.payload)

    def fechar(self) -> None:
        self.cliente.loop_stop()
        self.cliente.disconnect()


class LocalizadorMQTT:
    """Recebe as posições publicadas pelos capacetes (ESP32 + GPS/UWB, gateway LoRa etc.)."""

    def __init__(self, conexao: ConexaoMQTT, topico: str = "expro/capacetes/+/posicao",
                 origem_gps: Optional[tuple[float, float]] = None,
                 relogio: Callable[[], float] = time.monotonic):
        self.origem_gps = origem_gps
        self.relogio = relogio
        self._pendentes: list[Leitura] = []
        self._lock = threading.Lock()
        conexao.assinar(topico, self._receber)

    def _receber(self, topico: str, payload: bytes) -> None:
        leitura = interpretar_posicao(topico, payload, self.relogio(), self.origem_gps)
        if leitura is not None:
            with self._lock:
                self._pendentes.append(leitura)

    def ler(self, agora: float) -> list[Leitura]:
        with self._lock:
            leituras, self._pendentes = self._pendentes, []
        return leituras


class AudioMQTT:
    """Publica o nível de alerta para alto-falantes IP, gateways de rádio e capacetes."""

    def __init__(self, conexao: ConexaoMQTT, topico: str = "expro/alerta"):
        self.conexao = conexao
        self.topico = topico
        self.parar()

    def tocar(self, alerta: Alerta) -> None:
        self.conexao.publicar(self.topico, {"nivel": alerta.nivel, "titulo": alerta.titulo,
                                            "mensagem": alerta.mensagem, "duracao_s": alerta.duracao_s},
                              reter=True)

    def parar(self) -> None:
        self.conexao.publicar(self.topico, {"nivel": 0}, reter=True)
