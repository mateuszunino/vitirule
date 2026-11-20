# `grapevine-downy-mildew-eval` — Metodologia Aberta de Avaliação para DSS Preventivo de Míldio da Videira (*Plasmopara viticola*)

**Autor:** Mateus Zunino Espindola — Universidade Federal de Santa Catarina (UFSC)  
**Relatório técnico (inglês, com Resumo em português):** [docs/technical_report.md](docs/technical_report.md) · [docs/technical_report.pdf](docs/technical_report.pdf)

Repositório aberto e reprodutível focado na **avaliação rigorosa de regras agrometeorológicas preventivas** para o míldio da videira (*Plasmopara viticola*), combinando:
1. **validação empírica de estimadores de molhamento foliar (LWD)** contra `80.392` horas de sensores reais (decompondo erro da fórmula vs. erro da reanálise);
2. **OSSE com modelo SEIR mal-especificado e OSSE semirreal movido por sensor real de campo** (quebra do "crime inverso", lavagem por chuva e previsão de 7 dias ruidosa);
3. **ablação com orçamento igual** e **fronteira de Pareto** (aplicações vs. AACPD) com congelamento em commit e validação em anos e regiões inéditos;
4. **análise econômica com superfície de sensibilidade** (inclinação do dano × receita bruta) e restrição regulatória real de cobre orgânico na União Europeia (**Regulamento de Execução (UE) 2018/1981**).

### Posicionamento frente a sistemas operacionais existentes
Sistemas consolidados como o **VitiMeteo** (*VitiMeteo-Plasmopara*, usado em Luxemburgo/Moselle, Alemanha, Suíça e leste da França) e o **RIMpro** já operam em viticultura europeia. Este projeto **não pretende competir como produto comercial** com essas plataformas. Sua contribuição é a **metodologia aberta de avaliação** (simulador mal-especificado, teste semirreal com sensor, ablação causal, fronteira de Pareto, congelamento fora da amostra em commits e sensibilidade econômica), etapa raramente publicada de forma reprodutível em sistemas de alerta fitossanitário.

> **Histórico e módulos desligados por padrão:** O projeto começou como um DSS em circuito fechado com visão computacional (`vision_pipeline.py`) e assimilação bayesiana de severidade foliar (`epidemiology_assimilation.py`). Uma ablação congelada fora da amostra (`N = 360`, commit `2e8aea8`) mostrou que **a assimilação de severidade não superou a regra puramente climática com previsão de 7 dias e lavagem por chuva** (`Δ AACPD = +0,99`, IC 95 % `[-1,81 ; +3,91]`, Wilcoxon `p = 0,462`). Os módulos de visão e assimilação permanecem testados no repositório, **desligados por padrão**, para eventual uso quando houver dados experimentais de campo.

---

## 1. Validação de molhamento foliar (LWD) contra sensores reais (`80.392` horas)

Implementada em [lwd_sensor_validation.py](lwd_sensor_validation.py) sobre duas redes independentes abertas:
* **INRAE AgroClim** (`doi:10.57745/BQ0BWB`; Furusho-Percot et al., *Data in Brief* 2025, `PMC12266558`): 4 estações vitícolas francesas (Bordeaux-Couhins `33080002`, Alsace-Colmar `68066002`, Champagne-Fagnières `51242002`, Bourgogne-Bretenière `21106002`; abril–setembro 2022–2024, **52.675 h**).
* **Politecnico di Torino / iXem Labs** (Mendeley Data, `doi:10.17632/sd4b8vpvyb.1`): 7 estações italianas com sensor capacitivo dupla face (abril–setembro, **27.717 h** totais; **23.735 h** nas 6 estações sem deriva — `site2.csv` apresentou `99,9 % > 0`).

| Rede (abril–setembro) | Estimador | Estação: Acc / F1 / CSI / MAE (h/d) / Viés | Open-Meteo: Acc / F1 / CSI / MAE (h/d) / Viés | Δ MAE da reanálise |
|---|---|---|---|---:|
| **INRAE AgroClim** (4 est. FR, 52,7k h) | `rh90_hysteresis` | **0,864 / 0,732 / 0,581 / 2,61 / +0,97** | **0,779** / 0,604 / 0,434 / 4,07 / +2,17 | +1,46 h/d |
| | `dpd_hysteresis` | 0,859 / 0,731 / 0,580 / 2,76 / +1,31 | 0,776 / **0,608 / 0,438** / 4,24 / +2,46 | +1,48 h/d |
| | `rh85` | 0,831 / 0,693 / 0,533 / 3,26 / +1,95 | 0,761 / 0,589 / 0,419 / 4,30 / +2,71 | +1,04 h/d |
| | `cart_kim2002` | 0,828 / 0,675 / 0,513 / 3,25 / +1,52 | 0,772 / 0,577 / 0,407 / **3,82** / +1,66 | +0,57 h/d |
| **Polito IT** (6 est. limpas, 23,7k h) | `rh85` | **0,879 / 0,680 / 0,519 / 2,59 / -0,07** | 0,789 / **0,529 / 0,364 / 4,05** / +1,49 | +1,46 h/d |
| | `dpd_hysteresis` | 0,871 / 0,653 / 0,490 / 2,79 / -0,36 | 0,788 / 0,519 / 0,354 / 4,13 / +1,27 | +1,34 h/d |
| | `rh90_hysteresis` | 0,869 / 0,636 / 0,472 / 2,85 / -0,70 | **0,791** / 0,516 / 0,351 / 4,06 / +1,05 | +1,21 h/d |
| | `cart_kim2002` | 0,861 / 0,672 / 0,513 / 2,95 / +1,15 | 0,779 / 0,507 / 0,343 / 4,28 / +1,40 | +1,33 h/d |

**Conclusão empírica principal:**
* **Na entrada operacional (Open-Meteo), os 4 estimadores praticamente empatam** e trocam de posição conforme a métrica (`dpd_hysteresis` lidera em F1 `0,608`, `cart_kim2002` tem o menor MAE `3,82 h/d`, `rh90_hysteresis` lidera em acurácia `0,779`).
* **A fonte do dado meteorológico domina o erro**, não a fórmula de molhamento: sair da estação real para a reanálise Open-Meteo derruba `F1` em ~`0,13` e eleva o erro diário de ~`2,6` para **`4,0 h/dia`** (viés úmido de `+1,6` a `+2,2 h/dia`, autocorrelação horária lag-1 de `0,68`). Consequência operacional direta: um sistema em Luxemburgo deveria ler as estações da rede agrometeorológica local (**ASTA / agrimeteo.lu**), não reanálise.

---

## 2. Resultado negativo da assimilação, fronteira de Pareto e OSSE semirreal com sensor

### 2.1 Ablação congelada (`commit 2e8aea8`, 2022–2024, Moselle & Bordeaux, `N = 360`)
* **`(d)` DSS com assimilação − `(c)` Previsão + lavagem (sem assimilação):** `+0,99` AACPD (`IC 95 %: [-1,81 ; +3,91]`, Wilcoxon `p = 0,462`, `141/360` vitórias) — **empate estatístico**.
* **`(c)` Previsão + lavagem − `(b)` Clima observado reativo:** `-44,68` AACPD (`IC 95 %: [-51,40 ; -37,91]`, `p < 1e-6`, `293/360` vitórias).

### 2.2 Fronteira de Pareto puramente simulada vs. **OSSE semirreal movido pelo sensor INRAE**
Para verificar quanto do ganho simulado sobrevive sob o erro real de `~4 h/dia` da reanálise, executamos [semireal_osse.py](semireal_osse.py) com a **regra congelada (`T = 10,0`, sem nenhum reajuste)** sobre **24 estação-safras reais do INRAE (`2019–2024`, 4 regiões vitícolas, `N = 1.200` talhão-safras)** onde a verdade SEIR é movida pelo **sensor real de molhamento foliar (`h`)** e a regra lê apenas o **Open-Meteo** (`om_*`) ou o clima da **estação local sem sensor** (`st_*`), além de **Moselle `2016–2018` (`N = 180`)** com perturbação AR(1) calibrada nos erros reais (`MAE = 3,99 h/d`, `viés = +1,59 h/d`, `lag-1 = 0,68`):

| Experimento (regra congelada `T = 10,0`) | Estratégia | Aplic. | AACPD média (IC 95 %) | Δ vs. fronteira de calendários | Pareado vs. calendário próximo |
|---|---|---:|---:|---:|---|
| **INRAE Semirreal (verdade = SENSOR REAL, `N = 1.200`)** | `cal_7d` / `10d` / `12d` / `14d` | 11 / 8 / 7 / 6 | 95,5 / 118,5 / 138,6 / 146,5 | referência | — |
| | **`om_v1_T10`** *(só Open-Meteo)* | **6,77** | **121,42 `[112,5 ; 130,9]`** | **-18,95 (-13,5 %)** | **-17,15 vs `cal_12d`** (`-0,23` aplic., `p < 1e-6`, `814/1200`) |
| | `om_v2_T10` *(alternativa econômica)* | **5,51** | **137,31 `[126,9 ; 148,2]`** | abaixo de `cal_14d` | **-9,18 vs `cal_14d`** (`-0,49` aplic., `p < 1e-6`, `652/1200`) |
| | `st_v1_T10` *(clima estação, sem sensor)* | **6,38** | **127,48 `[117,8 ; 137,7]`** | **-15,99 (-11,1 %)** | **-19,01 vs `cal_14d`** (`+0,38` aplic., `p < 1e-6`, `788/1200`) |
| **Moselle erro calibrado (`2016–2018`, `N = 180`)** | `cal_12d` / `cal_14d` | 7 / 6 | 302,1 / 367,6 | referência | — |
| | **`om_v1_T10`** | **7,22** | **277,37 `[243,1 ; 315,9]`** | **-22,70 (-7,6 %)** | **-24,70 vs `cal_12d`** (`p = 4,7e-5`, `120/180`) |
| | `om_v2_T10` | **5,83** | **346,54 `[303,6 ; 394,1]`** | abaixo de `cal_14d` | **-21,03 vs `cal_14d`** (`-0,17` aplic., `p = 0,021`, `99/180`) |

**Quanto do ganho sobrevive:**
* Como esperado, os ganhos absolutos de `-101` AACPD no simulador puramente de reanálise estavam inflados pelo viés úmido do Open-Meteo (`+1,6 h/d`) e pelo acoplamento excessivo entre verdade e entrada.
* Sob **sensor real do INRAE (`N = 1.200`)** e **erro calibrado em Moselle (`N = 180`)**, o ganho absoluto cai para **`-19` a `-23` AACPD (`-7,6 %` a `-13,5 %` abaixo da fronteira de calendários fixos)** — menor, porém **estatisticamente robusto (`p < 1e-4`) e em dominância estrita de Pareto** (`om_v1_T10` entrega menos doença *e* menos aplicações que `cal_12d`).
* `v2` (`ResidualGateConfig`, piso 6 d e $P_{\text{est}} \le 0,45$) atua como **outro ponto mais econômico na mesma curva de Pareto** (`5,5` vs. `6,8` aplic.), não como melhoria absoluta sobre `v1`.

---

## 3. Sensibilidade econômica (€/ha) e teto europeu de cobre ([economics.py](economics.py))

Como a inclinação da curva de dano foliar → cacho ($L = 0{,}85(1 - e^{-k\cdot\text{AACPD}})$) não foi calibrada em campo, avaliamos **126 combinações** de $k \in [0{,}0002 ; 0{,}0015]$ × receita bruta de `3.000` a `30.000 €/ha` (`55 €/ha` por aplicação) sobre o **OSSE semirreal INRAE (`N = 1.200`)**, gerando os mapas de decisão [economics_map_unconstrained.svg](data/fase2/economics_map_unconstrained.svg) e [economics_map_eu_copper.svg](data/fase2/economics_map_eu_copper.svg):

* **Sem restrição de cobre (126 células):**
  * `cal_7d` vence em **`40,5 %`** da superfície (vinhedos de alta receita + dano severo — reproduzindo o comportamento real de viticultores de vinhos premium);
  * **`om_v1_T10` vence em `27,0 %`** e **`om_v2_T10` em `19,8 %`** (total: **`46,8 %`** nas faixas intermediárias/econômicas);
  * `testemunha` vence em `12,7 %` (apenas receita mínima + dano mínimo);
  * **`cal_10d`, `cal_12d` e `cal_14d` vencem em `0,0 %` da superfície** — sempre que não se aplica semanalmente, a regra preventiva domina os calendários fixos espaçados.
* **Sob o teto europeu de cobre para viticultura orgânica — Regulamento de Execução (UE) 2018/1981 (`28 kg Cu/ha` em 7 anos = média de `4,0 kg Cu/ha/ano`):**
  * A uma dose típica de `0,50 kg Cu/ha` por aplicação, `cal_7d` (`11,0` aplic. = `5,50 kg Cu/ha/ano`) **ultrapassa o limite legal europeu**, enquanto `om_v1_T10` (`3,39 kg/ha/ano`) e `om_v2_T10` (`2,76 kg/ha/ano`) **cumprem integralmente o regulamento**.
  * Dentro do espaço conforme ao Reg. (UE) 2018/1981, **`om_v1_T10` lidera em `61,1 %`** e **`om_v2_T10` em `19,8 %`** (**`80,9 %` da superfície** contra `6,3 %` do `cal_10d`).

---

## 4. Calibração da posteriori de `r` (módulo de assimilação)
Com `r_prior_gompertz` separada em [epidemiology_assimilation.py](epidemiology_assimilation.py), a cobertura do IC 95 % de `r` dentro do modelo escolhido passou de ~75 % (mistura de escalas logística/Gompertz) para **97,9 % (logística)** e **95,8 % (Gompertz)**.

---

## 5. Como reproduzir

```powershell
# Testes automatizados (sem rede, sem banco, sem GPU)
.venv\Scripts\python.exe -m pytest tests/ -q

# 1. Validação de LWD contra sensores reais (INRAE AgroClim + Politecnico di Torino)
.venv\Scripts\python.exe lwd_sensor_validation.py

# 2. OSSE semirreal nas 4 estações INRAE (verdade = sensor) + Moselle com erro calibrado
.venv\Scripts\python.exe semireal_osse.py --lwd-method rh90_hysteresis --n-plots 50

# 3. Sensibilidade econômica e mapa de decisão sob Reg. (UE) 2018/1981
.venv\Scripts\python.exe economics.py data/fase2/semireal_inrae_osse.json \
    --out-svg-unconstrained data/fase2/economics_map_unconstrained.svg \
    --out-svg-copper data/fase2/economics_map_eu_copper.svg
```
