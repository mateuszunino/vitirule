# An Open, Reproducible Evaluation Protocol for Preventive Agrometeorological Decision Support in Grapevine Downy Mildew (*Plasmopara viticola*)

**Author:** Mateus  
**Repository:** `tomato-dss` / *Agrometeorological Evaluation Framework for Foliar Diseases*  
**Date:** November 2026  
**Code & Frozen Checkpoints:** Git commits `2e8aea8`, `68ef7fd`, `a562ccc`, `958cbe3`

---

## Abstract

Weather-driven decision support systems (DSS) for grapevine downy mildew (*Plasmopara viticola*) are widely deployed in European viticulture, yet published evaluations rarely isolate the marginal value of individual system components, guard against in-sample threshold tuning, or quantify how meteorological data-source errors propagate into spray decisions. We present an open, reproducible evaluation protocol combining: (i) an Observing System Simulation Experiment (OSSE) driven by a misspecified hourly discrete-time SEIR epidemic model incorporating a four-stage Müller-Sleumer/Goidànich latent period, rain-induced fungicide wash-off, microclimatic canopy offsets, and autocorrelated 7-day forecast errors; (ii) strictly frozen out-of-sample validation across disjoint year blocks (`2025` development, `2022–2024` selection, `2019–2021` and `2016–2018` unseen validation, and `2019–2024` semi-real sensor testing); (iii) empirical validation of four hourly leaf wetness duration (LWD) estimators against `80,392` hours of field-measured sensor data from INRAE AgroClim (France) and Politecnico di Torino (Italy); and (iv) an economic sensitivity analysis including seven-year cumulative copper accounting under Commission Implementing Regulation (EU) 2018/1981.

Four main findings emerge. First, in a frozen four-arm equal-budget ablation across `360` out-of-sample plot-seasons (`Moselle` and `Bordeaux`, `2022–2024`), closed-loop Bayesian assimilation of foliar severity added no statistically significant benefit over a purely weather-driven preventive rule using 7-day forecasts and rain wash-off tracking (`Δ AUDPC = +0.99`, 95% bootstrap CI `[-1.81, +3.91]`, paired Wilcoxon `p = 0.462`). Second, against real LWD sensors, all four empirical estimators performed comparably when fed operational Open-Meteo reanalysis (`F1 = 0.58–0.61`, daily `MAE = 3.82–4.30 h/day`), whereas switching from on-station meteorology to reanalysis increased daily LWD error by `+1.21` to `+1.48 h/day` with a `+1.6 h/day` wet bias; thus, the meteorological data source dominated estimation error over the choice of LWD formula. Third, in a semi-real OSSE where the SEIR epidemic was driven directly by real INRAE LWD sensors (`N = 1,200` plot-seasons across four French wine regions) while the frozen rule read only Open-Meteo reanalysis, pooled Pareto dominance survived (`-18.95` AUDPC below the interpolated fixed-calendar frontier, `-13.5%`, `p < 1e-6`), shrinking sharply from `-101.6` AUDPC in purely reanalysis-driven simulations. Crucially, per-cohort decomposition revealed that within individual seasons the rule sat on the fixed-calendar frontier (median `-3.37`, mean `+1.00`, below the curve in `14/24` cohorts), demonstrating that **the pooled gain comes from inter-annual campaign sizing** (`r = 0.595`, `p = 0.0022` between spray count and untreated epidemic pressure), **not from superior within-season spray timing**. Moreover, two severe tail-risk failures occurred (`Champagne 2022`: `+77.3` AUDPC / `+56.8%` worse than the frontier; `Bordeaux 2021`: `+52.9` / `+14.7%`), and feeding on-station weather did not outperform reanalysis at the frozen threshold (`-15.99` vs. `-18.95` AUDPC), likely because the threshold had absorbed reanalysis wet bias. Fourth, economic sensitivity mapping showed that fixed 7-day calendars remained optimal in unconstrained high-value vineyards (`40.5%` of the parameter space), whereas under EU 7-year cumulative copper limits (`28 kg Cu/ha` over 7 years) the preventive rules dominated at doses of `0.40–0.50 kg Cu/ha/spray`, though compliance depended sensitively on dose and regional disease pressure.

### Resumo (Português)

Este relatório apresenta uma metodologia aberta e reprodutível para avaliar regras agrometeorológicas preventivas contra o míldio da videira (*Plasmopara viticola*), e não um novo produto comercial concorrente de sistemas operacionais como VitiMeteo ou RIMpro. Os resultados principais são quatro: (1) em ablação fora da amostra congelada em commit (`N = 360`), a assimilação bayesiana da severidade foliar não acrescentou ganho sobre a decisão preventiva baseada em previsão de 7 dias e lavagem por chuva (`Δ AACPD = +0,99`, `p = 0,462`); (2) contra `80.392` horas de sensores reais de molhamento foliar (INRAE AgroClim e Politecnico di Torino), os quatro estimadores empataram na entrada operacional Open-Meteo (`MAE = 3,8–4,3 h/d`) e a fonte climática dominou o erro (`+1,2` a `+1,5 h/d` ao sair da estação para reanálise); (3) em OSSE semirreal movido pelo sensor real do INRAE (`N = 1.200`), a dominância de Pareto consolidada sobreviveu (`-18,95` AACPD, `-13,5 %`), mas a análise por coorte mostrou que o ganho vem de **dimensionar o número anual de aplicações** conforme a pressão da safra (`r = 0,595`), não de acertar melhor o momento dentro de uma mesma safra — com falhas severas em `Champagne 2022` (`+56,8 %`) e `Bordeaux 2021` (`+14,7 %`); e (4) sob o teto europeu acumulado de cobre (**Regulamento (UE) 2018/1981**, `28 kg Cu/ha` em 7 anos), a viabilidade econômica e regulatória depende fortemente da receita do vinhedo e da dose de cobre por aplicação (`0,30–0,60 kg Cu/ha`).

---

## 1. Introduction

Grapevine downy mildew, caused by the obligate biotrophic oomycete *Plasmopara viticola*, is the primary foliar and cluster disease threatening viticulture across temperate humid Europe, including the Moselle Valley (Luxembourg and Germany), Bordeaux, Alsace, Champagne, and Burgundy (Gessler et al., 2011; Rossi et al., 2008). Under favorable warm and wet conditions during spring and summer, polycyclic secondary infection cycles can complete incubation in as little as four days, causing severe inflorescence and young-berry destruction if protective fungicide coverage fails.

To avoid catastrophic crop losses, conventional and organic winegrowers frequently rely on fixed-interval calendar spraying—typically every 7 to 14 days from shoot elongation through veraison. Calendar schedules are operationally simple and insure against unexpected infection events, but they are structurally blind to inter-annual climate variability: they over-apply fungicides in dry seasons and risk under-protecting canopies during prolonged rainfall periods when contact fungicides wash off. In the European Union, reducing unnecessary fungicide applications is not only an economic or environmental preference; in certified organic viticulture, copper compounds remain the backbone of *P. viticola* control and are legally capped at **28 kg of metallic copper per hectare over a 7-year period** under Commission Implementing Regulation (EU) 2018/1981 (an average of `4.0 kg Cu/ha/year` with inter-annual smoothing).

Operational agrometeorological decision support systems already exist to address this problem. Platforms such as **VitiMeteo** (*VitiMeteo-Plasmopara*, developed by Agroscope and WBI Freiburg and deployed operationally across Luxembourg's Moselle region, Germany, Switzerland, and eastern France) and **RIMpro** integrate local weather stations, leaf wetness, and mechanistic pathogen sub-models to guide spray timing. Building yet another commercial forecasting platform is neither necessary nor realistic for a single-researcher open-source project.

Instead, the contribution of this work is **an open, reproducible evaluation protocol** for testing agrometeorological spray rules before field trials. Published DSS papers frequently evaluate rules on the same years used for threshold tuning, omit equal-budget ablations that separate weather-forecast skill from biological sub-models, rely on unvalidated reanalysis-derived leaf wetness, or report only pooled spray savings without tail-risk failure cases or economic sensitivity. Here, we implement and execute a strict verification pipeline—including a documented negative result on closed-loop severity assimilation, real-sensor validation of leaf wetness duration (LWD), semi-real OSSE robustness testing, per-cohort Pareto decomposition, and multi-parameter economic sensitivity—where every hypothesis freeze is auditable via Git commit history.

---

## 2. Methods

### 2.1 System Scope and Frozen-Rule Protocol

The project originally explored a closed-loop architecture linking foliar severity measurements to Bayesian epidemiological assimilation (`epidemiology_assimilation.py`, logistic/Gompertz curves in physiological favorable-day time $\tau$) and computer vision (`vision_pipeline.py`). Following the negative ablation result reported in Section 3.1, the active protocol focused on preventive weather-driven rules (*Path A*), while retaining the assimilation and vision modules disabled by default (with a separate Gompertz rate prior `r_prior_gompertz` added to fix cross-model scale mixing in posterior rate coverage; Section 5).

To prevent in-sample overfitting and post-hoc threshold tuning ("p-hacking across weather years"), every rule change was frozen in a Git commit **before** executing the corresponding evaluation set. Each historical year block served a single, non-overlapping methodological role (Table 1).

**Table 1.** Strict separation of historical weather years, regions, and Git checkpoints across study phases.

| Study Phase | Years | Regions / Stations | Sample Size (`N` plot-seasons) | Role | Frozen Commit |
|---|---|---|---:|---|---|
| Initial prototyping & calibration | `2025` | Moselle (LU), Bordeaux (FR) | 16 | Rule design & initial threshold calibration | Pre-freeze |
| Four-arm equal-budget ablation | `2022–2024` | Moselle (LU), Bordeaux (FR) | 360 (`60 × 2 × 3`) | Out-of-sample test of severity assimilation (`d` vs. `c`) | `2e8aea8` |
| Pareto frontier description | `2022–2024` | Moselle (LU), Bordeaux (FR) | 360 (`60 × 2 × 3`) | Operating-point selection (`T = 10.0`) on fixed-calendar frontier | `68ef7fd` |
| Out-of-sample Pareto validation #1 | `2019–2021` | Moselle, Bordeaux, **Alsace (new)** | 540 (`60 × 3 × 3`) | Unseen temporal & spatial validation (`cart_kim2002`) | `68ef7fd` |
| LWD empirical sensor validation | `2022–2024` (INRAE); `2022–2024` (Polito) | 4 INRAE French vineyards; 7 Polito Italian sites | `80,392` real hours | Empirical benchmark of 4 LWD models (station vs. Open-Meteo) | `a562ccc` |
| Out-of-sample Pareto validation #2 | `2016–2018` | Moselle, Bordeaux, Alsace | 540 (`60 × 3 × 3`) | Untouched years with sensor-best station formula (`rh90_hysteresis`) | `a562ccc` |
| Semi-real sensor OSSE | `2019–2024` (split `19–21` vs. `22–24`) | 4 INRAE stations (Bordeaux, Alsace, Champagne, Bourgogne) | 1,200 (`50 × 4 × 6`) | Robustness under **real measured LWD sensor truth** (no rule edits) | `958cbe3` |
| Calibrated-error Moselle test | `2016–2018` | Moselle (LU) | 180 (`60 × 1 × 3`) | Sensor-less region with empirical AR(1) reanalysis wetness error | `958cbe3` |

### 2.2 Misspecified Mechanistic SEIR Ground-Truth Generator

To avoid the *inverse crime* of generating synthetic epidemics with the same logistic/Gompertz equations fitted by the assimilation module, ground-truth vineyard epidemics were generated by an hourly discrete-time compartmental **SEIR model** (`osse_benchmark.py`) over a 75-day growing window (`May 1` to `July 15`, with meteorological context through `August 5` for 7-day forecasts):

1. **Compartmental structure and incubation delay:** Susceptible leaf area $S$ enters a four-stage Erlang exposed pipeline $(E_1, \dots, E_4)$ before transitioning into infectious sporulating lesions $I$ (infectious duration `12 days`) and removed necrotic tissue $R$. Visible foliar severity is $100 \times (I + R)$, so new infections remain invisible throughout incubation. Stage progression follows piecewise linear interpolation of the published Müller-Sleumer/Goidànich temperature-incubation curve (`25.0%/day` at `22–25 °C` [4 days], `7.7%/day` at `12 °C` [~13 days], `0%/day` outside `[8, 30] °C`).
2. **Deliberate parameter misspecification and decoupling:** Plot-level true parameters were drawn independently per plot to break alignment with the rule and assimilation defaults: maximum infection rate $\beta_{\max} \sim 0.055 \cdot \exp(\mathcal{N}(0, 0.25^2))$, initial latent inoculum $E_1(0) \sim \text{clip}(0.0025 \cdot \exp(\mathcal{N}(0, 0.45^2)), 0.0004, 0.018)$, shifted thermal cardinals ($\Delta T_{\min} \sim \mathcal{N}(0, 1.2^2)$, $\Delta T_{\text{opt}} \sim \mathcal{N}(0, 1.5^2)$ °C), real protectant efficacy $E_{\text{true}} \sim \text{clip}(\mathcal{N}(0.76, 0.08^2), 0.55, 0.92)$ (vs. `0.60` in assimilation), and half-life $t_{1/2,\text{true}} \sim \text{clip}(\mathcal{N}(5.5, 1.2^2), 3.5, 9.0)$ days (vs. `7.0` days).
3. **Rain wash-off (decoupled from the decision rule):** Cumulative rainfall $R_{\text{since}}$ since the last spray exponentially washes off active fungicide protection via $P(t) = E_{\text{true}} \cdot 0.5^{\Delta t / t_{1/2,\text{true}}} \cdot 0.5^{R_{\text{since}} / W_{\text{true}}}$, with plot-specific $W_{\text{true}} \sim \text{clip}(\mathcal{N}(25, 8^2), 12, 48)$ mm—deliberately decoupled from the fixed `15 mm` wash-off override in rule `v1` and the `30 mm` residual gate in rule `v2`.
4. **Autocorrelated 7-day forecast error:** Every 3-day decision step received a 168-hour forecast perturbed with AR(1) errors ($\phi = 0.85$) whose standard deviation grew linearly with lead time (`0.5 → 2.5 °C` in temperature, `3 → 12%` in relative humidity, and `20%` lognormal wind noise). All arms evaluated on the same plot received identical perturbed forecast realizations.
5. **Canopy wetness truth:** In purely simulated OSSEs (`2022–2024`, `2019–2021`, `2016–2018`), canopy wetness was perturbed with microclimatic dew-point depression shifts ($\mathcal{N}(-0.35, 0.40^2)$ °C) and wind shelter ($\mathcal{N}(0.65, 0.12^2)$). In the **semi-real INRAE OSSE** (`semireal_osse.py`), true temperature, rainfall, and hourly leaf wetness $h \in [0, 1]$ were taken **directly from the INRAE field station and its physical LWD sensor**, completely eliminating synthetic wetness generation. For sensor-less Moselle (`2016–2018`), an empirical AR(1) wetness-error generator calibrated to the INRAE Open-Meteo discrepancies (Section 3.2) replaced the small microclimate perturbation.

### 2.3 Leaf Wetness Estimators and Real-Sensor Validation

Four hourly LWD estimators were implemented in `leaf_wetness.py` (all classifying precipitation $\ge 0.1\text{ mm/h}$ as wet):
1. **`rh85`**: simple threshold $\text{RH} \ge 85\%$;
2. **`rh90_hysteresis`** (after Sentelhas et al., 2008): onset at $\text{RH} \ge 90\%$ (with solar radiation $< 150\text{ W/m}^2$ when available), drying when $\text{RH} < 80\%$ or solar radiation $> 250\text{ W/m}^2$ with $\text{RH} < 92\%$;
3. **`dpd_hysteresis`** (Gillespie et al., 1993; Gleason et al., 1994; Sentelhas et al., 2008): dew-point depression $\text{DPD} = T - T_d \le 1.8\,^\circ\text{C}$ for onset, drying at $\text{DPD} \ge 3.8\,^\circ\text{C}$ (or $\text{DPD} \ge 2.2\,^\circ\text{C}$ under $> 250\text{ W/m}^2$);
4. **`cart_kim2002`** (Kim et al., 2002, *Plant Disease* 86:179–185): four-category Classification and Regression Tree / Stepwise Linear Discriminant (CART/SLD) model using $T$, $\text{RH}$, $\text{DPD}$, and canopy-adjusted wind speed (FAO-56 Eq. 47 scaling 10 m Open-Meteo wind to 2 m).

Validation (`lwd_sensor_validation.py`) used two independent open field networks during the April–September growing season:
* **INRAE AgroClim** (DOI `10.57745/BQ0BWB`; Furusho-Percot et al., *Data in Brief* 2025, `PMC12266558`): four French viticultural research stations—Bordeaux-Couhins (`33080002`, `44.753°N, -0.561°E`), Alsace-Colmar (`68066002`, `48.064°N, 7.330°E`), Champagne-Fagnières (`51242002`, `48.950°N, 4.314°E`), and Bourgogne-Bretenière (`21106002`, `47.239°N, 5.102°E`)—yielding `52,675` valid hourly observations (`2022–2024`), with hourly sensor duration `h >= 0.5` defining a wet hour.
* **Politecnico di Torino / iXem Labs** (Mendeley Data, DOI `10.17632/sd4b8vpvyb.1`): seven Italian sites with double-sided capacitive sensors (`27,717` hours; `23,735` hours across six clean sites after flagging `site2.csv`, which reported `99.9% > 0` readings consistent with sensor baseline drift), binarized at `leaf_top >= 20`.

Each estimator was evaluated twice on the exact same timestamps: **(A) on-station measured meteorology** (`T, RH, wind, rain, radiation` at 2 m) and **(B) Open-Meteo Archive ERA5 reanalysis** fetched at the exact station coordinates. The difference `(B) - (A)` isolates the reanalysis error penalty.

### 2.4 Decision Rules, Ablation Arms, and Pareto Evaluation

Daily *P. viticola* risk indices (`downy_mildew.py`) computed in 12h–12h local windows comprise Baldacci's 3-10 primary infection trigger ($T_{\text{mean}} \ge 10\,^\circ\text{C}$, 48 h rain $\ge 10\text{ mm}$, shoots $\ge 10\text{ cm}$) and a `0–4` secondary infection severity index (`secondary_sv`) driven by LWD, wet-period temperature, and nocturnal sporulation.

1. **Four-arm equal-budget ablation (`2022–2024`, `osse_benchmark.py`):** Each plot was run under `(d) closed_loop_dss` (forecast + 15 mm wash-off + Bayesian assimilation triggers `delta_y_7d`, `p_exceed`, `regime_change`), obtaining spray count $N_d$. Three controls matched $N_d$: `(a) uniform_calendar` (exact $N_d$ evenly spaced sprays), `(b) climate_reactive` (past 7-day observed climate only, causal threshold matched to $N_d$), and `(c) climate_forecast_washoff` (identical forecast, dry-week block, and 15 mm wash-off mechanics as `(d)`, **without assimilation**, causal threshold matched to $N_d$). All pairwise differences in AUDPC (`% × day`, trapezoidal rule cross-checked against R to `< 1e-6`) were evaluated via `B = 5,000` bootstrap 95% CIs and two-sided paired Wilcoxon signed-rank tests.
2. **Pareto frontier (`pareto_analysis.py`):** Because an equal-budget uniform calendar implicitly receives oracle knowledge of how many sprays a season requires, real-world policy comparison places practical **fixed calendars chosen before the season** (`cal_7d` [11 sprays], `cal_10d` [8], `cal_12d` [7], `cal_14d` [6]) against preventive forecast rules on the `(mean sprays, mean AUDPC)` plane. Two frozen variants at threshold `T = 10.0` (selected on `2022–2024` development data) were tested without modification:
   * **`v1_T10`**: `7-day` minimum interval reduced to `4 days` after `>= 15 mm` rain; sprays when `sv_fc_7d + 0.5 * sv_fc_3d >= 10.0` (or primary 3-10 before first spray) with active incoming risk (`sv_fc_7d >= 3` or `sv_fc_3d >= 2`).
   * **`v2_T10`**: replaces the binary `4-day / 15 mm` rule with a continuous residual-coverage gate requiring `days_since >= 6.0` and $P_{\text{est}} = 0.5^{\Delta t / 7.0} \cdot 0.5^{R_{\text{since}} / 30.0} \le 0.45$, designed as a more economical operating point that avoids 4-day spray clustering.

### 2.5 Economic Damage Function and 7-Year EU Copper Accounting

Because foliar AUDPC does not directly equal financial loss (downy mildew causes economic loss primarily via cluster infection), we parameterized a saturating exponential bunch-damage curve (`economics.py`; Madden et al., 2007):

$$L(\text{AUDPC}) = L_{\max}\left(1 - e^{-k \cdot \text{AUDPC}}\right), \qquad \text{Net Return (€/ha)} = G \cdot (1 - L) - N_{\text{sprays}} \cdot C_{\text{spray}}$$

with $L_{\max} = 0.85$ and $C_{\text{spray}} = 55\text{ €/ha}$ (product, tractor, and labor). **Crucially, $k$ is not field-calibrated in this study.** Therefore, instead of relying on a single assumed slope, we swept a **126-cell sensitivity surface** over $k \in [0.0002, 0.0015]$ per AUDPC unit and gross grape revenue $G \in [3{,}000;\, 30{,}000]\text{ €/ha}$.

Regulatory compliance under **Commission Implementing Regulation (EU) 2018/1981** was modeled as the actual **7-year cumulative cap (`<= 28 kg Cu/ha` over 7 years)** rather than a rigid `4 kg/year` annual ceiling, projecting each INRAE station's 6-year empirical spray total (`2019–2024`) to a 7-year window ($\sum_{6\text{y}} \times 7/6$) across four sensitivity doses per application: **`0.30, 0.40, 0.50, and 0.60 kg Cu/ha/spray`**.

---

## 3. Results

### 3.1 Negative Result: Severity Assimilation Adds No Value Over Preventive Weather Rules (`d` vs. `c`)

In the frozen out-of-sample four-arm ablation across Moselle and Bordeaux (`2022–2024`, `N = 360` plot-seasons, commit `2e8aea8`), **closed-loop Bayesian assimilation of foliar severity failed to outperform the identical weather-forecast + wash-off rule without assimilation** (Table 2).

**Table 2.** Frozen out-of-sample four-arm ablation (`2022–2024`, Moselle & Bordeaux, `N = 360`, commit `2e8aea8`). Negative `Δ AUDPC` favors the first arm.

| Ablation Arm / Contrast | Mean Sprays | Mean AUDPC (SD) | Final Sev. (%) | Paired Δ AUDPC `[95% Boot CI]` | Wilcoxon `p` | Wins |
|---|---:|---:|---:|---|---:|---:|
| `(0) testemunha` (untreated) | 0.00 | 1004.98 (903.11) | 50.02 | — | — | — |
| `(a) uniform_calendar` (oracle equal-`N`) | 8.56 | 405.71 (480.58) | 23.13 | — | — | — |
| `(b) climate_reactive` (observed past only) | 7.77 | 474.54 (561.45) | 26.71 | — | — | — |
| `(c) climate_forecast_washoff` (no assim.) | 8.56 | 429.87 (518.53) | 24.09 | — | — | — |
| `(d) closed_loop_dss` (full assimilation) | 8.56 | 430.85 (513.14) | 24.12 | — | — | — |
| `(e) weekly_calendar` (fixed 7-day) | 11.00 | 386.18 (481.62) | 21.67 | — | — | — |
| **Main test: `(d) − (c)` (assimilation value)** | **0.00** | — | — | **`+0.99 [-1.81, +3.91]`** | **0.4618** | **141/360** *(106 ties)* |
| Forecast value: `(c) − (b)` | +0.79 | — | — | `-44.68 [-51.40, -37.91]` | `< 1e-6` | 293/360 |
| Oracle equal-`N`: `(d) − (a)` | 0.00 | — | — | `+25.14 [+19.02, +31.49]` | `< 1e-6` | 121/360 |
| Trade-off vs. weekly: `(c) − (e)` | `-2.44 (-22.2%)` | — | — | `+43.69 [+38.09, +49.40]` | `< 1e-6` | — |

The biological mechanism is straightforward: protectant fungicides block *new* infections entering $E_1$, not already-incubating latent lesions. Because visible symptoms lag infection by the 4–13 day Goidànich incubation period, reactive triggers derived from assimilated foliar severity (`delta_y_7d`, `p_exceed`, `regime_change`) acted too late in intermittent years (`2022`, where `(c)` beat `(d)` by `14.6` to `18.4` AUDPC) and provided only marginal adjustments in severe wet years (`Bordeaux 2023`, `Moselle 2024`), canceling out to a statistical tie (`p = 0.462`). Even in a favorable simulation environment without video-segmentation errors, severity assimilation did not justify its operational monitoring cost.

### 3.2 Real-Sensor LWD Validation: Estimators Tie on Reanalysis; Data Source Dominates Error

Validation across `80,392` real hourly sensor observations (Table 3) overturned our initial assumption that Kim et al.'s CART model (`cart_kim2002`) was superior, and exposed a much larger meteorological bottleneck.

**Table 3.** Hourly LWD estimator performance against real sensors in French (INRAE AgroClim, `2022–2024` Apr–Sep) and Italian (Politecnico di Torino, Apr–Sep) networks, fed either on-station measured weather or Open-Meteo ERA5 reanalysis at the identical coordinates.

| Network (`N` hours) | Estimator | Station: Acc / F1 / CSI / MAE (h/d) / Bias | Open-Meteo: Acc / F1 / CSI / MAE (h/d) / Bias | Reanalysis Penalty (Δ MAE) |
|---|---|---|---|---:|
| **INRAE AgroClim FR** (`52,675 h`, 4 vineyards) | `rh90_hysteresis` | **0.864 / 0.732 / 0.581 / 2.61 / +0.97** | **0.779** / 0.604 / 0.434 / 4.07 / +2.17 | `+1.46 h/d` |
| | `dpd_hysteresis` | 0.859 / 0.731 / 0.580 / 2.76 / +1.31 | 0.776 / **0.608 / 0.438** / 4.24 / +2.46 | `+1.48 h/d` |
| | `rh85` | 0.831 / 0.693 / 0.533 / 3.26 / +1.95 | 0.761 / 0.589 / 0.419 / 4.30 / +2.71 | `+1.04 h/d` |
| | `cart_kim2002` | 0.828 / 0.675 / 0.513 / 3.25 / +1.52 | 0.772 / 0.577 / 0.407 / **3.82** / +1.66 | `+0.57 h/d` |
| **Polito IT** (`23,735 h`, 6 clean sites) | `rh85` | **0.879 / 0.680 / 0.519 / 2.59 / -0.07** | 0.789 / **0.529 / 0.364 / 4.05** / +1.49 | `+1.46 h/d` |
| | `dpd_hysteresis` | 0.871 / 0.653 / 0.490 / 2.79 / -0.36 | 0.788 / 0.519 / 0.354 / 4.13 / +1.27 | `+1.34 h/d` |
| | `rh90_hysteresis` | 0.869 / 0.636 / 0.472 / 2.85 / -0.70 | **0.791** / 0.516 / 0.351 / 4.06 / +1.05 | `+1.21 h/d` |
| | `cart_kim2002` | 0.861 / 0.672 / 0.513 / 2.95 / +1.15 | 0.779 / 0.507 / 0.343 / 4.28 / +1.40 | `+1.33 h/d` |

Two conclusions stand out:
1. **On operational Open-Meteo input, the four estimators effectively tie and trade rankings across metrics:** in INRAE vineyards, `dpd_hysteresis` leads in `F1` (`0.608`), `rh90_hysteresis` in accuracy (`0.779`), and `cart_kim2002` in daily `MAE` (`3.82 h/day`). On station weather, `cart_kim2002` actually ranked **last** in both France and Italy.
2. **Meteorological data source dominates estimation error:** replacing local station observations with Open-Meteo reanalysis degraded `F1` by `~0.13`, increased daily `MAE` from `~2.6` to `~4.0 h/day`, and introduced a persistent wet bias (`+1.59 h/day` across `70,537` May–August INRAE hours; hourly lag-1 error autocorrelation `0.676`; $P(\text{sensor wet} \mid \text{OM wet}) = 0.532$). This reanalysis penalty (`+1.2` to `+1.5 h/day`) was more than double the spread across formulas on station data (`0.65 h/day`).

### 3.3 Pareto Frontier: Pooled Gain vs. Per-Cohort Reality (Inter-Annual Sizing, Not Within-Season Timing)

Across purely simulated out-of-sample blocks (`2019–2021` with `cart_kim2002`, `N = 540`; `2016–2018` with `rh90_hysteresis`, `N = 540`), the frozen operating point `T = 10.0` sat substantially below the fixed-calendar Pareto frontier (`-37.1` AUDPC in `2019–2021`; `-101.6` AUDPC in `2016–2018`, `p < 1e-6`). However, as predicted from Section 3.2, those purely simulated gains were inflated by the optimistic coupling between reanalysis-derived canopy truth and reanalysis rule input.

When the SEIR epidemic was driven directly by **real INRAE physical LWD sensors** (`semireal_osse.py`, 4 French vineyard stations × 6 years `2019–2024`, `N = 1,200` plot-seasons) while the frozen rule saw only Open-Meteo reanalysis (`om_v1_T10`, `om_v2_T10`), untreated epidemic pressure fell to realistic levels (`284.7` AUDPC) and the pooled Pareto advantage shrank from `-101.6` to **`-18.95` AUDPC (`-13.5%` below the interpolated frontier)**—still statistically robust (`p < 1e-6`, `814/1,200` wins over `cal_12d` with `0.23` fewer sprays; Table 4). Both the strictly unseen `2019–2021` subset (`-13.50` AUDPC, `N = 600`) and the `2022–2024` selection-year subset (`-19.51` AUDPC, `N = 600`) preserved pooled dominance, as did the calibrated-error Moselle test (`2016–2018`, `N = 180`: `-22.70` AUDPC below the frontier, `p = 4.7e-5`).

**Table 4.** Semi-real INRAE sensor-truth OSSE (pooled `2019–2024` and split into unseen `2019–2021` vs. selection years `2022–2024`) and calibrated-error Moselle (`2016–2018`). Rule frozen at `T = 10.0` (`rh90_hysteresis`).

| Experiment / Subset | Strategy | Sprays | AUDPC `[95% CI]` | Δ vs. Calendar Frontier | Paired vs. Closest Calendar (`p`) |
|---|---|---:|---:|---:|---|
| **INRAE Semi-Real Pooled** (`N = 1,200`, 24 cohorts) | `cal_7d` / `10d` / `12d` / `14d` | 11 / 8 / 7 / 6 | 95.5 / 118.5 / 138.6 / 146.5 | ref. | — |
| | **`om_v1_T10`** (Open-Meteo only) | **6.77** | **121.42 `[112.5, 130.9]`** | **-18.95 (-13.5%)** | `-17.15` vs `cal_12d` (`-0.23` sp, `< 1e-6`) |
| | `om_v2_T10` (economical point) | 5.51 | 137.31 `[126.9, 148.2]` | below `cal_14d` | `-9.18` vs `cal_14d` (`-0.49` sp, `< 1e-6`) |
| | `st_v1_T10` (INRAE station, no LWD) | 6.38 | 127.48 `[117.8, 137.7]` | -15.99 (-11.1%) | `-19.01` vs `cal_14d` (`+0.38` sp, `< 1e-6`) |
| **INRAE Unseen `2019–2021`** (`N = 600`, 12 cohorts) | `cal_12d` / `cal_14d` | 7 / 6 | 127.69 / 134.53 | ref. | — |
| | **`om_v1_T10`** | **6.25** | **119.32** | **-13.50 (-10.2%)** | — |
| | `st_v1_T10` | 6.09 | 123.14 | -10.78 (-8.1%) | — |
| **INRAE Selection Yrs `2022–2024`** (`N = 600`, 12 cohorts) | `cal_12d` / `cal_14d` | 7 / 6 | 149.45 / 158.46 | ref. | — |
| | **`om_v1_T10`** | **7.30** | **123.53** | **-19.51 (-13.6%)** | — |
| | `st_v1_T10` | 6.67 | 131.82 | -20.56 (-13.5%) | — |
| **Moselle Calibrated Error** (`2016–2018`, `N = 180`) | `cal_12d` / `cal_14d` | 7 / 6 | 302.1 / 367.6 | ref. | — |
| | **`om_v1_T10`** | **7.22** | **277.37 `[243.1, 315.9]`** | **-22.70 (-7.6%)** | `-24.70` vs `cal_12d` (`p = 4.7e-5`, 120/180) |
| | `om_v2_T10` | 5.83 | 346.54 `[303.6, 394.1]` | below `cal_14d` | `-21.03` vs `cal_14d` (`p = 0.021`, 99/180) |

**Per-cohort decomposition reveals the true mechanism (Table 5):** when the distance from `om_v1_T10` to the fixed-calendar curve is computed **separately within each of the 24 station-years**, the rule sits virtually **on top of the calendar frontier**: mean difference **`+1.00` AUDPC**, median **`-3.37` AUDPC**, below the frontier in only **`14/24` cohorts** (and for `st_v1_T10`: mean `+1.07`, median `-0.99`, `15/24` below).

Why does a `-18.95` AUDPC pooled gain appear when the within-season mean gain is `+1.00`? Because **`om_v1_T10`'s annual spray count correlates strongly with untreated epidemic pressure (`Pearson r = 0.595, p = 0.0022`)**, ranging from `2.44` sprays in dry `Bourgogne 2019` (`test = 113.6`) to `10.28–11.66` sprays in wet `Bordeaux 2024` / `Alsace 2024` (`test = 563–598`). A fixed calendar spends the exact same budget every year, wasting sprays in low-pressure seasons and under-protecting severe ones. Pooling across seasons therefore captures the real operational value of a multi-year policy—**sizing each year's spray campaign appropriately**—even though **within a given season, the rule's timing is no better than an evenly spaced calendar of the same spray count**.

**Table 5.** Per-cohort semi-real INRAE results (`24` station-years, `N = 50` plots each; `Δ` = `om_v1_T10` minus interpolated/extrapolated fixed-calendar frontier).

| Station | Year | Untreated AUDPC | `om_v1` Sprays | `om_v1` AUDPC | Frontier AUDPC | `Δ` AUDPC (`%`) | `st_v1` Sprays (`Δ`) |
|---|---:|---:|---:|---:|---:|---:|---:|
| Bordeaux (Couhins) | 2019 | 357.3 | 7.26 | 146.4 | 164.4 | -18.0 (-11.0%) | 7.50 (-10.6) |
| Bordeaux (Couhins) | 2020 | 545.5 | 8.20 | 219.8 | 214.7 | +5.1 (+2.4%) | 7.26 (+1.0) |
| **Bordeaux (Couhins)** | **2021** | **782.0** | **8.32** | **413.2** | **360.3** | **+52.9 (+14.7%)** | **7.94 (+51.8)** |
| Bordeaux (Couhins) | 2022 | 281.7 | 6.36 | 103.7 | 119.2 | -15.5 (-13.0%) | 6.00 (-20.6) |
| Bordeaux (Couhins) | 2023 | 864.3 | 9.80 | 243.2 | 259.1 | -15.9 (-6.1%) | 8.58 (+7.0) |
| Bordeaux (Couhins) | 2024 | 563.1 | 10.28 | 188.8 | 182.7 | +6.1 (+3.4%) | 9.04 (-20.6) |
| Alsace (Colmar) | 2019 | 103.0 | 5.86 | 56.8 | 64.6 | -7.8 (-12.1%) | 6.34 (-4.8) |
| Alsace (Colmar) | 2020 | 139.3 | 5.96 | 65.3 | 75.0 | -9.7 (-13.0%) | 5.94 (-9.7) |
| Alsace (Colmar) | 2021 | 171.7 | 8.00 | 82.1 | 84.3 | -2.2 (-2.6%) | 8.22 (-0.3) |
| Alsace (Colmar) | 2022 | 168.3 | 4.00 | 92.6 | 111.1 | -18.5 (-16.7%) | 4.00 (-18.5) |
| Alsace (Colmar) | 2023 | 99.0 | 5.34 | 63.9 | 68.5 | -4.6 (-6.7%) | 4.32 (-0.4) |
| Alsace (Colmar) | 2024 | 597.9 | 11.66 | 187.3 | 183.4 | +3.9 (+2.1%) | 8.96 (-3.7) |
| Champagne (Fagnières) | 2019 | 114.0 | 4.18 | 61.6 | 50.8 | +10.8 (+21.3%) | 3.88 (+15.3) |
| Champagne (Fagnières) | 2020 | 98.0 | 4.68 | 62.7 | 58.1 | +4.6 (+7.9%) | 4.26 (+6.3) |
| Champagne (Fagnières) | 2021 | 322.3 | 6.66 | 123.3 | 135.9 | -12.6 (-9.3%) | 7.60 (-0.4) |
| **Champagne (Fagnières)** | **2022** | **450.5** | **4.00** | **213.3** | **136.1** | **+77.3 (+56.8%)** | **4.24 (+66.8)** |
| Champagne (Fagnières) | 2023 | 77.6 | 4.50 | 54.2 | 64.8 | -10.7 (-16.5%) | 4.26 (-9.1) |
| Champagne (Fagnières) | 2024 | 223.5 | 9.26 | 85.3 | 85.7 | -0.3 (-0.4%) | 8.40 (+2.4) |
| Bourgogne (Bretenière) | 2019 | 113.6 | 2.44 | 74.8 | 83.8 | -9.0 (-10.7%) | 2.64 (-8.1) |
| Bourgogne (Bretenière) | 2020 | 76.3 | 5.38 | 52.1 | 50.8 | +1.2 (+2.4%) | 4.36 (+1.6) |
| Bourgogne (Bretenière) | 2021 | 157.7 | 8.06 | 73.8 | 69.5 | +4.3 (+6.2%) | 7.12 (-1.6) |
| Bourgogne (Bretenière) | 2022 | 210.9 | 5.86 | 102.5 | 115.4 | -13.0 (-11.3%) | 5.86 (-13.0) |
| Bourgogne (Bretenière) | 2023 | 125.4 | 5.68 | 73.0 | 84.6 | -11.7 (-13.8%) | 6.16 (-13.3) |
| Bourgogne (Bretenière) | 2024 | 189.8 | 10.82 | 74.7 | 67.4 | +7.2 (+10.7%) | 10.28 (+8.4) |

![Pareto Frontier 2022–2024](../data/fase2/pareto_dev_2022_2024.svg)

### 3.4 Tail-Risk Failure Cases Hidden by Pooled Averages

Pooled statistics conceal asymmetric downside risk that matters deeply for grower adoption. Two cohorts in Table 5 experienced major control failures (Table 6).

**Table 6.** Severe tail-risk failure cohorts in the semi-real INRAE sensor OSSE (`N = 50` plots per cohort).

| Cohort | Untreated Pressure (AUDPC) | `om_v1_T10` Sprays | `om_v1_T10` AUDPC | Frontier AUDPC | Excess AUDPC (`%`) | `st_v1_T10` Excess (`%`) | Failure Mode |
|---|---:|---:|---:|---:|---:|---:|---|
| **Champagne 2022** | 450.5 | 4.00 | 213.3 | 136.1 | **+77.3 (+56.8%)** | +66.8 (+47.3%) | Under-sprayed a deceptive mid/late epidemic burst (`4.0` sprays) |
| **Bordeaux 2021** | 782.0 | 8.32 | 413.2 | 360.3 | **+52.9 (+14.7%)** | +51.8 (+14.0%) | Wet-year spray clustering left unprotected gaps during intense rain |

Notably, **both failures persisted even under local INRAE station weather (`st_v1_T10`: `+66.8` and `+51.8` AUDPC)**, confirming that these tail losses stem from structural vulnerabilities in the rule threshold (`T = 10` missing moderate-score multi-day events in `Champagne 2022`, and `4-day / 15 mm` clustering in `Bordeaux 2021`), not solely from reanalysis errors. In practical viticulture, losing a single heavy epidemic season easily outweighs saving 2–3 sprays in several mild seasons.

### 3.5 Local Station Weather Did Not Beat Reanalysis at the Frozen Threshold

Despite reducing daily LWD `MAE` from `4.07` to `2.61 h/day` (Table 3), feeding local INRAE station meteorology (`st_v1_T10`) into the frozen rule yielded **`-15.99` AUDPC** below the frontier (`6.38` sprays, `127.48` AUDPC), slightly *less* than Open-Meteo (`om_v1_T10`: `-18.95` AUDPC, `6.77` sprays, `121.42` AUDPC), with virtually identical per-cohort behavior (mean `+1.07` vs. `+1.00`).

The likely explanation is **threshold–bias coupling**: `T = 10.0` was selected on Open-Meteo reanalysis (`2022–2024`), which has a `+1.6` to `+2.2 h/day` wet bias. When cleaner, drier station data replaced reanalysis without recalibrating `T`, the rule fired `0.39` fewer sprays per season (`6.38` vs. `6.77`), shifting slightly left on the Pareto curve (and losing protection in wet `Bordeaux 2023`, where `st_v1` dropped from `9.80` to `8.58` sprays and swung from `-15.9` to `+7.0`). Consequently, recommending local weather stations over reanalysis for *decision quality* remains a **hypothesis requiring station-specific threshold recalibration**, not an established result of the frozen test.

### 3.6 Economic Sensitivity Maps and 7-Year Cumulative EU Copper Accounting

Over the 126-cell sensitivity grid ($k \in [0.0002, 0.0015]$ × revenue `€3,000–€30,000/ha`, spray cost `€55/ha`) applied to the semi-real INRAE OSSE (`N = 1,200`):
* **Unconstrained economics** (Figure 2, top): `cal_7d` maximized net return in **`40.5%`** of parameter combinations (high grape value and/or steep bunch-damage slopes, matching observed Grand Cru grower behavior); `om_v1_T10` won **`27.0%`** and `om_v2_T10` won **`19.8%`** (combined `46.8%` across moderate/lower revenues); `testemunha` won `12.7%` (only extreme low revenue + low damage slope). **Fixed `10`, `12`, and `14`-day calendars won `0.0%` of the entire parameter space.**
* **Seven-year cumulative EU copper accounting (`<= 28 kg Cu/ha` over 7 years, Regulation (EU) 2018/1981)** with **dose per spray as a sensitivity parameter** (Table 7) reveals a far more nuanced picture than a rigid `4 kg/year` filter:

**Table 7.** Projected 7-year cumulative metallic copper load (`kg Cu/ha / 7 yr`) across the four INRAE stations (`2019–2024` scaled `× 7/6`) vs. the EU `28.0 kg/ha` 7-year legal cap (Regulation (EU) 2018/1981).

| Dose (`kg Cu/ha/spray`) | `cal_7d` (`11.0/yr`) | `cal_10d` (`8.0/yr`) | `cal_12d` (`7.0/yr`) | `cal_14d` (`6.0/yr`) | `om_v1_T10` Pooled (Worst: Bordeaux) | `om_v2_T10` Pooled (Worst: Bordeaux) | `st_v1_T10` Pooled (Worst: Bordeaux) |
|---:|---:|---:|---:|---:|---|---|---|
| **0.30** | **23.1** (OK) | 16.8 (OK) | 14.7 (OK) | 12.6 (OK) | 14.2 (17.6; **4/4** OK) | 11.6 (14.2; **4/4** OK) | 13.4 (16.2; **4/4** OK) |
| **0.40** | 30.8 (**EXCEEDS**) | **22.4** (OK) | 19.6 (OK) | 16.8 (OK) | **19.0** (23.4; **4/4** OK) | 15.4 (19.0; **4/4** OK) | 17.9 (21.6; **4/4** OK) |
| **0.50** | 38.5 (**EXCEEDS**) | **28.0** (OK) | 24.5 (OK) | 21.0 (OK) | 23.7 (**29.3**; **3/4** OK) | **19.3** (23.7; **4/4** OK) | **22.3** (27.0; **4/4** OK) |
| **0.60** | 46.2 (**EXCEEDS**) | 33.6 (**EXCEEDS**) | 29.4 (**EXCEEDS**) | **25.2** (OK) | 28.4 (**35.2**; **2/4** OK) | **23.1** (**28.4**; **3/4** OK) | 26.8 (**32.4**; **3/4** OK) |

At low modern organic doses (`0.30 kg Cu/ha`), even `cal_7d` complies (`23.1 kg/7 yr`), removing the regulatory constraint entirely. At `0.40 kg Cu/ha`, `cal_7d` exceeds `28 kg` while `om_v1_T10` complies at all `4/4` stations (and dominates `80.9%` of the copper-compliant economic grid alongside `om_v2_T10` at `0.50 kg/ha`, Figure 2 bottom). At `0.50 kg Cu/ha`, however, `om_v1_T10` exceeds `28 kg` in humid **Bordeaux** (`29.3 kg/7 yr`), where only the more economical `om_v2_T10` (`23.7 kg`) or local-station `st_v1_T10` (`27.0 kg`) stays compliant. Thus, copper regulatory compliance depends jointly on dose, regional climate, and inter-annual smoothing.

![Economic Sensitivity Map Unconstrained](../data/fase2/economics_map_unconstrained.svg)

![Economic Sensitivity Map EU Copper](../data/fase2/economics_map_eu_copper.svg)

---

## 4. Discussion and Limitations

### 4.1 Limitations (Primary Caveats)

Any interpretation of these findings must begin with five fundamental limitations:

1. **Disease progression is entirely simulated; only leaf wetness is field-measured.** While the semi-real OSSE uses authentic hourly temperature, rainfall, and physical leaf wetness sensors from four INRAE research stations, the epidemic trajectories (`SEIR`), fungicide wash-off mechanics, and AUDPC values are simulated. The direction of inter-annual campaign sizing aligns with viticulture literature, but **the exact numerical magnitudes (`-19` AUDPC, `-13.5%`, or `€/ha` deltas) are properties of the simulator, not field measurements**.
2. **No empirical validation against real vineyard epidemic curves or cluster-loss trials.** Because no paired field spray trial (treated vs. untreated plots with real *P. viticola* bunch ratings) was conducted, real-world factors—such as canopy growth dilution of protectant coverage, cultivar susceptibility differences, nozzle deposition heterogeneity, and systemic/translaminar fungicide options—are omitted.
3. **The bunch-damage function is assumed, not calibrated.** Foliar AUDPC was mapped to harvest loss via an uncalibrated saturating exponential curve $L = 0.85(1 - e^{-k\cdot\text{AUDPC}})$. Although sweeping $k$ across a `7.5×` range (`0.0002–0.0015`) bounds qualitative strategy dominance, exact financial break-even thresholds depend on phenology-specific cluster susceptibility (flowering to berry pea-size) that foliar AUDPC does not explicitly resolve.
4. **Half of the semi-real INRAE sample overlaps the operating-point selection years.** The `2019–2024` semi-real benchmark includes `2022–2024`, which were used on Open-Meteo data to pick `T = 10.0`. No parameter was adjusted during the semi-real run, and splitting out strictly unseen `2019–2021` (`N = 600`) confirmed pooled dominance (`-13.50` AUDPC vs. `-19.51` in `2022–2024`), yet full temporal independence holds strictly for the `2019–2021` half (and the `2016–2018` Moselle test).
5. **LWD sensor benchmarks carry sensor-specific calibration uncertainty.** Capacitive and resistive leaf wetness sensors differ across manufacturers and mounting heights (illustrated by `site2.csv` in Politecnico di Torino showing `99.9% > 0` readings). Furthermore, weather-station wetness sensors sit outside the vine canopy and only approximate inner-canopy microclimate.

### 4.2 Implications for Operational Agrometeorology and DSS Evaluation

Within those boundaries, this work offers three concrete lessons for agrometeorological modeling:

* **Test negative hypotheses openly:** Had we evaluated closed-loop severity assimilation only against an untreated control or a weekly calendar without an equal-budget weather-only ablation (`d` vs. `c`), the assimilation system would have appeared successful when the true driver was the 7-day forecast and rain wash-off rule.
* **Report per-cohort Pareto behavior and tail failures alongside pooled means:** Showing only pooled averages hides both *why* a rule works (inter-annual campaign sizing, `r = 0.595`, rather than superior within-season timing) and *when* it fails (`Champagne 2022`: `+56.8%` excess disease). Addressing such tail failures—not chasing marginal mean improvements—is the primary barrier to grower adoption.
* **Treat meteorological data quality and threshold calibration as coupled:** Real-sensor validation proved that Open-Meteo ERA5 reanalysis introduces `+1.2` to `+1.5 h/day` of LWD error and a `+1.6 h/day` wet bias relative to local stations. Yet simply plugging cleaner local station data into a reanalysis-calibrated threshold (`st_v1_T10`) did not automatically improve decisions. Operational deployments (e.g., on Luxembourg's ASTA/`agrimeteo.lu` network) should calibrate thresholds directly on local station series.

---

## 5. Reproducibility, Software, and AI Assistance Statement

### 5.1 Software Architecture and Verification

All code is implemented in Python 3.12 (`numpy`, `scipy`, `pandas`, `requests`, `flask`, `psycopg2-binary`, `pytest`) with cross-validation of trapezoidal AUDPC against R 4.6.1 (`r/aacpd_validacao.R`, maximum discrepancy `3.33e-9 < 1e-6`). The automated test suite (`pytest tests/ -q`) comprises **69 passing unit and integration tests** executing offline without external database or GPU dependencies. A companion fix in `epidemiology_assimilation.py` separated `r_prior_gompertz` from `r_prior`, restoring within-model 95% credible-interval coverage of `r` from `~75%` (cross-model scale artifact) to `97.9%` (logistic) and `95.8%` (Gompertz).

Every frozen checkpoint is preserved in Git history:
* `2e8aea8`: Freeze four-arm OSSE ablation before `2022–2024` out-of-sample evaluation.
* `68ef7fd`: Freeze `T = 10.0` and residual coverage gate (`v2`) before unseen `2019–2021` + Alsace validation.
* `a562ccc`: Freeze `rh90_hysteresis` LWD test and economics before untouched `2016–2018` validation.
* `958cbe3`: Semi-real INRAE sensor OSSE (`N = 1,200`), calibrated Moselle error test (`N = 180`), and EU 2018/1981 copper sensitivity surface.

### 5.2 AI Assistance Statement

The software implementation, simulation pipelines, statistical scripts, and draft structuring of this technical report were developed iteratively with AI coding and review assistants (Antigravity / Gemini and Claude Opus) under human direction. All experimental design decisions, scientific critiques, hypothesis freezes, data-source verifications, and interpretation of negative and positive findings were reviewed, challenged, and verified against raw repository outputs and primary open-access datasets.

---

## References

1. Baldacci, E. (1947). Epifitie di *Plasmopara viticola* (1941–46) nell'Oltrepò Pavese ed adozione del calendario di incubazione come strumento di lotta. *Atti dell'Istituto Botanico della Università di Pavia*, 8, 45–85.
2. Colucci, G. P., Filipescu, E., Scatozza, F., & Trinchero, D. (2025). *Leaf Wetness and Agrometeorological Dataset*. Politecnico di Torino / iXem Labs, Mendeley Data, V1. DOI: `10.17632/sd4b8vpvyb.1`.
3. European Commission (2018). *Commission Implementing Regulation (EU) 2018/1981 of 13 December 2018 renewing the approval of the active substances copper compounds, as candidates for substitution*. Official Journal of the European Union, L 317, 16–20.
4. Furusho-Percot, C., Maury, O., Minet, V., De Decker, T., Roux, D., Beauvois, C., Le Roux, R., Décome, J., Launay, M., & García de Cortázar-Atauri, I. (2025). French agroclimatic research network dataset. *Data in Brief*, 61, 111809. PMCID: `PMC12266558`. Dataset: INRAE AgroClim, Recherche Data Gouv, DOI: `10.57745/BQ0BWB`.
5. Gessler, C., Pertot, I., & Perazzolli, M. (2011). *Plasmopara viticola*: a review of knowledge on downy mildew of grapevine and effective disease management. *Phytopathologia Mediterranea*, 50(1), 3–44.
6. Gillespie, T. J., Srivastava, B., & Pitblado, R. E. (1993). Using operational weather data to schedule fungicide sprays on tomatoes in southern Ontario, Canada. *Journal of Applied Meteorology*, 32(3), 567–573.
7. Gleason, M. L., Taylor, S. E., Loughin, T. M., & Koehler, K. J. (1994). Development and validation of an empirical model to estimate the duration of dew periods. *Plant Disease*, 78(10), 1011–1016.
8. Goidànich, G. (1964). *Manuale di Patologia Vegetale*, Vol. II. Edagricole, Bologna.
9. Kim, K. S., Taylor, S. E., Gleason, M. L., & Koehler, K. J. (2002). Model to enhance site-specific estimation of leaf wetness duration. *Plant Disease*, 86(2), 179–185.
10. Madden, L. V., Hughes, G., & van den Bosch, F. (2007). *The Study of Plant Disease Epidemics*. APS Press, St. Paul, MN.
11. Rossi, V., Caffi, T., Giosuè, S., & Bugiani, R. (2008). A mechanistic model simulating primary infections of downy mildew in grapevine. *Ecological Modelling*, 212(3–4), 480–491.
12. Sentelhas, P. C., Dalla Marta, A., Orlandini, S., Santos, E. A., Gillespie, T. J., & Gleason, M. L. (2008). Suitability of relative humidity as an estimator of leaf wetness duration. *Agricultural and Forest Meteorology*, 148(3), 392–400.
