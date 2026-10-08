# PROJETO EXPRO — EXplosion PROtection

**ER Dynamics Group** · CEPI Garavelo Park

Sistema de bloqueio e alerta para detonações industriais (NR-19), baseado na
*Especificação de Requisitos de Software (DERF) — Projeto NR-19: Explosivos*. Funciona como um
**Equipamento de Proteção Coletiva digital**: se houver pelo menos uma pessoa no raio de risco, a
detonação fica bloqueada, e alertas sonoros em 3 níveis orientam a evacuação.

> Projeto estudantil de demonstração. Os sensores são simulados com dados fictícios.
> Não use com explosivos reais.

## Conteúdo

| Pasta | O que tem |
|---|---|
| [`colab/EXPRO_Demo_Colab.ipynb`](colab/EXPRO_Demo_Colab.ipynb) | **Versão 1 — Google Colab**: painel interativo, só demonstração |
| [`expro/`](expro) | **Versão 2 — expansível**: núcleo das regras + adaptadores de hardware |
| [`config/`](config) | Dados fictícios editáveis e exemplo de configuração com hardware real |
| [`docs/EXPANSAO_HARDWARE.md`](docs/EXPANSAO_HARDWARE.md) | Dicas para ligar localizadores nos capacetes e sistemas de áudio |
| [`firmware/capacete_esp32/`](firmware/capacete_esp32) | Esboço de firmware do capacete (ESP32 + GPS + MQTT) |
| [`banner/`](banner) | Banner do projeto (PDF para impressão, 90 × 120 cm) |
| [`tests/`](tests) | Testes automáticos dos requisitos |

## Versão 1 — Google Colab (demonstração)

1. Acesse [colab.research.google.com](https://colab.research.google.com) → **Arquivo → Fazer upload de notebook**
   e escolha `colab/EXPRO_Demo_Colab.ipynb` (ou, com o repositório público, **Arquivo → Abrir notebook → GitHub**).
2. **Ambiente de execução → Executar tudo**.
3. No painel, entre como **Ana** (Técnica de Segurança, PIN `1234`) ou **Carlos** (Blaster, PIN `0000`).

Roteiro sugerido: Carlos aciona o **Nível 3** → as pessoas evacuam → Ana **autoriza** (Nível 2 + contagem) →
use **Entrar no raio** durante a contagem para ver o bloqueio → **EMERGÊNCIA** a qualquer momento.

Os dados fictícios (posições, raios, tempos, usuários) ficam na célula 1. Em `ACELERAR_TEMPO` dá para
deixar a demonstração mais rápida.

## Versão 2 — expansível (terminal, Raspberry Pi, hardware)

Requer Python 3.10 ou mais novo.

```bash
git clone https://github.com/Gustavo-HVF/rns19.git && cd rns19
python -m expro demo            # roteiro automático com os dados fictícios
python -m expro                 # terminal interativo (digite "ajuda")
python -m expro --acelerar 3    # idem, com o relógio 3x mais rápido
```

Comandos do terminal: `login`, `status`, `terreno`, `teste`, `nivel3`, `autorizar`, `detonado`,
`reentrada`, `emergencia`, `parar`, `baixa`, `sim` (move as pessoas fictícias) e `sair`.

Os dados fictícios estão em [`config/cenario_ficticio.toml`](config/cenario_ficticio.toml). Para hardware
real, copie [`config/exemplo_hardware_real.toml`](config/exemplo_hardware_real.toml) e siga o
[guia de expansão](docs/EXPANSAO_HARDWARE.md).

```bash
pip install -e ".[dev]"     # pytest, ipywidgets, paho-mqtt, gpiozero
pytest                      # testes dos requisitos
python ferramentas/gerar_notebook_colab.py   # regenera o notebook após mudar o código
```

### Como o código é organizado

```
 localizadores ──▶ ┌──────────────────────────────┐ ──▶ áudio (caixa de som, rádio, capacetes)
 (fictício/MQTT)   │ expro/nucleo.py              │ ──▶ trava da detonação (relé)
 botão emergência ▶│ regras RF-01..03, RN-01..04  │
                   └──────────────────────────────┘
```

O núcleo não depende de hardware. O notebook do Colab é gerado a partir dos mesmos arquivos
(`nucleo.py`, `sons.py`, `simulacao.py`, `painel_jupyter.py`), então as duas versões seguem as mesmas regras.

### Requisitos do DERF no código

| Requisito | Onde |
|---|---|
| RF-01 — Técnico autoriza a detonação e aciona o Nível 2 | `SistemaExpro.autorizar_detonacao` |
| RF-02 — Verificação da área e Nível 3 | `SistemaExpro.acionar_nivel3` |
| RF-03 — Alerta escalonado em 3 níveis + modo de teste | `criar_alertas`, `SistemaExpro.testar_audio` |
| RN-01 — Bloqueio por presença (inclusive durante a contagem) | `SistemaExpro.bloqueantes`, `_controlar_sequencia` |
| RN-02 — Só o Técnico de Segurança libera a detonação | `Perfil`, `Usuario.eh_tecnico` |
| RN-03 — Botão de emergência: Nível 1 contínuo, interrompe a contagem | `SistemaExpro.acionar_emergencia` |
| RN-04 — Reentrada só com validação do Técnico | `SistemaExpro.validar_reentrada` |
| ESC-03 — Contagem de pessoas no raio | `SistemaExpro.atualizar` / `Varredura` |
| ESC-04 — Terreno escolhido manualmente (define o raio) | `SistemaExpro.selecionar_terreno` |
| Ator 3 — Intervalo de 30 s entre avisos e duração dos áudios | `_motivo_espera`, `_controlar_audio` |

Além do DERF, por segurança: capacete **sem sinal** conta como pessoa na área (configurável), a trava
começa sempre **bloqueada**, e falhas de sensor ou de áudio são registradas sem derrubar o bloqueio.

## Equipe

Analistas do DERF: Erik Santos Figueredo e Robson Thauan Pereira Braz Santos — ER Dynamics Group.
