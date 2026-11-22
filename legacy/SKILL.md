---
name: tomato-dss
description: Arquitetura, contratos JSON, esquema de banco e regras agronômicas do DSS de pinta-preta e requeima do tomateiro (ensaio de 20 vasos em São José/SC). Leia inteiro antes de criar ou alterar qualquer arquivo do projeto.
---

# DSS de doenças foliares do tomateiro

## 0. Regras para o agente

Siga na ordem. Em caso de conflito, a regra de número menor vence.

1. Este arquivo é a fonte de verdade. Se o pedido contradiz o que está aqui, pare e pergunte ao Mateus. Não improvise.
2. Não invente nome de campo, tabela, coluna, endpoint, classe de modelo, limiar ou unidade. Se o que você precisa não está neste arquivo nem no código existente, pergunte.
3. Não altere os contratos da seção 5 nem o esquema da seção 6 sem pedido explícito. Mudança de contrato exige subir `schema_version` e atualizar este arquivo no mesmo commit.
4. Os três módulos entregues (`vision_pipeline.py`, `epidemiology_assimilation.py`, `weather_collector.py`) já funcionam. Importe e chame. Não reescreva, não duplique lógica deles em outro arquivo.
5. Toda data e hora trafega em ISO 8601 com fuso e é gravada em UTC como `timestamptz`. Data sem fuso é erro e deve ser rejeitada.
6. Severidade é sempre percentual de 0 a 100, nunca fração de 0 a 1.
7. Não adicione dependência nova sem perguntar. As permitidas estão na seção 2.
8. O sistema recomenda, quem decide é a pessoa. Nunca escolha produto, dose ou intervalo de segurança. Isso vem do receituário agronômico.
9. Antes de dizer que terminou, rode a lista da seção 11.

## 1. O que o sistema faz

Circuito fechado: vídeo da folha -> severidade medida -> curva de progresso recalibrada -> projeção de 7 dias com o clima previsto -> recomendação de manejo -> aplicação registrada -> novo vídeo.

Doenças: pinta-preta (*Alternaria solani*), código `pinta_preta`, e requeima (*Phytophthora infestans*), código `requeima`. Use só esses dois códigos.

### Ensaio

| Item | Valor |
|---|---|
| Local | São José/SC, latitude -27.5969, longitude -48.6367 |
| Vasos | 20, identificados de `V01` a `V20` |
| Testemunha | `V01` a `V10`, tratamento `testemunha`, sem aplicação para as duas doenças |
| Manejo pelo DSS | `V11` a `V20`, tratamento `dss` |
| Folhas marcadas | 60, três por vaso, identificadas como `V01-F1`, `V01-F2`, `V01-F3` |
| Avaliação | a cada 2 ou 3 dias, um vídeo por folha |
| Vídeo | 1080p, 30 fps, 4 a 5 s, fundo EVA azul-royal ou cinza, quadrado de referência de 2 x 2 cm no mesmo plano da folha |
| Unidade experimental | o vaso. As folhas são subamostras |

Expressões regulares válidas: vaso `^V(0[1-9]|1\d|20)$`, folha `^V(0[1-9]|1\d|20)-F[1-3]$`.

Nome de arquivo de vídeo: `{leaf_id}_{AAAAMMDD}T{HHMM}.mp4`, hora local. Exemplo: `V11-F2_20261201T0930.mp4`.

## 2. Stack

| Camada | Tecnologia |
|---|---|
| Treino dos modelos | Google Colab |
| Inferência e desenvolvimento | máquina local, GPU NVIDIA GTX 1660 Super com 6 GB |
| Backend | Python 3.10 ou mais novo, Flask |
| Banco | Supabase (PostgreSQL), acesso por `psycopg2` com `DATABASE_URL` |
| Estatística | R, com `agricolae` ou `epifitter` para a AACPD e `metan` para as análises |
| Agentes de código | Qwen no Ollama e Claude Sonnet, guiados por este arquivo |

Dependências Python permitidas: `ultralytics`, `torch`, `opencv-python`, `numpy`, `scipy`, `pandas`, `requests`, `psycopg2-binary`, `flask`, `python-dotenv`, `pytest`. No Windows, instale também `tzdata`, que o `zoneinfo` exige.

O `ultralytics` trocou o argumento `half=True` por `quantize=16` nas versões recentes. `YoloRunner` detecta qual dos dois a versão instalada aceita. Não passe nenhum dos dois por fora dele.

Segredos ficam em `.env`, que nunca entra no git: `DATABASE_URL`, `INMET_TOKEN`, `EPAGRI_API_TOKEN`.

### GPU de 6 GB

* Uma única instância de `VisionPipeline` por processo. O Flask roda com um worker para a rota de vídeo, ou com um `threading.Lock` em volta de `pipeline.process`.
* Padrões: estágio A com `imgsz` 640 e lote 4, estágio B com `imgsz` 1024 e lote 2. Use modelos `n` ou `s`. Não use `m`, `l` nem `x`.
* Não force `half="on"`. As GTX 16xx devolvem NaN em FP16 em várias combinações de driver e PyTorch. O pipeline testa FP32 contra FP16 e decide sozinho. A variável `VISION_HALF=0` desliga de vez.
* Falta de memória já é tratada dentro de `YoloRunner.predict`. Não envolva a chamada em outro `try`.

## 3. Pastas

```
tomato_dss/
  SKILL.md
  vision_pipeline.py            pronto
  epidemiology_assimilation.py  pronto
  weather_collector.py          pronto
  decision_engine.py            a implementar, contrato 5.4
  db.py                         a implementar, único ponto de acesso ao banco
  app.py                        a implementar, rotas da seção 5.5
  models/stage_a_leaf.pt        pesos do estágio A
  models/stage_b_lesion.pt      pesos do estágio B
  data/videos/AAAA-MM-DD/       vídeos originais, nunca apagados
  data/epagri_csv/              CSV baixado do portal da Epagri
  data/debug/                   sobreposições geradas com --debug-dir
  r/aacpd_validacao.R           a implementar
  tests/test_smoke.py           pronto, 46 testes sem rede, sem banco e sem GPU
  .env
```

## 4. Fluxo de dados

```
vídeo .mp4 --> vision_pipeline.process --> video_assessments
                                               |
                         média das 3 folhas por vaso e dia
                                               v
weather_collector --> weather_hourly --> epidemiology_assimilation.assimilate --> epi_fits
                                               |
                                               v
                                   decision_engine.decide --> decisions
                                               |
                         pessoa aplica ou não, e registra --> spray_events
```

O coletor de clima roda por cron de hora em hora. A assimilação roda quando entra um vídeo novo de qualquer folha do vaso. A decisão roda depois de cada assimilação dos vasos `V11` a `V20`.

## 5. Contratos

### 5.1 Saída de `VisionPipeline.process(video_path, leaf_id=None, captured_at=None, debug_dir=None)`

```json
{
  "schema_version": "1.0",
  "leaf_id": "V11-F2",
  "pot_id": "V11",
  "captured_at": "2026-12-01T09:30:00-03:00",
  "video": {"file": "V11-F2_20261201T0930.mp4", "sha256": "...", "n_frames": 135, "fps": 30.0, "width": 1920, "height": 1080},
  "severity_pct": 4.1095,
  "severity_sd_pct": 0.0821,
  "necrosis_pct": 2.4463,
  "chlorosis_pct": 1.6632,
  "leaf_area_cm2": 40.8484,
  "lesion_area_mm2": 167.8668,
  "necrosis_area_mm2": 99.9275,
  "chlorosis_area_mm2": 67.9393,
  "calibration": {"px_per_cm": 89.9993, "ref_square_side_px": 179.9986, "ref_square_side_cm": 2.0, "squareness": 1.0, "ok": true},
  "aggregation": {"method": "consensus", "n_keyframes": 4, "n_valid": 4, "n_aligned": 4, "reference_frame": 0},
  "keyframe_selection": {"sharpness_p90": 97.65, "n_blurry": 48, "n_duplicates_dropped": 1},
  "method": {"weights_a": "stage_a_leaf.pt", "weights_b": "stage_b_lesion.pt", "device": "cuda:0", "half": false,
             "stage_a": "yolo", "imgsz_a": 640, "batch_a": 4, "stage_b": "yolo", "imgsz_b": 1024, "batch_b": 2, "tiles_per_frame": 1.0},
  "keyframes": [{"frame_index": 0, "sharpness": 120.06, "leaf_found": true, "calibrated": true, "severity_pct": 4.0651, "aligned": true, "align_iou": 1.0, "align_method": "reference"}],
  "quality": {"ok": true, "flags": []},
  "processing_ms": 2446
}
```

Definições:

* `severity_pct` = (necrose + clorose) / área total da folha x 100. A área da folha inclui a parte lesionada.
* `necrosis_pct` + `chlorosis_pct` = `severity_pct`. Pixel com as duas classes conta como necrose.
* `severity_sd_pct` é o desvio-padrão entre keyframes. Pode ser `null` com um keyframe só.
* `aggregation.method` vale `consensus` quando a severidade sai do voto por pixel entre frames alinhados. Vale `median` quando o alinhamento falha e a resposta é a mediana das severidades por frame.
* Sem quadrado de referência as áreas em cm² e mm² vêm `null`. A severidade continua válida, porque é razão de áreas.
* `captured_at` não é lido do vídeo. Quem chama informa.

Flags de `quality.flags`:

| Flag | Significado | Bloqueia `quality.ok` |
|---|---|---|
| `no_leaf` | nenhuma folha segmentada | sim |
| `few_keyframes` | menos de 3 keyframes | sim |
| `leaf_touches_border` | folha cortada pela borda do quadro | sim |
| `high_frame_disagreement` | desvio entre frames maior que max(1,0; 25 % da severidade) | sim |
| `classical_fallback_stage_a`, `classical_fallback_stage_b` | sem pesos treinados, usou limiar de cor | sim |
| `no_calibration` | quadrado de referência não encontrado | não |
| `calibration_tilt` | `squareness` < 0,85, câmera inclinada | não |
| `alignment_failed` | caiu para a mediana | não |
| `low_sharpness` | mais de 80 % dos frames borrados | não |
| `fp16_disabled` | rodou em FP32 na GPU | não |

Regra de uso: só entra na assimilação a avaliação com `quality.ok = true`. As demais são gravadas com `accepted = false` e a pessoa é avisada para regravar o vídeo.

### 5.2 `epidemiology_assimilation.assimilate(...)`

Entrada, como argumentos nomeados ou JSON para `--input`:

```json
{
  "unit_id": "V11",
  "disease": "pinta_preta",
  "observations": [{"ts": "2026-12-01T09:30:00-03:00", "severity_pct": 0.42, "severity_sd_pct": 0.11}],
  "weather_observed": [{"ts": "2026-12-01T13:00:00+00:00", "temp_c": 24.1, "rh_pct": 78.0, "precip_mm": 0.0}],
  "weather_forecast": [{"ts": "2026-12-08T13:00:00+00:00", "temp_c": 22.3, "rh_pct": 91.0, "precip_mm": 1.2}],
  "prev_state": null,
  "spray_events": ["2026-12-05T08:00:00-03:00"],
  "prior": null
}
```

* `observations` do vaso vêm de `aggregate_leaves_to_pot`, que faz a média das folhas aceitas por dia local. Não passe as folhas soltas como se fossem o vaso.
* `weather_observed` cobre do primeiro vídeo até agora. `weather_forecast` cobre as 168 h seguintes. As duas listas vêm de `weather_hourly`, com `kind` `observed` e `forecast`.
* `prev_state` é o campo `state` da saída anterior do mesmo vaso e da mesma doença, lido de `epi_fits`. Na primeira chamada é `null`.

Saída:

```json
{
  "schema_version": "1.0",
  "unit_id": "V11", "disease": "pinta_preta", "fitted_at": "2026-12-15T09:40:00-03:00",
  "model": "logistic", "n_obs": 8,
  "params": {"r": 0.5228, "r_ci95": [0.3809, 0.6717], "r_unit": "por_dia_favoravel", "y0_pct": 0.4419, "K_pct": 100.0, "r_prior": 0.18, "r_prior_sd_log": 0.7},
  "fit": {"rmse_pct": 0.1917, "chi2_red": 0.2018, "aicc": {"logistic": 7.611, "gompertz": 8.135}, "forgetting": 0.97, "posterior_ess": 2250.0, "fitted_pct": [0.44, 0.66]},
  "innovation": {"predicted_pct": 5.63, "observed_pct": 6.56, "pred_sd_pct": 1.11, "z": 0.841, "regime_change": false},
  "tau": {"at_last_obs": 5.2142, "calendar_days": 14.0, "weather_gap_hours": 0},
  "projection": [{"ts": "2026-12-15T15:00:00-03:00", "lead_h": 6, "tau": 5.31, "y_median": 6.6, "y_lo95": 5.5, "y_hi95": 8.6}],
  "aacpd": {"unit": "pct_x_dia", "observed": 31.08, "projected_median": 80.16, "projected_ci95": [55.14, 118.0], "total_median": 111.24, "total_ci95": [86.22, 149.08], "relative_total": 0.05297, "window_days": 21.0},
  "risk": {"wet_hours_7d": 59, "tomcast_dsv_7d": 10, "wallin_sv_7d": 0, "tau_gain_7d": 2.4906, "p_exceed": {"threshold_pct": 5.0, "p": 1.0}},
  "state": {"model": "logistic", "theta": [-0.6485, -5.417], "mean": [-0.66, -5.40], "cov": [[0.02, -0.03], [-0.03, 0.06]], "k_floor": null, "t0": "2026-12-01T12:30:00+00:00", "last_obs_ts": "2026-12-15T12:30:00+00:00"},
  "flags": []
}
```

* `projection` tem um ponto a cada 6 h, de `lead_h` 0 a 168. `y_lo95` e `y_hi95` são o intervalo de 95 % da severidade real, sem o ruído de medida.
* `r_unit` é `por_dia_favoravel` quando há clima e `por_dia` quando não há.
* `innovation` é `null` nas três primeiras avaliações sem `prev_state`.

Flags: `prior_dominated` (menos de 3 avaliações), `pre_symptomatic` (tudo abaixo de 0,05 %), `regime_change` (|z| > 3, ajuste refeito com esquecimento 0,80), `no_weather_calendar_time`, `weather_gaps_filled`, `forecast_shorter_than_horizon`, `posterior_low_ess`.

### 5.3 `weather_collector`

`collect(settings, now=None, session=None)` devolve `CollectionResult`. `store(conn, result, settings)` grava. Linha horária normalizada:

```json
{"station_id": "sj_vasos", "ts": "2026-12-10T12:00:00+00:00", "kind": "observed", "source": "inmet", "source_priority": 2,
 "temp_c": 22.5, "rh_pct": 88.0, "precip_mm": 0.2, "dewpoint_c": 18.1, "wind_ms": 2.3, "rad_wm2": 500.0,
 "leaf_wet": true, "is_measured": true, "issued_at": "2026-12-10T12:20:00+00:00"}
```

* `ts` marca o fim da hora. Temperatura e umidade são do instante. Chuva é o acumulado dos 60 min anteriores.
* `kind`: `observed` ou `forecast`. `source` e `source_priority`: `epagri_ciram` com 1, `inmet` com 2, `open_meteo` com 3. Número menor vence.
* `is_measured` é falso para tudo que vem do Open-Meteo, inclusive as horas passadas, que são análise de modelo.
* Status do log: `ok`, `ok_with_fallback`, `partial`, `failed`.

### 5.4 `decision_engine.decide(...)`, a implementar

Entrada: saída de 5.2, linhas de `dsv_daily` do vaso, último `spray_events` do vaso. Saída:

```json
{
  "schema_version": "1.0",
  "pot_id": "V11", "disease": "pinta_preta", "decided_at": "2026-12-15T09:41:00-03:00",
  "action": "spray",
  "reasons": ["dsv_since_last_spray>=15"],
  "inputs": {"dsv_since_last_spray": 16, "wallin_sv_7d": 2, "p_exceed": 0.62, "days_since_last_spray": 9, "regime_change": false}
}
```

`action` aceita só `spray`, `monitor` ou `none`. As regras estão na seção 7.4.

### 5.5 Rotas Flask, a implementar

| Método e rota | Corpo | Resposta |
|---|---|---|
| `POST /api/v1/assessments` | multipart: `video`, `leaf_id`, `captured_at` | 201 com `{"assessment_id", "vision": <5.1>}`. 422 com o mesmo corpo se `quality.ok` for falso |
| `POST /api/v1/pots/<pot_id>/assimilate?disease=` | vazio | 200 com 5.2 |
| `GET /api/v1/pots/<pot_id>/projection?disease=` | | 200 com o último 5.2 gravado |
| `GET /api/v1/pots/<pot_id>/decision?disease=` | | 200 com 5.4 |
| `POST /api/v1/sprays` | `{"pot_id", "applied_at", "product", "dose", "notes"}` | 201 |
| `GET /api/v1/weather/summary` | | 200 com cobertura e última observação |
| `GET /api/v1/health` | | 200 com `{"db": true, "gpu": true, "weights": true}` |

Erros em JSON: `{"error": {"code": "invalid_leaf_id", "message": "..."}}`. `POST /assessments` grava o vídeo em `data/videos/AAAA-MM-DD/` antes de processar. Se o `sha256` já existe em `video_assessments`, devolve o registro existente com 200.

## 6. Banco de dados

Convenções: nomes em inglês, `snake_case`, tabelas no plural. Tempo em `timestamptz`. Percentual em `double precision` de 0 a 100. JSON bruto dos módulos em `jsonb`. Toda escrita passa por `db.py`. Use `insert ... on conflict` para tornar as cargas repetíveis. Não use `delete` em tabela de dado do ensaio.

As tabelas `weather_hourly`, `weather_forecast_archive`, `weather_ingest_log` e a view `weather_hourly_local` são criadas por `python weather_collector.py --init-db`. A definição que vale é a constante `DDL` daquele arquivo. Chave de `weather_hourly`: `(station_id, ts, kind)`.

```sql
create table if not exists pots (
    pot_id    text primary key check (pot_id ~ '^V(0[1-9]|1[0-9]|20)$'),
    treatment text not null check (treatment in ('testemunha', 'dss'))
);

create table if not exists leaves (
    leaf_id text primary key check (leaf_id ~ '^V(0[1-9]|1[0-9]|20)-F[1-3]$'),
    pot_id  text not null references pots,
    disease text check (disease in ('pinta_preta', 'requeima')),
    notes   text
);

create table if not exists video_assessments (
    assessment_id  bigint generated always as identity primary key,
    leaf_id        text not null references leaves,
    captured_at    timestamptz not null,
    video_sha256   text not null unique,
    video_path     text not null,
    severity_pct   double precision check (severity_pct between 0 and 100),
    severity_sd_pct double precision,
    necrosis_pct   double precision,
    chlorosis_pct  double precision,
    leaf_area_cm2  double precision,
    lesion_area_mm2 double precision,
    quality_ok     boolean not null,
    accepted       boolean not null,
    flags          text[] not null default '{}',
    result         jsonb not null,
    created_at     timestamptz not null default now()
);
create index if not exists video_assessments_leaf_ts on video_assessments (leaf_id, captured_at);

create table if not exists epi_fits (
    fit_id      bigint generated always as identity primary key,
    pot_id      text not null references pots,
    disease     text not null check (disease in ('pinta_preta', 'requeima')),
    fitted_at   timestamptz not null,
    model       text not null check (model in ('logistic', 'gompertz')),
    n_obs       integer not null,
    r           double precision not null,
    r_lo95      double precision,
    r_hi95      double precision,
    aacpd_observed double precision,
    aacpd_total_median double precision,
    state       jsonb not null,
    result      jsonb not null
);
create index if not exists epi_fits_pot on epi_fits (pot_id, disease, fitted_at desc);

create table if not exists spray_events (
    spray_id   bigint generated always as identity primary key,
    pot_id     text not null references pots,
    applied_at timestamptz not null,
    product    text not null,
    dose       text,
    notes      text
);

create table if not exists dsv_daily (
    station_id text not null,
    day        date not null,
    kind       text not null check (kind in ('observed', 'forecast')),
    tomcast_dsv smallint not null check (tomcast_dsv between 0 and 4),
    wallin_sv   smallint not null check (wallin_sv between 0 and 4),
    wet_hours   smallint not null,
    primary key (station_id, day, kind)
);

create table if not exists decisions (
    decision_id bigint generated always as identity primary key,
    pot_id      text not null references pots,
    disease     text not null,
    decided_at  timestamptz not null,
    action      text not null check (action in ('spray', 'monitor', 'none')),
    reasons     text[] not null,
    result      jsonb not null
);
```

`accepted` começa igual a `quality_ok`. Só a pessoa muda esse campo, depois de olhar a sobreposição em `data/debug/`.

`leaves.disease` é preenchido pela pessoa quando o primeiro sintoma aparece. A visão mede necrose e clorose e não distingue pinta-preta de requeima. Não tente inferir a doença pela imagem.

`dsv_daily.day` é o dia local em que a janela de 24 h começa, ao meio-dia.

## 7. Regras agronômicas

### 7.1 Molhamento foliar e tempo epidemiológico

* Hora molhada: UR >= 85 % ou chuva > 0 mm na hora. O limiar clássico é 90 %. O projeto usa 85 % porque a estação fica fora do dossel.
* Favorabilidade horária: `f = g(T) * [d + (1 - d) * molhada]`, com `g` a função beta de temperatura.
* `tau` = soma de `f` dividida por 24, em dias favoráveis. A taxa `r` é por dia favorável.

| Parâmetro | `pinta_preta` | `requeima` |
|---|---|---|
| Tmin, Tot, Tmax em graus C | 6, 27, 35 | 4, 20, 30 |
| `d`, fração do progresso com folha seca | 0,25 | 0,10 |
| `r` da priori, por dia favorável | 0,18 | 0,35 |
| desvio de ln `r` na priori | 0,70 | 0,70 |

Esses valores são iniciais, tirados de faixas da literatura (recalibrar com a testemunha ao fim do ensaio). Ficam em `PATHOGENS` no módulo de assimilação. Mude lá, não espalhe cópias.

### 7.2 TOM-CAST, pinta-preta

DSV diário pelas horas molhadas da janela de 12 h a 12 h locais e pela temperatura média dessas horas, arredondada ao inteiro. Fora de 13 a 29 graus o DSV é 0.

| Temp. média (graus C) | DSV 0 | DSV 1 | DSV 2 | DSV 3 | DSV 4 |
|---|---|---|---|---|---|
| 13 a 17 | 0 a 6 h | 7 a 15 h | 16 a 20 h | 21 h ou mais | não há |
| 18 a 20 | 0 a 3 h | 4 a 8 h | 9 a 15 h | 16 a 22 h | 23 h ou mais |
| 21 a 25 | 0 a 2 h | 3 a 5 h | 6 a 12 h | 13 a 20 h | 21 h ou mais |
| 26 a 29 | 0 a 3 h | 4 a 8 h | 9 a 15 h | 16 a 22 h | 23 h ou mais |

Função: `epidemiology_assimilation.tomcast_dsv`. Não reescreva a tabela em outro arquivo.

### 7.3 Wallin, requeima

Valor de severidade diário pela maior sequência de horas com UR >= 90 % na janela e pela temperatura média nessas horas.

| Temp. média (graus C) | 0 | 1 | 2 | 3 | 4 |
|---|---|---|---|---|---|
| 7,2 a 11,6 | até 15 h | 16 a 18 h | 19 a 21 h | 22 h ou mais | não há |
| 11,7 a 15,0 | até 12 h | 13 a 15 h | 16 a 18 h | 19 a 21 h | 22 h ou mais |
| 15,1 a 26,6 | até 9 h | 10 a 12 h | 13 a 15 h | 16 a 18 h | 19 h ou mais |

Função: `epidemiology_assimilation.wallin_severity`.

### 7.4 Regra de decisão para `V11` a `V20`

Avalie na ordem. A primeira condição verdadeira define a resposta.

1. Vaso de `V01` a `V10`: `action = "none"`, sempre.
2. Menos de 7 dias desde a última aplicação no vaso: `action = "monitor"` (intervalo mínimo do projeto, conferir com a bula do produto usado).
3. `pinta_preta` com DSV acumulado desde a última aplicação >= 15: `spray`. Sem aplicação anterior, acumule desde o transplante. (Limiar do projeto. A literatura usa de 12 a 20 conforme a cultivar. Confirmar.)
4. `requeima` com soma de Wallin dos últimos 7 dias observados >= 5, ou soma desde o transplante >= 18 sem nenhuma aplicação anterior: `spray`. (Simplificação da matriz do BLITECAST. Confirmar.)
5. `risk.p_exceed.p` >= 0,50, ou seja, probabilidade de passar de 5 % de severidade em 7 dias: `spray`.
6. `innovation.regime_change` verdadeiro, ou `risk.tomcast_dsv_7d` >= 10, ou `risk.wallin_sv_7d` >= 3: `monitor`, com nova avaliação por vídeo em 2 dias.
7. Caso contrário: `none`.

Cada condição que disparou entra em `reasons` com o texto exato: `dsv_since_last_spray>=15`, `wallin_7d>=5`, `wallin_total>=18`, `p_exceed>=0.5`, `regime_change`, `forecast_risk`, `min_interval`, `control_pot`.

Depois de uma aplicação registrada em `spray_events`, o DSV acumulado do vaso volta a zero. A aplicação entra na assimilação pelo argumento `spray_events`, com eficácia 0,60 e meia-vida de 7 dias (valores do projeto, a calibrar).

## 8. Regras de visão

Classes dos modelos, nesta ordem de índice:

| Modelo | Arquivo | Classes |
|---|---|---|
| Estágio A | `models/stage_a_leaf.pt` | 0 `leaf`, 1 `ref_square` |
| Estágio B | `models/stage_b_lesion.pt` | 0 `necrosis`, 1 `chlorosis` |

* A classe `leaf` cobre o limbo da folha marcada inteira, com as áreas lesionadas dentro. Pecíolo, dedos e folhas vizinhas ficam fora.
* O estágio B é treinado em recortes da folha com o fundo pintado de cinza 114, igual ao que o pipeline entrega na inferência.
* Divisão treino e validação por vaso, nunca por frame. Frames do mesmo vídeo em treino e validação inflam a métrica. Vasos de validação: `V05`, `V10`, `V15`, `V20`.
* Critério de aceite do modelo: coeficiente de concordância de Lin >= 0,90 entre a severidade do pipeline e a anotada à mão nos vasos de validação (meta do projeto).
* Captura: folha aberta e apoiada no EVA, quadrado de referência inteiro no quadro e no mesmo plano, câmera perpendicular, sem sombra dura, movimento lento.
* O fundo azul-royal é melhor que o cinza. Necrose seca tem cor próxima do cinza e some na borda da folha quando a segmentação é por cor.

## 9. Regras estatísticas

* A AACPD é calculada por vaso, com a média diária das folhas aceitas, pela regra dos trapézios, em % x dia. Função: `epidemiology_assimilation.aacpd`.
* No R, use `agricolae::audpc` ou `epifitter::AUDPC` com os mesmos pontos. Diferença aceita entre Python e R: até 1e-6.
* Comparação de tratamentos: 2 tratamentos, 10 vasos cada, delineamento inteiramente casualizado. Não trate as 60 folhas como repetições. Isso é pseudorrepetição.
* Exportação para o R: `r/dados/aacpd_por_vaso.csv` com as colunas `pot_id, treatment, disease, aacpd, n_avaliacoes, primeira_data, ultima_data`.
* Para a análise final use a AACPD observada. A projetada serve à decisão, não ao teste de hipótese.

## 10. Proibido

* Gravar hora local sem fuso, ou converter fuso somando 3 horas na mão. Use `zoneinfo.ZoneInfo("America/Sao_Paulo")`.
* Somar área de lesão de vários frames do mesmo vídeo.
* Usar avaliação com `accepted = false` na assimilação ou na AACPD.
* Aplicar a regra de decisão aos vasos `V01` a `V10`.
* Trocar `psycopg2` por ORM, ou abrir conexão fora de `db.py`.
* Carregar os modelos YOLO a cada requisição.
* Deixar token ou senha no código, no log ou em mensagem de commit.
* Preencher dado de clima ausente com valor inventado. Hora sem dado fica nula. A assimilação já trata as falhas.
* Mexer nas tabelas TOM-CAST e Wallin, ou nos parâmetros de `PATHOGENS`, sem pedido explícito.
* Escrever `TODO`, `pass` ou função vazia e chamar de pronto.

## 11. Lista antes de entregar uma tarefa

1. O código roda: `python -m pytest tests/ -q` sem falha.
2. `python epidemiology_assimilation.py --demo` termina sem erro.
3. `python weather_collector.py --dry-run -v` devolve `status` diferente de `failed`.
4. Nenhum contrato da seção 5 mudou. Se mudou, `schema_version` subiu e este arquivo foi atualizado.
5. Todo timestamp novo tem fuso.
6. Nenhum segredo em arquivo versionado.
7. A mensagem final diz o que foi feito, o que foi testado e o que ficou sem testar.

## 12. Pontos em aberto

Não resolva sozinho. Pergunte ao Mateus.

* A Epagri/Ciram não tem API pública de dados horários. O coletor lê o CSV baixado do portal `dadosambientaispublicos` ou um endpoint JSON, se o Ciram liberar acesso. O manual do portal não informa se a hora do CSV é local ou UTC (confirmar com o Ciram). O padrão do código é hora local, ajustável por `EPAGRI_TZ`.
* As rotas da API do INMET e a exigência de token mudaram nos últimos anos (conferir no manual da API do INMET antes de depender dela).
* A estação da Epagri fica no Itacorubi, em Florianópolis, e a do INMET é a A806. Nenhuma das duas está nos vasos em São José. O molhamento estimado por UR de estação distante é a maior fonte de erro do modelo climático.
* Limiares da seção 7.4 e parâmetros da seção 7.1.
* Data de transplante dos vasos, necessária para acumular DSV antes da primeira aplicação.

## 13. Glossário

| Termo | Significado |
|---|---|
| AACPD | área abaixo da curva de progresso da doença, AUDPC em inglês |
| DSV | valor diário de severidade do TOM-CAST, de 0 a 4 |
| SV | valor de severidade de Wallin, de 0 a 4 |
| `tau` | tempo epidemiológico, em dias favoráveis acumulados |
| `r` | taxa de progresso da doença na curva logística ou de Gompertz |
| keyframe | frame nítido escolhido para a medição |
| testemunha | vasos sem manejo para as duas doenças |
| inovação | diferença entre a avaliação nova e o que o ajuste anterior previa |
