"""Sirenes sintéticas (WAV) para os 3 níveis de alerta, só com a biblioteca padrão."""

from __future__ import annotations

import io
import math
import struct
import wave

# Cada padrão é uma lista de trechos (duração_s, frequência_inicial_hz, frequência_final_hz); 0 Hz = silêncio.
PADROES_SIRENE = {
    3: [(0.35, 880, 880), (0.05, 0, 0), (0.60, 660, 660), (1.50, 0, 0)],  # "ding-dong" calmo
    2: [(0.25, 960, 960), (0.25, 720, 720)] * 4 + [(0.40, 0, 0)],  # bipe alternado rápido
    1: [(0.80, 600, 1400), (0.80, 1400, 600)] * 2,  # sirene contínua subindo e descendo
}


def gerar_wav(nivel: int, taxa: int = 16000, volume: float = 0.8) -> bytes:
    """Retorna um WAV curto (mono, 16 bits) próprio para tocar em loop."""
    amostras: list[int] = []
    fase = 0.0
    rampa = max(1, int(0.008 * taxa))  # evita estalos no início e fim de cada bipe
    for duracao, f_ini, f_fim in PADROES_SIRENE[nivel]:
        n = int(duracao * taxa)
        for i in range(n):
            if f_ini == 0:
                amostras.append(0)
                continue
            freq = f_ini + (f_fim - f_ini) * i / n
            fase += 2 * math.pi * freq / taxa
            envelope = min(1.0, i / rampa, (n - i) / rampa)
            valor = volume * envelope * (0.8 * math.sin(fase) + 0.2 * math.sin(3 * fase))
            amostras.append(int(max(-1.0, min(1.0, valor)) * 32767))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as arquivo:
        arquivo.setnchannels(1)
        arquivo.setsampwidth(2)
        arquivo.setframerate(taxa)
        arquivo.writeframes(struct.pack(f"<{len(amostras)}h", *amostras))
    return buffer.getvalue()
