# Pré-registro experimental do vitirule v2

> **Estado:** CONGELADO NA TAG `v2-freeze`, antes de executar qualquer comparação entre fontes meteorológicas candidatas e a referência medida. Qualquer alteração posterior a `v2-freeze` entrará obrigatoriamente na seção 8 com data, motivo e resultado das duas versões.

## 1. Pergunta de pesquisa e escopo

O vitirule v2 responde a uma pergunta específica: **quanto se pode confiar num alerta de doença calculado com dado meteorológico gratuito, e onde ele falha?**

O projeto não mede eficácia de controle no campo nem simula progresso epidêmico. O protocolo do míldio da v1 permanece congelado no repositório como estudo de caso 1, acompanhado da errata `v1.0.2`. A v2 mede exclusivamente a confiabilidade da entrada meteorológica em quatro regras clássicas publicadas, comparando cada fonte candidata contra a mesma regra alimentada pelos dados medidos na própria estação com sensor físico de molhamento foliar.

## 2. Escopo das estações e separação por rede

As estações meteorológicas das redes INRAE AgroClim na França e Politecnico di Torino na Itália são estações agrometeorológicas de pesquisa ou de vinhedo, não pomares de macieira nem lavouras comerciais de tomate. Rodar a tabela revisada de Mills e o TOM-CAST sobre essas séries mede a fidelidade da entrada meteorológica diante de regras com estruturas matemáticas distintas, não o risco fitossanitário real da macieira ou do tomateiro naquela coordenada.

Por esse motivo, todos os resultados serão reportados separadamente por rede de referência, sem agregação cega entre INRAE AgroClim, Politecnico di Torino e, na Fase 4, Epagri/Ciram.

## 3. Regras publicadas e parâmetros

Todas as constantes, tabelas, divergências da literatura, escolhas adotadas e citações primárias estão centralizadas em `vitirule_v2/rules/params.json`.

1. **Regra 3-10 para míldio da videira:** baseada em Baldacci (1947), Goidànich (1964) e na descrição operacional revista por Rossi et al. (2008). Dispara alerta de infecção primária quando a data está dentro da janela fenológica da videira, a **temperatura mínima diária local** é maior ou igual a `10,0 °C` conforme Emenda 2 abaixo, a precipitação acumulada em 48 horas atinge pelo menos `10,0 mm` e há chuva ativa no dia do disparo de pelo menos `0,2 mm`. Dias consecutivos que satisfazem o critério são agrupados num único evento datado pelo primeiro dia de disparo. A versão original de `v2-rules` com temperatura média diária fica preservada como análise secundária documentada na seção 8.
2. **Calendário de incubação de Goidànich para míldio da videira:** baseado em Müller & Sleumer (1934) e Goidànich (1964). Cada evento primário 3-10 inicia uma coorte de incubação em 0% no dia seguinte ao disparo, somando o progresso diário interpolado linearmente pela tabela publicada em função da temperatura média diária, multiplicado por `0,85` quando a umidade relativa média diária fica abaixo de `75%`. O evento principal de alerta ocorre no dia em que o acumulado atinge `100%`. O marco preventivo de `80%` é registrado como metadado auxiliar.
3. **Tabela revisada de Mills para sarna da macieira:** baseada em MacHardy & Gadoury (1989) com extensão de baixas temperaturas de Stensvand et al. (1997) e tabela operacional da OMAFRA. Avalia eventos horários de molhamento dentro da janela primária da macieira iniciados ou acompanhados por pelo menos `0,2 mm` de chuva acumulada no evento. Períodos molhados separados por interrupção seca de até `8 horas` consecutivas são combinados num único evento, contando apenas as horas molhadas para a duração e para a temperatura média. Interrupções secas acima de `8 horas` reiniciam a contagem. Classifica cada evento em infecção leve, moderada ou severa conforme a tabela publicada.
4. **TOM-CAST para pinta-preta do tomate:** baseado em Madden, Pennypacker & MacNab (1978), Pitblado (1988, 1992) e Gillespie, Srivastava & Pitblado (1993). Calcula o DSV diário de 0 a 4 na janela de 12h a 12h no fuso local usando a matriz publicada sobre as horas molhadas e a temperatura média molhada arredondada pelo critério aritmético half-up. Dispara pulverização quando o DSV acumulado atinge `15`. Será avaliado nos dois modos de memória: reset autônomo `self_reset` controlado pela própria fonte candidata e reset sincronizado `reference_reset` nas datas de pulverização da referência medida.

## 4. Janelas fenológicas fixas

Como estações meteorológicas não registram fenologia local, aplicamos janelas fixas por hemisfério e cultura, idênticas para a referência e para todas as fontes candidatas. Isso elimina qualquer vazamento entre fontes e preserva a comparabilidade pareada, assumindo como limitação conhecida que variações interanuais de brotação não são modeladas.

- **Hemisfério Norte, França e Itália:**
  - Videira, regras 3-10 e Goidànich: `1 de abril` a `30 de setembro`.
  - Macieira, Mills primária: `15 de março` a `30 de junho`.
  - Tomateiro, TOM-CAST: `1 de maio` a `30 de setembro`.
- **Hemisfério Sul, Santa Catarina na Fase 4:**
  - Videira: `1 de outubro` a `31 de março` do ano seguinte.
  - Macieira: `15 de setembro` a `31 de dezembro`.
  - Tomateiro: `1 de novembro` a `31 de março` do ano seguinte.

## 5. Análise primária única, análises secundárias e conjunto confirmatório

### 5.1 Análise primária única e análises secundárias

Para evitar multiplicidade de testes, existe **uma única análise primária**:

- **Análise primária:** janela temporal pareada de **2022 a 2025** com todas as quatro fontes principais disponíveis simultaneamente, a saber estação local sem sensor, ERA5 combinado: T e UR do ERA5-Land, chuva, vento e radiação do ERA5, Open-Meteo Historical Forecast e NASA POWER; estimador de molhamento **`rh90_rain`**; Regra 3-10 com temperatura mínima diária **`daily_min`**; controle de qualidade sob política **`mask_with_warmup`**.

Todo o restante é **análise secundária**, sempre rotulada como tal:

1. Estimadores secundários de molhamento `dpd_hysteresis` e `cart_kim2002` em 2022–2025 para Mills e TOM-CAST.
2. Versão original `daily_mean` da Regra 3-10 e de Goidànich em 2022–2025.
3. Sensibilidade de controle de qualidade `reject_24h` em 2022–2025.
4. **Análise secundária A, série longa sem Historical Forecast:** anos de **2019 a 2025** no INRAE comparando estação sem sensor, ERA5 combinado: T e UR do ERA5-Land, chuva, vento e radiação do ERA5 e NASA POWER.
5. **Análise secundária B, previsão real com horizonte fixo:** anos de **2024 a 2025** com `Open-Meteo Previous Runs` nos horizontes de 1, 2 e 3 dias de antecedência.

### 5.2 Conjunto exploratório versus conjunto confirmatório

Substituímos o sorteio anterior de 20% em lockbox por uma separação limpa ligada ao congelamento:

- **Conjunto exploratório:** composto pelas 4 estações locais do INRAE e pelas 2 estações aprovadas do Politecnico di Torino já usadas na v1. Toda avaliação sobre essas estações é rotulada explicitamente como exploratória. O Politecnico di Torino, com apenas 2 estações aprovadas, é reportado de forma estritamente **descritiva, sem intervalos de confiança**.
- **Conjunto confirmatório:** como o desenvolvimento termina na tag `v2-freeze` e o lote novo do INRAE não tem nenhum papel antes dela, **todas as estações novas do INRAE** que passarem no controle de qualidade cego `vitirule_v2/qc.py` formam o conjunto confirmatório. Quando o portal `entrepot.recherche.data.gouv.fr` retornar e a licença for confirmada, o conjunto confirmatório roda **uma única vez** após `v2-freeze`, registrado na tag **`v2-confirmatory`**, e o resultado entra no relatório seja ele qual for.

### 5.3 Metadados espaciais e padrão temporal das fontes candidatas

- Todas as fontes são alinhadas em **UTC**. Na API horária do NASA POWER, o padrão da API sem parâmetro explícito é Local Solar Time, portanto o coletor exige `time-standard=UTC` em toda chamada e valida `header.time_standard == "UTC"` no retorno.
- Para cada estação e cada fonte em grade, registramos a distância horizontal em quilômetros até o ponto de grade servido e a diferença de altitude entre a grade e a estação. **Nenhuma correção de altitude entra na análise principal.**

## 6. Estimadores de molhamento foliar

Fixamos em `vitirule_v2/lwd.py` a hierarquia de estimadores puros de molhamento foliar, nenhum deles lendo o sensor físico da estação:

1. **Estimador primário:** `rh90_rain`, marcando a hora como molhada quando `UR >= 90,0%` ou `precipitação > 0,0 mm/h`.
2. **Estimadores secundários com parâmetros publicados fixos:**
   - `dpd_hysteresis`: depressão do ponto de orvalho com início em `DPD <= 1,8 °C` e secagem em `DPD >= 3,8 °C`, além de chuva acima de zero, citando Gillespie, Srivastava & Pitblado (1993).
   - `cart_kim2002`: árvore publicada por Kim, Taylor, Gleason & Koehler (2002) com seus coeficientes originais, ajustando vento de 10 m para 2 m via FAO-56 apenas nas fontes que entregam vento a 10 m.
3. **Sem modelo empírico recalibrado nesta etapa:** com apenas 4 estações do INRAE disponíveis antes do congelamento, nenhum modelo recalibrado entra na análise, evitando ajuste com amostra insuficiente.

## 7. Regras de pareamento, métricas, custo-perda e critério de usabilidade

Todas as métricas abaixo estão implementadas em `vitirule_v2/metrics.py` e congeladas em `v2-freeze`.

### 7.1 Pareamento temporal um-para-um e tolerâncias

Eventos da referência medida e de cada fonte candidata são pareados um-para-um por busca gulosa ordenada pela menor distância temporal absoluta dentro de tolerâncias fixas:

- **Regra 3-10 e Goidànich: `±2 dias`.** A incubação do míldio da videira leva de 4 a 13 dias, de modo que um desvio de até 2 dias ainda permite posicionar uma pulverização preventiva ou pós-infecção inicial antes da esporulação.
- **Tabela revisada de Mills: `±24 horas` sobre `light_ts`.** Fungicidas pós-infecção contra a sarna da macieira perdem eficácia após cerca de 24 a 48 horas do início da infecção, exigindo que o alerta capture o mesmo evento de molhamento dentro de 24 horas.
- **TOM-CAST no modo `self_reset`: `±3 dias`.** Os intervalos entre pulverizações de 15 DSV no tomateiro duram em geral de 7 a 14 dias, logo um desvio de até 3 dias ainda vincula o alerta ao mesmo ciclo operacional de proteção.

No modo `reference_reset` do TOM-CAST não há pareamento livre: avalia-se diretamente, em cada intervalo não mascarado encerrado por uma pulverização da referência, se a candidata atingiu `15 DSV` até a data de referência, a antecipação em dias e o erro de DSV acumulado naquela data.

### 7.2 Métricas principais e convenção de sinal

- **Taxa de alertas perdidos:** `FN / (TP + FN)`, fração dos eventos de referência não detectados pela fonte dentro da tolerância.
- **Razão de alarmes falsos, FAR:** `FP / (TP + FP)`, fração dos alertas emitidos pela fonte que não correspondem a nenhum evento de referência dentro da tolerância.
- **F1 de eventos:** `2 * TP / (2 * TP + FP + FN)`.
- **Atraso com sinal:** `t_candidata - t_referência`, medido em dias e expresso em fração de dia para Mills horária. O sinal é **positivo quando a fonte alerta depois da referência** e negativo quando antecipa. Reportam-se a mediana e o intervalo interquartil `P25` a `P75`.
- **Concordância de severidade em Mills:** entre os pares detectados, fração de acerto exato entre leve, moderada e severa e fração de subestimativa de severidade.
- **Incerteza:** intervalos de confiança de 95% por bootstrap em bloco por estação com `2.000` reamostragens e semente fixa `20261122`, mantendo juntas todas as safras de cada estação sorteada. Quando a rede tem menos de 3 estações, como no Politecnico com 2 estações aprovadas, o bootstrap não roda e os números saem apenas como descritivos.

### 7.3 Modelo de custo-perda com decisão diária

Seguindo Richardson (2000) e Kim, Beresford & Henshall (2008), a unidade de decisão é **cada dia não mascarado** dentro da janela fenológica da cultura. Em cada dia monta-se a tabela de contingência 2 por 2 completa entre alerta da referência e alerta da candidata: acertos `a`, alarmes falsos `b`, alertas perdidos `c` e **acertos negativos `d`**, somando `N = a + b + c + d` dias e frequência climatológica `s = (a + c) / N`.

Para razões de custo sobre perda $r = C / L \in \{0{,}05;\, 0{,}10;\, 0{,}20\}$, o custo médio normalizado por dia da candidata é $E_{\text{cand}} = [(a + b)r + c] / N$, o custo da melhor estratégia fixa entre sempre e nunca pulverizar é $E_{\text{fixa}} = \min(r, s)$ e o custo sob informação perfeita da referência medida é $E_{\text{perf}} = s \cdot r$. O valor econômico relativo é:

$$V(r) = \frac{E_{\text{fixa}} - E_{\text{cand}}}{E_{\text{fixa}} - E_{\text{perf}}}$$

Valores próximos de `1` indicam desempenho próximo ao do sensor medido, `0` equivale à melhor estratégia fixa e valores negativos indicam desempenho pior que adotar uma regra fixa sem previsão.

### 7.4 Critério pré-registrado de usabilidade

Uma fonte meteorológica será classificada como **usável** para uma regra se, no **conjunto confirmatório**, atender simultaneamente às quatro condições abaixo:

1. Taxa de alertas perdidos de no máximo **20%**.
2. Razão de alarmes falsos, FAR, de no máximo **30%**.
3. Atraso mediano com sinal de no máximo **1,0 dia**.
4. Limite superior do intervalo de confiança de 95% da taxa de alertas perdidos estritamente abaixo de **30%**.

## 8. Registro de emendas e desvios do pré-registro

### Emenda 1: 22 nov 2026, antes de `v2-freeze` e antes de rodar qualquer fonte candidata

- **O que mudou:** substituiu-se a reprovação automática por lacuna contínua acima de `24 h` pelo mascaramento da lacuna acrescido de um período de aquecimento pós-lacuna igual à memória máxima de cada regra, mantendo inalterados a cobertura mínima de `95,0%` e todos os testes físicos e de deriva do sensor.
- **Motivo:** a aplicação cega da regra de `24 h` na Fase 1 descartou três estações-safra do INRAE em 2022 que possuíam cobertura acima de `95%` e sensores limpos, apenas por uma única falha breve de telemetria entre `46 h` e `115 h`.
- **Períodos de aquecimento derivados de `params.json`:** `48 h` na Regra 3-10; `48 h` mais exclusão exata de coortes que toquem hora faltante em Goidànich; `9 h` em Mills pela soma de `8 h` de interrupção seca e `1 h` de recuo de chuva; exclusão exata de intervalos de pulverização que toquem dia faltante no TOM-CAST.
- **Sensibilidade:** `gap_policy="reject_24h"` permanece calculada como análise secundária.

### Emenda 2: 22 nov 2026, antes de `v2-freeze` e antes de rodar qualquer fonte candidata

- **O que mudou:** na Regra 3-10 em `vitirule_v2/rules/params.json`, a agregação térmica primária passou de temperatura média diária `daily_mean >= 10 °C`, usada em `v2-rules`, para **temperatura mínima diária `daily_min >= 10 °C`**.
- **Motivo:** conferência bibliográfica da formulação clássica italiana de Baldacci (1947), Goidànich (1964) e Rossi et al. (2008). A versão `daily_mean` segue reportada como análise secundária.

### Emenda 3: 22 nov 2026, antes de `v2-freeze`

- **O que mudou:** o lockbox de 20% foi substituído pelo **conjunto confirmatório completo**, formado por todas as estações novas do INRAE que passarem no controle de qualidade cego, rodando uma única vez após `v2-freeze` na tag `v2-confirmatory`.
- **Motivo:** como o desenvolvimento termina em `v2-freeze` sem uso prévio do lote novo do INRAE, reservar apenas 20% desperdiçaria poder estatístico. Usar todo o lote novo como conjunto confirmatório maximiza a precisão dos intervalos de confiança de 95% mantendo separação total do desenvolvimento.

### Correção técnica pós-`v2-freeze`: 22 nov 2026, parâmetro da API Open-Meteo Archive e grade do ERA5 combinado

- **O que aconteceu:** houve uma primeira rodada exploratória após `v2-freeze` com a coleta original em `models=era5_land`, cujo resultado foi visto e acusou zero alertas em 3-10, Goidànich e Mills para essa fonte. A inspeção dos arquivos em cache mostrou que `models=era5_land` no endpoint `archive-api.open-meteo.com/v1/archive` retorna `null` em 100% das horas de `precipitation`, `wind_speed_10m` e `shortwave_radiation`.
- **O que mudou:** em `vitirule_v2/sources/open_meteo.py`, trocamos o parâmetro de coleta para `models=era5_seamless` com trava automática contra precipitação inteiramente nula, tratando o ajuste estritamente como correção de coleta, sem nenhuma mudança de regra, limiar, tolerância ou métrica.
- **Descrição corrigida da fonte:** segundo a documentação do Open-Meteo, `era5_seamless` combina temperatura e umidade relativa do ERA5-Land na grade de `0,1 grau` com precipitação, vento e radiação do ERA5 na grade de `0,25 grau`. Por isso a fonte passa a ser designada como **ERA5 combinado: T e UR do ERA5-Land, chuva, vento e radiação do ERA5**, registrando em `grid_metadata` a distância horizontal e a diferença de altitude tanto do ponto ERA5-Land de `0,1 grau` quanto do ponto ERA5 de `0,25 grau` usado para a chuva.
