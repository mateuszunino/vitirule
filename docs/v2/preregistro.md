# Pré-registro experimental do vitirule v2

> **Estado:** EM CONSTRUÇÃO, com seções 1 a 6 fechadas nas Fases 1 e 2. A seção 7 será completada na Fase 3 antes do congelamento final na tag `v2-freeze`, antes de abrir qualquer métrica comparativa entre fontes ou rodar o lockbox.

## 1. Pergunta de pesquisa e escopo

O vitirule v2 responde a uma pergunta específica: **quanto se pode confiar num alerta de doença calculado com dado meteorológico gratuito, e onde ele falha?**

O projeto não mede eficácia de controle no campo nem simula progresso epidêmico. O protocolo do míldio da v1 permanece congelado no repositório como estudo de caso 1, acompanhado da errata `v1.0.1`. A v2 mede exclusivamente a confiabilidade da entrada meteorológica em quatro regras clássicas publicadas, comparando cada fonte candidata contra a mesma regra alimentada pelos dados medidos na própria estação com sensor físico de molhamento foliar.

## 2. Escopo das estações e separação por rede

As estações meteorológicas das redes INRAE AgroClim na França e Politecnico di Torino na Itália são estações agrometeorológicas de pesquisa ou de vinhedo, não pomares de macieira nem lavouras comerciais de tomate. Rodar a tabela revisada de Mills e o TOM-CAST sobre essas séries mede a fidelidade da entrada meteorológica diante de regras com estruturas matemáticas distintas, não o risco fitossanitário real da macieira ou do tomateiro naquela coordenada.

Por esse motivo, todos os resultados serão reportados separadamente por rede de referência, sem agregação cega entre INRAE AgroClim, Politecnico di Torino e, na Fase 4, Epagri/Ciram.

## 3. Regras publicadas e parâmetros

Todas as constantes, tabelas, divergências da literatura, escolhas adotadas e citações primárias estão centralizadas em `vitirule_v2/rules/params.json`.

1. **Regra 3-10 para míldio da videira:** baseada em Baldacci (1947), Goidànich (1964) e na descrição operacional revista por Rossi et al. (2008). Dispara alerta de infecção primária quando a data está dentro da janela fenológica da videira, a **temperatura mínima diária local** é maior ou igual a `10,0 °C` conforme Emenda 2 abaixo, a precipitação acumulada em 48 horas atinge pelo menos `10,0 mm` e há chuva ativa no dia do disparo de pelo menos `0,2 mm`. Dias consecutivos que satisfazem o critério são agrupados num único evento datado pelo primeiro dia de disparo. A versão original de `v2-rules` com temperatura média diária é mantida como comparação pareada documentada na seção 8.
2. **Calendário de incubação de Goidànich para míldio da videira:** baseado em Müller & Sleumer (1934) e Goidànich (1964). Cada evento primário 3-10 inicia uma coorte de incubação em 0% no dia seguinte ao disparo, somando o progresso diário interpolado linearmente pela tabela publicada em função da temperatura média diária, multiplicado por `0,85` quando a umidade relativa média diária fica abaixo de `75%`. O evento principal de alerta ocorre no dia em que o acumulado atinge `100%`. O marco preventivo de `80%` é registrado como metadado auxiliar.
3. **Tabela revisada de Mills para sarna da macieira:** baseada em MacHardy & Gadoury (1989) com extensão de baixas temperaturas de Stensvand et al. (1997) e tabela operacional da OMAFRA. Avalia eventos horários de molhamento dentro da janela primária da macieira iniciados ou acompanhados por pelo menos `0,2 mm` de chuva acumulada no evento. Períodos molhados separados por interrupção seca de até `8 horas` consecutivas são combinados num único evento, contando apenas as horas molhadas para a duração e para a temperatura média. Interrupções secas acima de `8 horas` reiniciam a contagem. Classifica cada evento em infecção leve, moderada ou severa conforme a tabela publicada.
4. **TOM-CAST para pinta-preta do tomate:** baseado em Madden, Pennypacker & MacNab (1978), Pitblado (1988, 1992) e Gillespie, Srivastava & Pitblado (1993). Calcula o DSV diário de 0 a 4 na janela de 12h a 12h no fuso local usando a matriz publicada sobre as horas molhadas e a temperatura média molhada arredondada pelo critério aritmético half-up. Dispara pulverização quando o DSV acumulado atinge `15`. Será avaliado nos dois modos de memória: reset autônomo controlado pela própria fonte candidata e reset sincronizado às datas de pulverização da referência medida.

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

## 5. Janela temporal pareada, qualidade de dados e lockbox

### 5.1 Comparação pareada principal e análises secundárias

A análise principal usa exclusivamente estações-safra em que todas as quatro fontes candidatas principais existem: estação local sem sensor de molhamento, ERA5-Land, Open-Meteo Historical Forecast e NASA POWER.

- **Análise principal pareada:** anos de **2022 a 2025**, primeiro ano civil completo com cobertura operacional do Historical Forecast para todas as estações das duas redes. Cobre quatro safras por estação no INRAE e todas as estações aprovadas do Politecnico di Torino.
- **Análise secundária A, série longa sem Historical Forecast:** anos de **2019 a 2025** no INRAE, comparando estação sem sensor, ERA5-Land e NASA POWER em sete safras.
- **Análise secundária B, previsão real com horizonte fixo:** anos de **2024 a 2025** com `Open-Meteo Previous Runs` nos horizontes de 1, 2 e 3 dias de antecedência, separada por rede.

### 5.2 Controle de qualidade, mascaramento de lacunas e separação de lockbox

Os critérios objetivos de qualidade estão em `docs/v2/criterios_qualidade.md` e implementados em `vitirule_v2/qc.py`. Mantemos o piso de **95,0% de cobertura válida** e todos os testes físicos e de deriva de sensor. Conforme a Emenda 1 registrada na seção 8, lacunas contínuas acima de 24 horas não reprovam a estação-safra se a cobertura global seguir em 95,0% ou mais; em vez disso, a lacuna e um período de aquecimento pós-lacuna igual à memória máxima de cada regra ficam mascarados, e qualquer evento cujo cálculo toque uma hora mascarada sai da referência e de todas as candidatas. A regra original de reprovação rígida acima de 24 horas fica preservada como análise de sensibilidade.

As 4 estações do INRAE e as 7 estações do Politecnico usadas na v1 ficam obrigatoriamente fora do lockbox, pois já participaram da avaliação de estimadores na v1. Todas as estações-safra aprovadas do Politecnico ficam no conjunto de desenvolvimento. O lockbox em `docs/v2/lockbox.txt` será sorteado exclusivamente entre as estações novas do INRAE aprovadas no controle de qualidade, com 20% das estações e mínimo de 2 estações, estratificado por região quando o número permitir, com semente fixa registrada no commit do sorteio.

### 5.3 Metadados espaciais e padrão temporal das fontes candidatas

- Todas as fontes são alinhadas em **UTC**. Na API horária do NASA POWER, o padrão da API sem parâmetro explícito é Local Solar Time, portanto o coletor exige `time-standard=UTC` em toda chamada e valida `header.time_standard == "UTC"` ao ler a resposta.
- Para cada estação e cada fonte em grade, registramos a distância horizontal em quilômetros até o ponto de grade servido e a diferença de altitude entre a grade e a estação. **Nenhuma correção de altitude entra na análise principal.**

## 6. Estimadores de molhamento foliar

Para limitar comparações múltiplas e evitar seleção pós-hoc, fixamos uma hierarquia explícita de estimadores puros de molhamento foliar em `vitirule_v2/lwd.py`, nenhum deles lendo o sensor físico da estação:

1. **Estimador primário:** `rh90_rain`, que marca a hora como molhada quando `UR >= 90,0%` ou `precipitação > 0,0 mm/h`. Todas as comparações principais entre fontes meteorológicas na Fase 3 usam este estimador como linha primária.
2. **Estimadores secundários com parâmetros publicados fixos:**
   - `dpd_hysteresis`: depressão do ponto de orvalho com início em `DPD <= 1,8 °C` e secagem em `DPD >= 3,8 °C`, além de chuva acima de zero, usando os parâmetros publicados por Gillespie, Srivastava & Pitblado (1993).
   - `cart_kim2002`: árvore de classificação e regressão publicada por Kim, Taylor, Gleason & Koehler (2002) com seus coeficientes originais, ajustando vento de 10 m para 2 m via FAO-56 apenas nas fontes que entregam vento a 10 m.
3. **Modelo empírico recalibrado condicionado ao lote novo do INRAE:** enquanto o portal do INRAE permanecer em manutenção e o conjunto de desenvolvimento contar apenas com as 4 estações da v1, nenhum modelo recalibrado entra na análise, evitando sobreajuste com amostra insuficiente. Caso o lote completo do INRAE chegue antes da tag `v2-freeze`, um estimador recalibrado estritamente nas estações de desenvolvimento fora do lockbox poderá entrar como estimador secundário adicional.

## 7. Regras de pareamento de eventos e métricas

Pendente de definição na Fase 3 antes da tag `v2-freeze`: tolerâncias temporais de pareamento de alertas, definição de taxa de alertas perdidos, taxa de alarmes falsos, atraso mediano em dias, valor econômico de custo-perda simplificado e intervalos de confiança por bootstrap em bloco por estação.

## 8. Registro de emendas e desvios do pré-registro

### Emenda 1: 22 nov 2026, após contagens de QC da Fase 1 e antes de rodar qualquer fonte candidata

- **O que mudou:** substituiu-se a reprovação automática por lacuna contínua acima de `24 h` pelo mascaramento da lacuna acrescido de um período de aquecimento pós-lacuna igual à memória máxima de cada regra, mantendo inalterados a cobertura mínima de `95,0%` e todos os testes físicos e de deriva do sensor.
- **Motivo:** a aplicação cega da regra de `24 h` na Fase 1 descartou três estações-safra do INRAE em 2022 que possuíam cobertura acima de `95%` e sensores limpos, apenas por uma única falha breve de telemetria entre `46 h` e `115 h`.
- **Períodos de aquecimento derivados de `params.json`:**
  - **Regra 3-10:** `48 horas`, igual a `rain_window_hours`, garantindo que nenhuma soma móvel de 48 horas cruze a lacuna.
  - **Goidànich:** `48 horas` herdadas do gatilho 3-10 mais exclusão exata de qualquer coorte de incubação cujo intervalo do gatilho até `100%` toque uma hora faltante, com teto teórico de memória de `24 dias` a `10 °C` sob umidade baixa.
  - **Tabela revisada de Mills:** `9 horas`, soma de `max_dry_interruption_hours = 8 h` e `rain_initiation_lookback_hours = 1 h`. Após 9 horas válidas contínuas depois da lacuna, nenhum evento anterior pode se combinar nem disparar pelo recuo de 1 hora de chuva.
  - **TOM-CAST:** exclusão exata de qualquer intervalo de pulverização cuja acumulação toque um dia `12h–12h` com hora faltante, com teto teórico de memória de `15 dias` no limiar de `15 DSV` a `1 DSV/dia`.
- **Análise de sensibilidade:** a regra original de reprovação rígida acima de `24 h` permanece implementada como `gap_policy="reject_24h"` para verificação de sensibilidade.

### Emenda 2: 22 nov 2026, antes do congelamento da Fase 3 e antes de rodar qualquer fonte candidata

- **O que mudou:** na Regra 3-10 em `vitirule_v2/rules/params.json`, a agregação térmica primária passou de temperatura média diária `daily_mean >= 10 °C`, usada na tag `v2-rules`, para **temperatura mínima diária `daily_min >= 10 °C`**.
- **Motivo:** conferência bibliográfica da formulação italiana clássica de Baldacci (1947), Goidànich (1964) e da revisão de Rossi et al. (2008), que enunciam a regra como temperatura mínima não inferior a `10 °C` durante a chuva primária.
- **Reportagem das duas versões:** a referência medida na Fase 2 e todas as comparações da Fase 3 calcularão e reportarão tanto `daily_min` quanto a versão original `daily_mean` congelada em `v2-rules`.
