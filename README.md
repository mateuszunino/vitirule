# Agrometeorologia Preventiva para o Míldio da Videira (*Plasmopara viticola*)

Sistema de apoio à decisão (DSS) agrometeorológico baseado em **estimativa de molhamento foliar (LWD)**, **previsão meteorológica de 7 dias**, **risco de infecção primária e secundária (*Plasmopara viticola*)** e **avaliação de custo–benefício por fronteira de Pareto** (aplicações vs. AACPD) sob validação estritamente fora da amostra.

> **Nota de arquitetura e escopo:** Este repositório nasceu como um protótipo de circuito fechado com visão computacional (`vision_pipeline.py`) e assimilação bayesiana de severidade foliar (`epidemiology_assimilation.py`). Uma ablação rigorosa fora da amostra (**360 talhão-safras**, commit `2e8aea8`) mostrou que **a assimilação de severidade não agregou ganho estatístico sobre a decisão puramente preventiva guiada por previsão de 7 dias e lavagem por chuva** (`Δ AACPD = +0,99`, IC 95 % `[-1,81 ; +3,91]`, Wilcoxon `p = 0,462`). Por isso, o projeto foi focado no núcleo agrometeorológico preventivo (**Caminho A**). Os módulos de assimilação bayesiana e visão permanecem testados e versionados no repositório, **desligados por padrão**, para eventual uso quando houver dados experimentais de campo.

---

## 1. Principais achados científicos

### 1.1 O resultado negativo: por que a assimilação de severidade não venceu a previsão climática
Para evitar o "crime inverso" (gerar epidemias com a mesma equação usada no ajuste), construímos um **OSSE (Observing System Simulation Experiment)** em [osse_benchmark.py](osse_benchmark.py) onde a verdade do vinhedo é gerada por um **modelo compartimental SEIR horário discreto** com:
* período latente em 4 estágios seguindo a tabela de Müller-Sleumer / Goidànich (`25 %/d` a 22–25 °C; `7,7 %/d` a 12 °C) — infecções permanecem invisíveis durante a incubação;
* temperaturas cardinais deslocadas e erro microclimático no dossel (`DPD` e abrigo de vento);
* lavagem de fungicida por chuva (`washoff_mm ~ N(25, 8)` mm) e eficácia/meia-vida reais (`0,76 ± 0,08`; `5,5 ± 1,2 d`) **desacoplados** da regra fixa (`15 mm`) e do modelo (`0,60`; `7,0 d`);
* previsão de 7 dias com erro crescente (`0,5 → 2,5 °C` e `3 → 12 %` de UR).

Com a regra congelada antes de tocar os dados (commit `2e8aea8`) e avaliada em **Moselle (LU) e Bordeaux (FR), 2022–2024 (`N = 360` talhão-safras)**, com orçamento igualado ao do DSS:

| Contraste pareado (`N = 360`, 2022–2024) | Δ AACPD média | IC 95 % bootstrap | Wilcoxon `p` | Vitórias |
|---|---:|---|---:|---:|
| **`(d)` DSS com assimilação − `(c)` Previsão + lavagem (sem assimilação)** | **+0,99** | `[-1,81 ; +3,91]` | **0,4618** | 141/360 *(106 empates)* |
| `(c)` Previsão + lavagem − `(b)` Clima observado reativo | -44,68 | `[-51,40 ; -37,91]` | `< 1e-6` | 293/360 |

**Conclusão honesta:** fungicidas protetores não curam lesões já incubadas no compartimento latente `E`. Quando a severidade visível aumenta, a janela ideal de proteção já passou. O ganho prático veio de **estimar molhamento + antecipar surtos na previsão de 7 dias + gerir lavagem por chuva**, não da assimilação foliar.

### 1.2 Fronteira de Pareto: onde está o ganho real frente a calendários fixos
Um calendário uniforme que recebe o mesmo orçamento anual do DSS "trapaceia" por saber de antemão se a safra será seca (5 aplicações) ou chuvosa (11 aplicações). Na prática, o viticultor escolhe um intervalo fixo antes da safra (`7, 10, 12` ou `14` dias).

* **Amostra de desenvolvimento (2022–2024, Moselle e Bordeaux, `N = 360`):** todos os 5 limiares da regra preventiva `(c)` ficaram estritamente abaixo da fronteira de calendários fixos, com maior ganho vertical em **`T = 10,0`** (`7,17` aplicações médias vs. `7,00` do `cal_12d`: **`-84,9` AACPD** abaixo da fronteira interpolada, `p < 1e-6`).
* **Validação estritamente fora da amostra (commit `68ef7fd`, anos inéditos 2019–2021 + 3ª região inédita Alsace/Colmar, `N = 540` talhão-safras):**
  * **`fc_v1_T10` (regra base congelada):** `6,50` aplicações (`-0,50` vs. `cal_12d`) com AACPD **`264,19`** vs. **`285,74`** do `cal_12d` (**`-21,56` AACPD**, IC 95 % `[-26,46 ; -16,77]`, `p < 1e-6`, `381/540` vitórias; `-37,13` abaixo da fronteira interpolada).
  * **`fc_v2_T10` (correção única anti-agrupamento — portão de cobertura residual $P_{\text{est}} \le 0,45$ e piso mínimo de 6 dias):** `5,46` aplicações (`-0,54` vs. `cal_14d`, **50,4 % menos aplicações que o semanal**) com AACPD **`300,31`** vs. **`317,02`** do `cal_14d` (**`-16,71` AACPD**, IC 95 % `[-21,52 ; -11,84]`, `p < 1e-6`, `326/540` vitórias) — **dominância estrita de Pareto** (menos doença *e* menos aplicações simultaneamente) e eliminação do agrupamento em anos chuvosos (em `Bordeaux 2021`, reduziu de `8,60` para `6,60` aplicações mantendo controle equivalente ao `cal_12d`).

### 1.3 Diagnóstico e correção da cobertura do IC 95 % de `r`
Na avaliação inicial do módulo bayesiano, a cobertura de `r` ficou em ~75 % mesmo com a projeção de 7 dias calibrada (93–98 %). O diagnóstico ([diagnose_r_coverage.py](diagnose_r_coverage.py)) isolou a causa: `model="auto"` escolhia Gompertz em ~20 % das curvas geradas pela logística, aplicando a mesma `r_prior` numérica a dois modelos cuja taxa `r` tem escalas distintas (`0/16` de cobertura cruzada). Após separar `r_prior_gompertz` em [epidemiology_assimilation.py](epidemiology_assimilation.py) e medir cobertura dentro do modelo escolhido, a cobertura subiu para **97,9 % (logística)** e **95,8 % (Gompertz)**.

---

## 2. Estimativa de molhamento foliar (LWD) e lacuna de validação por sensor

[leaf_wetness.py](leaf_wetness.py) implementa 4 modelos publicados sobre dados horários (`T`, `UR`, `Td`, `vento`, `chuva`, `radiação`):
1. `rh85` (UR ≥ 85 % ou chuva);
2. `rh90_hysteresis` (Sentelhas et al. 2008);
3. `dpd_hysteresis` (Gillespie et al. 1993 / Gleason et al. 1994 / Sentelhas et al. 2008: início `DPD ≤ 1,8 °C`, seca `≥ 3,8 °C`);
4. `cart_kim2002` (Kim et al. 2002, *Plant Disease* 86:179–185, com ajuste logarítmico de vento FAO-56).

**Limitação importante:** os testes acima usam dados de reanálise Open-Meteo Archive sem sensor de molhamento em campo. A comparação mostra que os estimadores divergem (especialmente entre climas temperados europeus vs. litoral subtropical de SC), mas **não prova qual estimador acerta mais sem sensor real**.

### Levantamento de redes e datasets abertos com sensor de molhamento foliar
* **Luxemburgo (`agrimeteo.lu` / `data.public.lu` — ASTA):** rede com ~38 estações automáticas incluindo o vale do Moselle (exportação CSV por estação no portal e metadados INSPIRE; *Vitimeteo* consome molhamento internamente, sem API aberta uniforme de sensor bruto).
* **França (`meteo.data.gouv.fr` / Météo-France + INRAE AgroClim):** dados horários/diários abertos sob Licença Etalab; sensores brutos de *humectation foliaire* ficam majoritariamente nas redes locais (Chambres d'Agriculture / Data INRAE).
* **Datasets abertos prontos para validação direta com `leaf_wetness.validate_lwd_against_sensor()`:**
  * `abelias/die_off` (GitHub): microclima agrícola com `leaf wetness (min)`, `T`, `UR`, `Td`, `vento`, `chuva` e `radiação`.
  * `Haly.ID` (Zenodo, CC BY 4.0): pomar europeu multiano com sensor de molhamento foliar.
  * `GeoModelLab/octopus` (GitHub) e *Grape Disease Dataset* (Mendeley Data).

---

## 3. Estrutura do repositório

| Arquivo | Papel | Status |
|---|---|---|
| [leaf_wetness.py](leaf_wetness.py) | 4 modelos horários de LWD + validador contra sensor (`validate_lwd_against_sensor`) | **Ativo (núcleo)** |
| [downy_mildew.py](downy_mildew.py) | *Plasmopara viticola*: regra 3-10, incubação de Goidànich, risco secundário e coleta Open-Meteo | **Ativo (núcleo)** |
| [pareto_analysis.py](pareto_analysis.py) | Fronteira de Pareto (`2022–2024`), validação fora da amostra (`2019–2021` + Alsace) e geração de SVG | **Ativo (núcleo)** |
| [osse_benchmark.py](osse_benchmark.py) | OSSE com SEIR mal-especificado e ablação em 4 braços (documentação do resultado negativo) | **Ativo (validação)** |
| [weather_collector.py](weather_collector.py) | Coletor meteorológico horário (Epagri / INMET / Open-Meteo) | **Ativo (infra)** |
| [db.py](db.py), [app.py](app.py), [decision_engine.py](decision_engine.py) | Camada PostgreSQL/psycopg2, API Flask e motor de decisão | **Pronto (infra)** |
| [r/aacpd_validacao.R](r/aacpd_validacao.R) | Validação cruzada Python × R (`< 1e-6`) e análise estatística em DIC (`metan`) | **Pronto (estatística)** |
| [epidemiology_assimilation.py](epidemiology_assimilation.py), [simulator.py](simulator.py), [diagnose_r_coverage.py](diagnose_r_coverage.py) | Assimilação bayesiana em tempo epidemiológico `tau` (logística/Gompertz com prioris separadas) | *Desligado por padrão* |
| [vision_pipeline.py](vision_pipeline.py), [vision_prep.py](vision_prep.py), [vision_eval.py](vision_eval.py), [colab/train_yolo_seg.ipynb](colab/train_yolo_seg.ipynb) | Pipeline YOLO-seg de severidade foliar + avaliação por CCC de Lin | *Desligado por padrão (aguarda campo)* |

---

## 4. Como reproduzir

```powershell
# 1. Ambiente virtual (Python 3.12)
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. Suíte completa de testes (sem rede, sem banco e sem GPU)
.venv\Scripts\python.exe -m pytest tests/ -q

# 3. Curva de Pareto na amostra de desenvolvimento (2022–2024, Moselle & Bordeaux, N=360)
.venv\Scripts\python.exe pareto_analysis.py --mode dev-pareto --n-plots 60

# 4. Validação fora da amostra congelada (2019–2021, Moselle, Bordeaux & Alsace, N=540)
.venv\Scripts\python.exe pareto_analysis.py --mode oos-validate --n-plots 60

# 5. Reprodução da ablação fora da amostra (resultado negativo da assimilação, N=360)
.venv\Scripts\python.exe osse_benchmark.py --suite-oos --n-plots 60 --seed 20240101
```
