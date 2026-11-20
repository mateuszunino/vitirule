# Metodologia Aberta de Avaliação para DSS Preventivo de Míldio da Videira (*Plasmopara viticola*)

Repositório aberto e reprodutível focado na **avaliação rigorosa de regras agrometeorológicas preventivas** para o míldio da videira (*Plasmopara viticola*), combinando:
1. **validação empírica de estimadores de molhamento foliar (LWD)** contra sensores reais de campo (decompondo erro do modelo vs. erro da reanálise meteorológica);
2. **OSSE com modelo SEIR mal-especificado** (quebra do "crime inverso", lavagem por chuva e previsão de 7 dias ruidosa);
3. **ablação com orçamento igual** e **fronteira de Pareto** (aplicações vs. AACPD) com validação congelada em anos e regiões inéditos;
4. **função de dano econômico ao cacho** (resultado líquido em €/ha em diferentes faixas de valor do vinhedo).

### Posicionamento frente a sistemas operacionais existentes
Sistemas consolidados como o **VitiMeteo** (*VitiMeteo-Plasmopara*, usado em Luxemburgo/Moselle, Alemanha, Suíça e leste da França) e o **RIMpro** já realizam alerta operacional de *P. viticola* em viticultura europeia. Este projeto **não pretende competir como produto comercial** com essas plataformas. Sua contribuição é a **metodologia aberta de avaliação** (simulador mal-especificado, ablação causal, fronteira de Pareto, congelamento fora da amostra em commits e decomposição econômica/meteorológica), etapa que raramente é publicada de forma reproduzível em sistemas de alerta fitossanitário.

> **Histórico e módulos desligados por padrão:** O projeto começou como um DSS em circuito fechado com visão computacional (`vision_pipeline.py`) e assimilação bayesiana de severidade foliar (`epidemiology_assimilation.py`). Uma ablação congelada fora da amostra (`N = 360`, commit `2e8aea8`) mostrou que **a assimilação de severidade não superou a regra puramente climática com previsão de 7 dias e lavagem por chuva** (`Δ AACPD = +0,99`, IC 95 % `[-1,81 ; +3,91]`, Wilcoxon `p = 0,462`). Os módulos de visão e assimilação permanecem testados no repositório, **desligados por padrão**, para eventual uso quando houver dados experimentais de campo.

---

## 1. Validação de molhamento foliar (LWD) contra sensores reais (`80.392` horas)

Implementada em [lwd_sensor_validation.py](lwd_sensor_validation.py) sobre duas redes independentes abertas:
* **INRAE AgroClim** (`doi:10.57745/BQ0BWB`; Furusho-Percot et al., *Data in Brief* 2025, `PMC12266558`): 4 estações vitícolas francesas (Bordeaux-Couhins `33080002`, Alsace-Colmar `68066002`, Champagne-Fagnières `51242002`, Bourgogne-Bretenière `21106002`; abril–setembro 2022–2024, **52.675 h**).
* **Politecnico di Torino / iXem Labs** (Mendeley Data, `doi:10.17632/sd4b8vpvyb.1`): 7 estações italianas com sensor capacitivo dupla face (abril–setembro, **27.717 h** totais; **23.735 h** nas 6 estações sem deriva de linha de base — `site2.csv` apresentou `99,9 % > 0`).

### Erro do estimador (clima da estação) vs. erro da reanálise (Open-Meteo Archive no mesmo ponto)

| Rede (abril–setembro) | Estimador | Estação: Acc / F1 / CSI / MAE (h/d) / Viés | Open-Meteo: Acc / F1 / CSI / MAE (h/d) / Viés | Penalidade da reanálise (Δ MAE) |
|---|---|---|---|---:|
| **INRAE AgroClim** (4 est. FR, 52,7k h) | **`rh90_hysteresis`** | **0,864 / 0,732 / 0,581 / 2,61 / +0,97** | **0,779 / 0,604 / 0,434 / 4,07 / +2,17** | **+1,46 h/d** |
| | `dpd_hysteresis` | 0,859 / 0,731 / 0,580 / 2,76 / +1,31 | 0,776 / 0,608 / 0,438 / 4,24 / +2,46 | +1,48 h/d |
| | `rh85` | 0,831 / 0,693 / 0,533 / 3,26 / +1,95 | 0,761 / 0,589 / 0,419 / 4,30 / +2,71 | +1,04 h/d |
| | `cart_kim2002` | 0,828 / 0,675 / 0,513 / 3,25 / +1,52 | 0,772 / 0,577 / 0,407 / 3,82 / +1,66 | +0,57 h/d |
| **Polito IT** (6 est. limpas, 23,7k h) | `rh85` | 0,879 / 0,680 / 0,519 / 2,59 / -0,07 | 0,789 / 0,529 / 0,364 / 4,05 / +1,49 | +1,46 h/d |
| | `dpd_hysteresis` | 0,871 / 0,653 / 0,490 / 2,79 / -0,36 | 0,788 / 0,519 / 0,354 / 4,13 / +1,27 | +1,34 h/d |
| | `rh90_hysteresis` | 0,869 / 0,636 / 0,472 / 2,85 / -0,70 | 0,791 / 0,516 / 0,351 / 4,06 / +1,05 | +1,21 h/d |
| | `cart_kim2002` | 0,861 / 0,672 / 0,513 / 2,95 / +1,15 | 0,779 / 0,507 / 0,343 / 4,28 / +1,40 | +1,33 h/d |

**Principais achados empíricos:**
1. **`cart_kim2002` não venceu** em nenhuma das duas redes — ficou em 4º lugar em acurácia e F1 nas 4 estações vitícolas francesas e nas 6 estações italianas limpas. O vencedor nas estações vitícolas francesas foi **`rh90_hysteresis`** (`F1 = 0,732`, `MAE = 2,61 h/d`), praticamente empatado com `dpd_hysteresis`.
2. **A fonte climática pesa mais que a fórmula de LWD:** trocar o clima medido na estação pela reanálise Open-Meteo elevou o erro diário em **`+1,21` a `+1,48 h/dia`** e adicionou viés úmido de `+1,2` a `+1,6 h/dia` — mais que o dobro da diferença entre a melhor e a pior fórmula na estação (`0,65 h/dia`).

---

## 2. Resultado negativo da assimilação e fronteira de Pareto fora da amostra

### 2.1 Ablação congelada (`commit 2e8aea8`, 2022–2024, Moselle & Bordeaux, `N = 360`)
Com verdade gerada por **SEIR horário discreto** (4 estágios latentes de Müller-Sleumer/Goidànich, cardinais deslocadas, erro microclimático no dossel, lavagem `25 ± 8 mm` e eficácia `0,76 ± 0,08` desacopladas da regra fixa de `15 mm`, e previsão ruidosa):
* **`(d)` DSS com assimilação − `(c)` Previsão + lavagem (sem assimilação):** `+0,99` AACPD (`IC 95 %: [-1,81 ; +3,91]`, Wilcoxon `p = 0,462`, `141/360` vitórias) — **empate estatístico**.
* **`(c)` Previsão + lavagem − `(b)` Clima observado reativo:** `-44,68` AACPD (`IC 95 %: [-51,40 ; -37,91]`, `p < 1e-6`, `293/360` vitórias).

### 2.2 Fronteira de Pareto e validações fora da amostra (sem reutilizar anos)
Cada rodada usou um conjunto distinto de anos para evitar vazamento de ajuste:
* **Desenvolvimento (`2022–2024`, Moselle & Bordeaux, `N = 360`):** ponto de operação escolhido em `T = 10,0` (`-84,9` AACPD abaixo da fronteira de calendários fixos `7, 10, 12, 14` dias).
* **Validação OOS #1 (`commit 68ef7fd`, `2019–2021`, Moselle + Bordeaux + região inédita Alsace/Colmar, `N = 540`, `cart_kim2002`):**
  * `fc_v1_T10`: `6,50` aplicações, AACPD `264,19` vs. `285,74` do `cal_12d` (`-21,56`, `p < 1e-6`, `381/540`).
  * `fc_v2_T10` *(alternativa mais econômica na mesma curva de Pareto, com portão residual $P_{\text{est}} \le 0,45$ e piso de 6 d — não uma melhoria absoluta sobre `v1`)*: `5,46` aplicações, AACPD `300,31` vs. `317,02` do `cal_14d` (`-16,71`, `p < 1e-6`, `326/540`).
* **Validação OOS #2 em anos intactos (`commit a562ccc`, `2016–2018`, 3 regiões, `N = 540`, com o estimador vencedor nos sensores reais `rh90_hysteresis`):**

| Estratégia (`2016–2018`, `rh90_hysteresis`, `N = 540`) | Aplicações | AACPD média (IC 95 %) | Pareado vs. calendário próximo |
|---|---:|---:|---|
| `testemunha` | 0,00 | 1174,06 `[1097,9 ; 1251,6]` | — |
| `cal_7d` | 11,00 | 469,07 `[425,3 ; 516,3]` | referência |
| `cal_10d` | 8,00 | 608,20 `[555,2 ; 665,3]` | referência |
| `cal_12d` | 7,00 | 658,60 `[602,7 ; 717,5]` | referência |
| `cal_14d` | 6,00 | 731,26 `[671,9 ; 794,0]` | referência |
| **`fc_v1_T10` (ponto padrão congelado)** | **7,20** | **546,79 `[499,9 ; 598,5]`** | **-111,81 vs `cal_12d`** (`-101,6` abaixo da fronteira; `p < 1e-6`, `412/540`) |
| **`fc_v2_T10` (ponto mais econômico)** | **5,86** | **657,67 `[603,0 ; 716,6]`** | **-73,59 vs `cal_14d`** (`-0,14` aplic.; `p < 1e-6`, `370/540`) |

> **Ressalva metodológica:** embora o SEIR seja mal-especificado em relação à regra (inclusive rodando `rh90_hysteresis` contra verdade movida por `cart_kim2002` + microclima), o tamanho absoluto do ganho (`7 %` a `17 %` de AACPD) ainda é propriedade do simulador; no campo real, a magnitude depende da pressão de cacho e do erro local de previsão.

---

## 3. Avaliação econômica líquida (€/ha) ([economics.py](economics.py))

Usando a função de dano ao cacho $L = 0{,}85(1 - e^{-0{,}0005\cdot \text{AACPD}})$ e custo de `55 €/ha` por pulverização sobre os resultados fora da amostra de **`2016–2018` (`rh90_hysteresis`, `N = 540`)**:

| Estratégia | Aplic. | Perda est. (%) | Vinho de mesa (`5.000 €/ha`) | AOC regional (`12.000 €/ha`) | AOC premium (`25.000 €/ha`) |
|---|---:|---:|---:|---:|---:|
| **`fc_v1_T10`** | **7,20** | 20,3 % | **3.587 €/ha *(1º)*** | 9.164 €/ha *(2º; +279 vs `cal_10d`)* | 19.521 €/ha *(2º; +533 vs `cal_10d`)* |
| **`cal_7d`** | 11,00 | 17,8 % | 3.506 €/ha *(-81)* | **9.263 €/ha *(1º)*** | **19.952 €/ha *(1º)*** |
| `fc_v2_T10` | 5,86 | 23,8 % | 3.487 €/ha *(-101)* | 8.819 €/ha *(-443)* | 18.723 €/ha *(-1.230)* |
| `cal_10d` | 8,00 | 22,3 % | 3.446 €/ha *(-142)* | 8.885 €/ha *(-377)* | 18.988 €/ha *(-964)* |
| `cal_12d` | 7,00 | 23,9 % | 3.423 €/ha *(-165)* | 8.753 €/ha *(-509)* | 18.653 €/ha *(-1.300)* |

**Leitura econômica clara:**
* Em vinhedos de **menor receita bruta (`5.000 €/ha`)**, `fc_v1_T10` entrega o **maior retorno líquido absoluto** (batendo inclusive `cal_7d` em `+81 €/ha` em 2016–2018 e `+159 €/ha` em 2019–2021).
* Em vinhedos **AOC / Premium (`12k–25k €/ha`)**, `cal_7d` ainda maximiza o €/ha puro porque cada ponto percentual de perda de cacho vale muito mais que uma pulverização de `55 €/ha`; porém, sob qualquer meta de redução de fungicidas (ex.: **Ecophyto** / teto de cobre, ≤ 8 aplicações), **`fc_v1_T10` supera `cal_10d` em `+279` a `+533 €/ha`** e `cal_12d` em **`+411` a `+868 €/ha`**.

---

## 4. Calibração da posteriori de `r` (módulo de assimilação)
A subcobertura inicial de `r` (~75 %) decorria de o seletor `model="auto"` aplicar a mesma `r_prior` numérica à logística e à Gompertz. Com `r_prior_gompertz` separada em [epidemiology_assimilation.py](epidemiology_assimilation.py), a cobertura do IC 95 % de `r` medida dentro do modelo escolhido passou para **97,9 % (logística)** e **95,8 % (Gompertz)**.

---

## 5. Como reproduzir

```powershell
# Testes automatizados (sem rede, sem banco, sem GPU)
.venv\Scripts\python.exe -m pytest tests/ -q

# Validação de LWD contra sensores reais (INRAE AgroClim + Politecnico di Torino)
.venv\Scripts\python.exe lwd_sensor_validation.py

# Fronteira de Pareto em desenvolvimento (2022–2024, N=360)
.venv\Scripts\python.exe pareto_analysis.py --mode dev-pareto --n-plots 60

# Validação OOS intacta com o estimador vencedor no sensor (2016–2018, rh90_hysteresis, N=540)
.venv\Scripts\python.exe pareto_analysis.py --mode oos-2016-2018 --lwd-method rh90_hysteresis --n-plots 60

# Avaliação econômica líquida (€/ha)
.venv\Scripts\python.exe economics.py data/fase2/pareto_oos_2016_2018_rh90_hysteresis.json
```
