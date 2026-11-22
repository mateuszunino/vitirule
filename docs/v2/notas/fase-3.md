# Nota de método: Fase 3, avaliação exploratória

> **Estado:** avaliação **exploratória** concluída após a tag `v2-freeze` sobre as 4 estações locais do INRAE e as 2 estações aprovadas do Politecnico di Torino. O **conjunto confirmatório** formado por todas as estações novas do INRAE aprovadas no QC cego segue pendente porque o portal `entrepot.recherche.data.gouv.fr` permaneceu em HTTP 503 em 22 nov 2026; assim que voltar e a licença for confirmada, o conjunto confirmatório rodará uma única vez na tag `v2-confirmatory`.

## O que foi feito

1. **Fechamento do pré-registro e congelamento em `v2-freeze`:** completamos a seção 7 de `docs/v2/preregistro.md` com tolerâncias de pareamento justificadas agronomicamente, razão de alarmes falsos, atraso com sinal, modelo de custo-perda diário com acertos negativos, critério binário de usabilidade, análise primária única e substituição do lockbox de 20% pelo conjunto confirmatório completo. Implementamos `vitirule_v2/metrics.py`, `scripts/v2_evaluate.py` e `tests/test_v2_metrics.py`, fechando a tag anotada `v2-freeze` no commit `52a850a` antes de rodar qualquer comparação entre fontes.
2. **Correção técnica transparente pós-`v2-freeze`:** houve uma primeira rodada exploratória com `models=era5_land` no Open-Meteo Archive cujo resultado foi visto e devolveu zero alertas em 3-10, Goidànich e Mills porque o endpoint retorna 100% de valores `null` em precipitação, vento e radiação para esse parâmetro. Corrigimos a coleta em `vitirule_v2/sources/open_meteo.py` para `models=era5_seamless`, com trava automática contra precipitação nula e teste de regressão em `tests/test_v2_phase2.py`, sem alterar nenhuma regra, limiar, tolerância ou métrica. Segundo a documentação do Open-Meteo, `era5_seamless` junta temperatura e umidade relativa do ERA5-Land na grade de `0,1 grau` com precipitação, vento e radiação do ERA5 na grade de `0,25 grau`. Por isso a fonte aparece renomeada como **ERA5 combinado: T e UR do ERA5-Land, chuva, vento e radiação do ERA5**, com registro separado da distância e da diferença de altitude do ponto ERA5 de `0,25 grau` em `grid_metadata`. A correção foi registrada na seção 8 de `docs/v2/preregistro.md`. A suíte completa soma **175 testes passando**, sendo 69 da v1 e 106 da v2.
3. **Execução exploratória:** rodamos `scripts/v2_evaluate.py --split exploratory` sobre a análise primária única e todas as análises secundárias declaradas.

## Análise primária única, conjunto exploratório INRAE, 2022–2025

Especificação primária congelada: janela pareada `2022–2025`, estimador de molhamento `rh90_rain`, Regra 3-10 com `daily_min`, controle de qualidade `mask_with_warmup`. Nas tabelas abaixo, **ERA5 combinado** designa a fonte **ERA5 combinado: T e UR do ERA5-Land, chuva, vento e radiação do ERA5**. Amostra exploratória do INRAE: 4 estações, somando 14 estações-safra em videira e tomateiro e 16 em macieira. Como há apenas 4 estações no conjunto exploratório, o bootstrap em bloco por estação produz intervalos discretos e grosseiros, que só ganharão poder inferencial no conjunto confirmatório.

| Regra | Fonte candidata | Ref. / Cand. | Perdidos, IC 95% | FAR | F1 | Atraso mediano, IQR | Valor custo-perda `0,05` / `0,10` / `0,20` | Critério usável, exploratório |
|---|---|---:|---|---:|---:|---|---|---|
| Regra 3-10 | Estação sem sensor | 130 / 130 | 0,0% `[0,0; 0,0]` | 0,0% | 1,000 | 0,0 d `[0,0; 0,0]` | `1,00` / `1,00` / `1,00` | Sim |
| Regra 3-10 | Historical Forecast | 130 / 151 | 26,2% `[23,1; 37,7]` | 36,4% | 0,683 | 0,0 d `[0,0; 0,0]` | `0,44` / `0,43` / `0,33` | Não |
| Regra 3-10 | NASA POWER | 130 / 143 | 29,2% `[16,3; 47,3]` | 35,7% | 0,674 | 0,0 d `[0,0; 0,0]` | `0,37` / `0,36` / `0,26` | Não |
| Regra 3-10 | ERA5 combinado | 130 / 179 | 25,4% `[19,3; 31,2]` | 45,8% | 0,628 | 0,0 d `[0,0; 0,0]` | `0,40` / `0,38` / `0,25` | Não |
| Goidànich | Estação sem sensor | 119 / 119 | 0,0% `[0,0; 0,0]` | 0,0% | 1,000 | 0,0 d `[0,0; 0,0]` | `1,00` / `1,00` / `1,00` | Sim |
| Goidànich | Historical Forecast | 119 / 134 | 29,4% `[24,3; 45,8]` | 37,3% | 0,664 | 0,0 d `[0,0; 0,0]` | `0,46` / `0,43` / `0,34` | Não |
| Goidànich | ERA5 combinado | 119 / 158 | 25,2% `[16,7; 37,3]` | 43,7% | 0,643 | 0,0 d `[-1,0; 0,0]` | `0,35` / `0,29` / `0,16` | Não |
| Goidànich | NASA POWER | 119 / 129 | 34,5% `[22,3; 52,5]` | 39,5% | 0,629 | 0,0 d `[0,0; 0,0]` | `0,36` / `0,32` / `0,22` | Não |
| Mills revisada | Estação sem sensor | 249 / 237 | 16,9% `[11,9; 20,7]` | 12,7% | 0,852 | 0,0 d `[0,0; 0,06]` | `0,11` / `0,56` / `0,69` | **Sim** |
| Mills revisada | Historical Forecast | 249 / 270 | 31,7% `[18,0; 48,4]` | 37,0% | 0,655 | -0,04 d `[-0,17; 0,04]` | `-0,58` / `0,20` / `0,41` | Não |
| Mills revisada | ERA5 combinado | 249 / 326 | 34,5% `[32,4; 36,2]` | 50,0% | 0,567 | -0,17 d `[-0,44; -0,04]` | `-0,99` / `-0,02` / `0,22` | Não |
| Mills revisada | NASA POWER | 249 / 258 | 61,9% `[58,0; 65,2]` | 63,2% | 0,375 | -0,46 d `[-0,71; -0,25]` | `-1,90` / `-0,45` / `-0,06` | Não |
| TOM-CAST `self_reset` | Estação sem sensor | 47 / 40 | 57,5% `[44,7; 70,0]` | 50,0% | 0,460 | 0,0 d `[-1,0; 1,0]` | `0,13` / `0,09` / `0,00` | Não |
| TOM-CAST `self_reset` | ERA5 combinado | 47 / 98 | 44,7% `[37,0; 55,0]` | 73,5% | 0,359 | 0,0 d `[-1,0; 2,0]` | `0,00` / `-0,11` / `-0,39` | Não |
| TOM-CAST `self_reset` | Historical Forecast | 47 / 54 | 63,8% `[59,1; 68,1]` | 68,5% | 0,337 | -1,0 d `[-3,0; 0,0]` | `0,05` / `-0,01` / `-0,15` | Não |
| TOM-CAST `self_reset` | NASA POWER | 47 / 193 | 17,0% `[10,0; 25,0]` | 79,8% | 0,325 | 0,0 d `[-1,5; 1,0]` | `0,08` / `-0,15` / `-0,68` | Não |

Em Mills revisada, a concordância exata da classe de severidade entre pares detectados foi de `65,7%` na estação sem sensor com `24,6%` de subestimativa, `51,8%` no Historical Forecast com `24,7%` de subestimativa, `44,8%` no ERA5 combinado e `31,6%` no NASA POWER.

### Leitura conjunta do TOM-CAST: `reference_reset` versus `self_reset`

Os dois modos do TOM-CAST respondem a perguntas diferentes e devem ser lidos em conjunto. O modo **`reference_reset`** mede a **fidelidade da entrada meteorológica**: em cada intervalo delimitado pelas pulverizações reais da referência, a fonte candidata parte do mesmo zero e avalia-se apenas quanto o seu DSV acumulado se afasta dos `15 DSV` até aquela data. Já o modo **`self_reset`** mede a **divergência operacional**: quando uma pulverização atrasa ou antecipa, o zeramento do contador também se desloca, tirando de fase todos os ciclos seguintes e propagando o erro até o fim da safra.

A estação local sem sensor ilustra bem esse mecanismo nos 47 intervalos do INRAE. Em `reference_reset`, seu erro médio é modesto, apenas `-1,02 DSV` por intervalo, mas esse déficit pequeno já basta para que só `38,3%` dos intervalos atinjam `15 DSV` até a data da referência. Quando o mesmo déficit roda livremente em `self_reset`, o primeiro atraso desloca o zeramento seguinte e descasa o calendário inteiro: os alertas perdidos saltam para `57,5%` e a razão de alarmes falsos vai a `50,0%`, porque aplicações atrasadas passam a cair fora da tolerância de `±3 dias` dos ciclos seguintes. Nas fontes em grade, o erro de entrada já é grande em `reference_reset`: o Historical Forecast atingiu `15 DSV` em `61,7%` dos intervalos com viés médio de `+2,85 DSV` e antecipação mediana de `-10 dias`; o ERA5 combinado atingiu `91,5%` com excesso médio de `+14,91 DSV` e antecipação de `-14 dias`; o NASA POWER atingiu `100%` com excesso médio de `+38,94 DSV` por intervalo, antecipação de `-19 dias` e `8` alarmes falsos extras no fim da safra.

## Análise primária única, conjunto exploratório Politecnico di Torino, descritivo sem IC

Estes números derivam de dados sob licença CC BY-NC 4.0 do DOI `10.17632/sd4b8vpvyb.1`, sem redistribuição de dados brutos. Com apenas 2 estações aprovadas no QC, `site1` e `site5` em 2022, os resultados são estritamente descritivos e não possuem intervalos de confiança nem teste de usabilidade:

- **Regra 3-10, 11 eventos:** ERA5 combinado perdeu `18,2%` com FAR de `25,0%`, F1 `0,783` e `V(0,10) = 0,48`; Historical Forecast perdeu `54,6%` com FAR `50,0%` e F1 `0,476`; NASA POWER perdeu `54,6%` com FAR `37,5%` e F1 `0,526`.
- **Goidànich, 9 ciclos:** ERA5 combinado perdeu `11,1%` com FAR `27,3%` e F1 `0,800`; Historical Forecast perdeu `55,6%` com FAR `55,6%`; NASA POWER perdeu `55,6%` com FAR `42,9%`.
- **Mills revisada, 12 eventos:** estação sem sensor perdeu `41,7%` com FAR `50,0%` e F1 `0,539`; Historical Forecast perdeu `16,7%` com FAR `63,0%` e F1 `0,513`; ERA5 combinado perdeu `25,0%` com FAR `62,5%` e F1 `0,500`; NASA POWER perdeu `41,7%` com FAR `70,8%` e F1 `0,389`.
- **TOM-CAST `self_reset`, 12 pulverizações:** estação sem sensor emitiu apenas `5` pulverizações com `91,7%` perdidas e erro médio de `-9,17 DSV` em `reference_reset`; ERA5 combinado perdeu `50,0%` com FAR `45,5%`; Historical Forecast perdeu `75,0%` com FAR `66,7%`; NASA POWER emitiu `24` pulverizações com FAR `66,7%` e excesso médio de `+14,08 DSV`.

## Principais padrões nas análises secundárias do INRAE

1. **Trocar o estimador de molhamento não salva as fontes em grade nem o TOM-CAST:** na análise secundária com `dpd_hysteresis` de Gillespie et al. (1993) e `cart_kim2002`, a estação sem sensor continuou passando em Mills revisada com F1 de `0,840` e `0,846`, enquanto todas as fontes em grade seguiram fora do critério de usabilidade em Mills e no TOM-CAST, com FAR entre `74,3%` e `81,3%` no TOM-CAST.
2. **Previsão real degrada visivelmente em relação à quase-análise:** na análise secundária B de `2024–2025` com `Open-Meteo Previous Runs`, passar do `Historical Forecast` para horizontes reais de 1 a 3 dias elevou os alertas perdidos da Regra 3-10 de `24,7%` para `35,1%` a `36,4%`, de Goidànich de `29,0%` para `39,1%` e de Mills de `30,2%` para `38,0%` com FAR chegando a `50,0%` no dia 3. O valor econômico relativo em `C/L = 0,10` caiu de `0,47` para `0,25` na 3-10 e de `+0,20` para `-0,06` em Mills.
3. **Estabilidade nas sensibilidades:** a série longa de 7 safras em `2019–2025` sem Historical Forecast, a sensibilidade `reject_24h` e a versão `daily_mean` da Regra 3-10 reproduziram exatamente o mesmo ordenamento entre fontes e a mesma conclusão sobre usabilidade.

## Metadados de grade corrigidos do ERA5 combinado

Como `era5_seamless` combina temperatura e umidade relativa do ERA5-Land na grade de `0,1 grau` com precipitação, vento e radiação do ERA5 na grade de `0,25 grau`, `scripts/v2_fetch_sources.py` passou a registrar os dois pontos de grade em `grid_metadata`. Para o ponto ERA5 de `0,25 grau`, a altitude foi consultada na coordenada exata do centro da célula de `0,25 grau` via `/v1/elevation`, pois o cabeçalho `elevation` do Open-Meteo Archive devolve o modelo digital na coordenada da estação e não no centro da célula de chuva.

| Rede e estação | Altitude estação | ERA5-Land `0,1°`, T e UR: dist. / Δ alt. | ERA5 `0,25°`, chuva, vento e radiação: dist. / Δ alt. |
|---|---:|---:|---:|
| INRAE `33080002` Bordeaux-Couhins | 20 m | 6,11 km / +5,0 m | 4,81 km / -17,0 m |
| INRAE `68066002` Alsace-Colmar | 200 m | 4,56 km / +1,0 m | 9,31 km / +337,0 m |
| INRAE `51242002` Champagne-Fagnières | 102 m | 5,63 km / +2,0 m | 7,28 km / -26,0 m |
| INRAE `21106002` Bourgogne-Bretenière | 211 m | 4,36 km / 0,0 m | 7,82 km / +38,0 m |
| Politecnico `site1` | 125 m | 1,36 km / -2,0 m | 12,45 km / +189,0 m |
| Politecnico `site2`, reprovada QC | 33 m | 2,46 km / 0,0 m | 15,02 km / +281,0 m |
| Politecnico `site3`, reprovada QC | 242 m | 3,65 km / 0,0 m | 8,95 km / +260,0 m |
| Politecnico `site4`, reprovada QC | 258 m | 4,24 km / -7,0 m | 2,03 km / -41,0 m |
| Politecnico `site5` | 187 m | 3,10 km / -9,0 m | 6,76 km / +31,0 m |
| Politecnico `site6`, reprovada QC | 434 m | 5,13 km / -30,0 m | 8,89 km / +264,0 m |
| Politecnico `site7`, reprovada QC | 418 m | 8,29 km / -32,0 m | 9,32 km / +280,0 m |

Em Alsace-Colmar, o ponto ERA5 de `0,25 grau` usado para a precipitação cai a `9,31 km` nos contrafortes dos Vosges, `+337 m` acima da estação, reforçando por que a precipitação do ERA5 combinado diverge tanto da chuva local em relevo acidentado.

## O que este resultado exploratório mostra e onde pode falhar

- **A estrutura matemática da regra governa onde a fonte gratuita falha:** em regras de chuva e temperatura como 3-10 e Goidànich, o gargalo está na chuva convectiva mal localizada em grade, produzindo `25%` a `35%` de alertas perdidos e `36%` a `46%` de alarmes falsos mesmo sem depender de molhamento foliar. Em Mills revisada, manter a estação local sem sensor já basta para atingir `F1 = 0,852` e passar no critério exploratório, porque a chuva medida no local ancora o início do evento. Já no TOM-CAST, um acumulador com memória de vários dias sem âncora de chuva amplifica qualquer pequeno viés diário de molhamento: na estação sem sensor sob `rh90_rain` o erro acumula viés seco de `-1,02 DSV` e desalinha os zeramentos em `self_reset`, enquanto no ERA5 combinado e no NASA POWER o viés úmido multiplica as pulverizações em 2 a 4 vezes e gera valor econômico negativo.
- **Caráter exploratório e amostra reduzida:** enquanto o portal do INRAE seguir em HTTP 503, estes números vêm apenas de 4 estações francesas e 2 italianas. Nenhuma afirmação definitiva sobre usabilidade pode ser feita antes da execução única do conjunto confirmatório na tag `v2-confirmatory`.
- **Diferença de unidade entre eventos e custo-perda diário:** em Mills revisada, um evento horário deslocado em poucas horas perto da meia-noite muda de dia civil e conta como erro no custo-perda diário mesmo quando pareado dentro de `±24 h`. Reportar as duas métricas lado a lado evita mascarar esse efeito.

## Referências principais da Fase 3

- Gillespie, T. J., Srivastava, B., & Pitblado, R. E. (1993). *Journal of Applied Meteorology*, 32(3), 567–573. https://doi.org/10.1175/1520-0450(1993)032<0567:UOWDTS>2.0.CO;2
- Kim, K. S., Beresford, R. M., & Henshall, W. R. (2008). *New Zealand Plant Protection*, 61, 296–300. https://doi.org/10.30843/nzpp.2008.61.6839
- Kim, K. S., Taylor, S. E., Gleason, M. L., & Koehler, K. J. (2002). *Plant Disease*, 86(2), 179–185. https://doi.org/10.1094/PDIS.2002.86.2.179
- Richardson, D. S. (2000). *Quarterly Journal of the Royal Meteorological Society*, 126(563), 649–667. https://doi.org/10.1002/qj.49712656313
