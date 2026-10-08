"""Toca os alertas na saída de som do computador central (ligada à central de som / amplificador)."""

from __future__ import annotations

import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

from ..nucleo import Alerta
from ..sons import gerar_wav


class AudioLocal:
    """Repete o arquivo nivel<N>.wav da pasta até o alerta terminar.

    Grave as mensagens com voz humana (ou TTS) em nivel3.wav, nivel2.wav e nivel1.wav;
    se um arquivo não existir, é usada uma sirene gerada automaticamente.
    """

    def __init__(self, pasta: str | Path = "audios", comando: Optional[list[str]] = None):
        self.pasta = Path(pasta)
        self.comando = comando or _comando_padrao()
        self._parar = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._processo: Optional[subprocess.Popen] = None

    def arquivo(self, nivel: int) -> Path:
        caminho = self.pasta / f"nivel{nivel}.wav"
        if not caminho.exists():
            self.pasta.mkdir(parents=True, exist_ok=True)
            caminho = self.pasta / f"sirene_nivel{nivel}.wav"
            if not caminho.exists():
                caminho.write_bytes(gerar_wav(nivel))
        return caminho

    def tocar(self, alerta: Alerta) -> None:
        self.parar()
        if not self.comando and sys.platform != "win32":
            raise RuntimeError("nenhum reprodutor de áudio encontrado (instale aplay, paplay ou ffplay)")
        arquivo = self.arquivo(alerta.nivel)
        self._parar = threading.Event()
        self._thread = threading.Thread(target=self._repetir, args=(arquivo, self._parar), daemon=True)
        self._thread.start()

    def _repetir(self, arquivo: Path, parar: threading.Event) -> None:
        if sys.platform == "win32" and not self.comando:
            import winsound
            winsound.PlaySound(str(arquivo), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP)
            parar.wait()
            winsound.PlaySound(None, 0)
            return
        while not parar.is_set():
            try:
                self._processo = subprocess.Popen(self.comando + [str(arquivo)], stdout=subprocess.DEVNULL,
                                                  stderr=subprocess.DEVNULL)
            except OSError:
                return
            while self._processo.poll() is None:
                if parar.wait(0.1):
                    self._processo.terminate()
                    return
            if parar.wait(0.05):
                return

    def parar(self) -> None:
        self._parar.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None


def _comando_padrao() -> list[str]:
    if sys.platform == "darwin":
        return ["afplay"]
    if sys.platform == "win32":
        return []  # usa winsound
    for programa, extras in (("paplay", []), ("aplay", ["-q"]),
                             ("ffplay", ["-nodisp", "-autoexit", "-loglevel", "quiet"])):
        if shutil.which(programa):
            return [programa, *extras]
    return []
