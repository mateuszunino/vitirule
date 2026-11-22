# Pré-registro experimental do vitirule v2

> **Estado:** RASCUNHO EM CONSTRUÇÃO. As seções 1 a 5 são fechadas na Fase 1 e congeladas na tag `v2-rules`. As seções 6 a 8 serão completadas nas Fases 2 e 3 antes do congelamento final na tag `v2-freeze`, antes de abrir qualquer métrica comparativa ou rodar o lockbox.

## 1. Pergunta de pesquisa e escopo

O vitirule v2 responde a uma pergunta específica: **quanto se pode confiar num alerta de doença calculado com dado meteorológico gratuito, e onde ele falha?**

O projeto não mede eficácia de controle no campo nem simula progresso epidêmico. O protocolo do míldio da v1 permanece congelado no repositório como estudo de caso 1, sem alterações. A v2 mede exclusivamente a confiabilidade da entrada meteorológica em quatro regras clássicas publicadas, comparando cada fonte candidata contra a mesma regra alimentada pelos dados medidos na própria estação com sensor físico de molhamento foliar.

## 2. Escopo das estações e separação por rede

As estações meteorológicas das redes INRAE AgroClim na França e Politecnico di Torino na Itália são estações agrometeorológicas de pesquisa ou de vinhedo, não pomares de macieira nem lavouras comerciais de tomate. Rodar a tabela revisada de Mills e o TOM-CAST sobre essas séries mede a fidelidade da entrada meteorológica diante de regras com estruturas matemáticas distintas, não o risco fitossanitário real da macieira ou do tomateiro naquela coordenada.

Por esse motivo, todos os resultados serão reportados separadamente por rede de referência, sem agregação cega entre INRAE AgroClim, Politecnico di Torino e, na Fase 4, Epagri/Ciram.

## 3. Regras publicadas e parâmetros congelados em `v2-rules`

Todas as constantes, tabelas, divergências da literatura, escolhas adotadas e citações primárias estão centralizadas em `vitirule_v2/rules/params.json`.

1. **Regra 3-10 para míldio da videira:** baseada em Baldacci (1947) e consolidação de Goidànich (1964). Dispara alerta de infecção primária quando a data está dentro da janela fenológica da videira, a temperatura média diária local é maior ou igual a `10,0 °C`, a precipitação acumulada em 48 horas atinge pelo menos `10,0 mm` e há chuva ativa no dia do disparo de pelo menos `0,2 mm`. Dias consecutivos que satisfazem o critério são agrupados num único evento datado pelo primeiro dia de disparo.
2. **Calendário de incubação de Goidànich para míldio da videira:** baseado em Müller & Sleumer (1934) e Goidànich (1964). Cada evento primário 3-10 inicia uma coorte de incubação em 0% no dia seguinte ao disparo, somando o progresso diário interpolado linearmente pela tabela publicada em função da temperatura média diária, multiplicado por `0,85` quando a umidade relativa média diária fica abaixo de `75%`. O evento principal de alerta ocorre no dia em que o acumulado atinge `100%`. O marco preventivo de `80%` é registrado como metadado auxiliar.
3. **Tabela revisada de Mills para sarna da macieira:** baseada em MacHardy & Gadoury (1989) com extensão de baixas temperaturas de Stensvand et al. (1997) e tabela operacional da OMAFRA. Avalia eventos horários de molhamento dentro da janela primária da macieira iniciados ou acompanhados por pelo menos `0,2 mm` de chuva acumulada no evento. Períodos molhados separados por interrupção seca de até `8 horas` consecutivas são combinados num único evento, contando apenas as horas molhadas para a duração e para a temperatura média. Interrupções secas acima de `8 horas` reiniciam a contagem. Classifica cada evento em infecção leve, moderada ou severa conforme a tabela publicada.
4. **TOM-CAST para pinta-preta do tomate:** baseado em Madden, Pennypacker & MacNab (1978), Pitblado (1988, 1992) e Gillespie, Srivastava & Pitblado (1993). Calcula o DSV diário de 0 a 4 na janela de 12h a 12h no fuso local usando a matriz publicada sobre as horas molhadas e a temperatura média molhada arredondada pelo critério aritmético padrão. Dispara pulverização quando o DSV acumulado atinge `15`. Será avaliado nos dois modos de memória: reset autônomo controlado pela própria fonte candidata e reset sincronizado às datas de pulverização da referência medida.

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

- **Análise principal pareada:** anos de **2022 a 2025**, primeiro ano civil completo com cobertura operacional do Historical Forecast para todas as estações das duas redes. Cobre quatro safras por estação no INRAE e todas as sete estações do Politecnico di Torino.
- **Análise secundária A, série longa sem Historical Forecast:** anos de **2019 a 2025** no INRAE, comparando estação sem sensor, ERA5-Land e NASA POWER em sete safras.
- **Análise secundária B, previsão real com horizonte fixo:** anos de **2024 a 2025** com `Open-Meteo Previous Runs` nos horizontes de 1, 2 e 3 dias de antecedência, separada por rede.

### 5.2 Controle de qualidade e separação de lockbox

Os critérios objetivos de qualidade de estações-safra estão aprovados e congelados em `docs/v2/criterios_qualidade.md`, sendo aplicados automaticamente por `vitirule_v2/qc.py` antes de qualquer análise de alertas.

As 4 estações do INRAE e as 7 estações do Politecnico usadas na v1 não podem entrar no lockbox, pois já participaram da avaliação de estimadores de molhamento na v1. Todas as estações-safra aprovadas do Politecnico ficam no conjunto de desenvolvimento. O lockbox em `docs/v2/lockbox.txt` será sorteado exclusivamente entre as estações novas do INRAE aprovadas no controle de qualidade, com 20% das estações e mínimo de 2 estações, estratificado por região se o número permitir, com semente fixa registrada no commit do sorteio.

## 6. Estimadores de molhamento foliar

Pendente de definição na Fase 2 antes da tag `v2-freeze`. Qualquer estimador calibrado com dados será ajustado estritamente nas estações de desenvolvimento, nunca no lockbox.

## 7. Regras de pareamento de eventos e métricas

Pendente de definição na Fase 3 antes da tag `v2-freeze`: tolerâncias temporais de pareamento de alertas, definição de taxa de alertas perdidos, taxa de alarmes falsos, atraso mediano em dias, valor econômico de custo-perda simplificado e intervalos de confiança por bootstrap em bloco por estação.

## 8. Registro de desvios do pré-registro

Nenhum desvio registrado até o congelamento de regras na tag `v2-rules`. Qualquer alteração posterior será registrada aqui com data, motivo e resultado das duas versões.
