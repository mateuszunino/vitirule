# Nota de método: Fase 2

## O que foi feito

1. **Emenda 1 no controle de qualidade:** atualizamos `vitirule_v2/qc.py`, `docs/v2/criterios_qualidade.md` e a seção 8 de `docs/v2/preregistro.md` mantendo intactos a cobertura mínima de `95,0%` e todos os testes físicos e de deriva do sensor, enquanto substituímos a reprovação rígida por lacuna contínua acima de `24 h` pelo mascaramento da lacuna acrescido do período de aquecimento igual à memória máxima de cada regra. A regra original de `24 h` permanece implementada em `gap_policy="reject_24h"` como análise de sensibilidade.
2. **Emenda 2 na temperatura da Regra 3-10:** após conferir Baldacci (1947), Goidànich (1964) e Rossi et al. (2008), atualizamos `vitirule_v2/rules/params.json` e `vitirule_v2/rules/downy_mildew.py` para adotar a temperatura mínima diária `daily_min >= 10,0 °C` como formulação primária emendada antes da Fase 3, mantendo `daily_mean >= 10,0 °C` da tag `v2-rules` em paralelo na referência medida e nas análises futuras.
3. **Estimadores de molhamento foliar em `vitirule_v2/lwd.py`:** fechamos a seção 6 de `docs/v2/preregistro.md` fixando `rh90_rain`, isto é `UR >= 90%` ou `precipitação > 0`, como estimador primário único para limitar comparações múltiplas. Como secundários de parâmetros fixos entraram `dpd_hysteresis`, citando Gillespie, Srivastava & Pitblado (1993) para os limiares de `1,8 °C` e `3,8 °C`, e `cart_kim2002` de Kim et al. (2002). O módulo usa somente biblioteca padrão Python e nunca lê o campo `wet` do sensor. Como o portal do INRAE seguiu em HTTP 503 em 22 nov 2026 e restam apenas as 4 estações da v1, o estimador empírico recalibrado saiu do plano da Fase 2 para evitar ajuste sobre amostra insuficiente.
4. **Coletores com cache em disco e metadados de grade em `vitirule_v2/sources/`:** implementamos `open_meteo.py`, `nasa_power.py` e `grid_metadata.py`, baixando e guardando em `data/v2_cache/`, fora do Git, as séries horárias de `ERA5-Land`, `Historical Forecast`, `Previous Runs` e `NASA POWER` para todas as 11 estações locais de desenvolvimento. No `NASA POWER`, confirmamos que o padrão da API horária sem o parâmetro `time-standard` é Local Solar Time, portanto o coletor exige `time-standard=UTC` em toda chamada e valida `header.time_standard == "UTC"` no retorno.
5. **Testes automatizados:** criamos `tests/test_v2_phase2.py` com **12 novos testes** cobrindo o mascaramento com aquecimento, a diferença entre `daily_min` e `daily_mean` na Regra 3-10, os três estimadores de molhamento, o bloqueio de respostas `LST` no NASA POWER, a conversão de radiação `MJ/h` para `W/m²`, o cache em disco e o cálculo de distância Haversine e diferença de altitude. A suíte completa passou com **166 testes**, somando 69 da v1 e 97 da v2.

Nenhuma fonte meteorológica candidata foi avaliada contra a referência medida nesta fase.

## Períodos de aquecimento derivados de `params.json` e resultado do novo QC

Os períodos de aquecimento pós-lacuna derivam diretamente dos parâmetros congelados em `vitirule_v2/rules/params.json`:

- **Regra 3-10:** `48 horas`, igual a `rain_window_hours`, impedindo que a soma móvel de 48 horas atravesse uma lacuna.
- **Goidànich:** `48 horas` herdadas do gatilho 3-10 somadas à exclusão exata de qualquer coorte de incubação cujo intervalo do gatilho até `100%` toque uma hora faltante, com teto teórico de memória de `24 dias` a `10 °C` com umidade baixa.
- **Tabela revisada de Mills:** `9 horas`, soma de `max_dry_interruption_hours = 8 h` e `rain_initiation_lookback_hours = 1 h`, assegurando que nenhum evento pré-lacuna se combine nem dispare pelo recuo de chuva.
- **TOM-CAST:** exclusão exata de qualquer intervalo de pulverização cuja acumulação toque um dia local `12h–12h` com hora faltante, com teto teórico de memória de `15 dias` no limiar de `15 DSV` a `1 DSV/dia`.

A tabela abaixo compara quantas estações-safra passam no controle de qualidade emendado contra a regra original de `24 h`. Os números do Politecnico di Torino derivam de dados sob licença CC BY-NC 4.0 do DOI `10.17632/sd4b8vpvyb.1`, sem redistribuição de dados brutos.

| Rede | Recorte | Cultura | Emenda `mask_with_warmup` | Sensibilidade `reject_24h` |
|---|---|---|---:|---:|
| INRAE local, 4 estações v1 | Principal 2022–2025 | Macieira | 16 / 16 | 12 / 16 |
| INRAE local, 4 estações v1 | Principal 2022–2025 | Videira | 14 / 16 | 11 / 16 |
| INRAE local, 4 estações v1 | Principal 2022–2025 | Tomateiro | 14 / 16 | 11 / 16 |
| INRAE local, 4 estações v1 | Secundário 2019–2021 | Macieira | 12 / 12 | 12 / 12 |
| INRAE local, 4 estações v1 | Secundário 2019–2021 | Videira | 10 / 12 | 10 / 12 |
| INRAE local, 4 estações v1 | Secundário 2019–2021 | Tomateiro | 10 / 12 | 10 / 12 |
| Politecnico di Torino, 7 estações | Principal 2022–2025 | Todas as culturas | 2 / 7 | 2 / 7 |

A emenda recuperou no INRAE principal as três safras limpas de 2022 em Bordeaux, Alsace e Bourgogne que antes caíam apenas por uma lacuna isolada de 46 a 115 horas, além da primavera de Bordeaux 2023 na macieira porque o travamento do sensor em Bordeaux 2023 começou em julho, após o fim da janela primária em 30 de junho. Todas as safras com deriva de sensor ou cobertura abaixo de 95% continuaram reprovadas: Bordeaux 2021, Bordeaux 2023 na videira e no tomateiro, Bordeaux 2024, Bourgogne 2021 e `site2`, `site3`, `site4`, `site6` e `site7` no Politecnico.

## Referência medida em 2022–2025 com as duas versões da Regra 3-10

| Rede | Regra 3-10 `daily_min`, emendada | Regra 3-10 `daily_mean`, original `v2-rules` | Goidànich completos `daily_min` / `daily_mean` | Mills revisada | TOM-CAST 15 DSV |
|---|---:|---:|---:|---:|---:|
| INRAE local, 14–16 estações-safra | 130 eventos, 5 a 16 por safra | 142 eventos, 5 a 18 por safra | 119 / 128 ciclos | 249 eventos | 47 pulverizações |
| Politecnico, 2 estações aprovadas, CC BY-NC 4.0 | 11 eventos, 5 a 6 por safra | 11 eventos, 5 a 6 por safra | 9 / 9 ciclos | 12 eventos | 12 pulverizações |

Exigir temperatura mínima diária de pelo menos `10,0 °C` reduziu em 12 o total de eventos 3-10 no INRAE em 2022–2025, de 142 para 130, refletindo chuvas frias de primavera com média diária acima de `10 °C` e mínima noturna abaixo desse patamar.

## Distância horizontal e diferença de altitude até os pontos de grade

Nenhuma correção de altitude entra na análise principal. A tabela abaixo registra a distância Haversine em quilômetros e a diferença de altitude, definida como altitude da grade menos altitude da estação, para todas as estações locais de desenvolvimento. Para o NASA POWER, a distância refere-se ao centro mais próximo da grade MERRA-2 de 0,5 por 0,625 grau e a altitude vem do campo `geometry.coordinates[2]` retornado pela API.

| Rede e estação | Altitude estação | ERA5-Land: dist. / Δ alt. | Historical Forecast: dist. / Δ alt. | NASA POWER MERRA-2: dist. / Δ alt. |
|---|---:|---:|---:|---:|
| INRAE `33080002` Bordeaux-Couhins | 20 m | 6,11 km / +5,0 m | 0,66 km / +5,0 m | 27,97 km / +18,4 m |
| INRAE `68066002` Alsace-Colmar | 200 m | 4,56 km / +1,0 m | 0,88 km / +1,0 m | 14,51 km / +167,6 m |
| INRAE `51242002` Champagne-Fagnières | 102 m | 5,63 km / +2,0 m | 0,65 km / +2,0 m | 7,14 km / +46,5 m |
| INRAE `21106002` Bourgogne-Bretenière | 211 m | 4,36 km / 0,0 m | 0,68 km / 0,0 m | 27,70 km / +71,7 m |
| Politecnico `site1` | 125 m | 1,36 km / -2,0 m | 2,66 km / -2,0 m | 12,45 km / +8,6 m |
| Politecnico `site2`, reprovada QC | 33 m | 2,46 km / 0,0 m | 5,53 km / 0,0 m | 15,02 km / +100,6 m |
| Politecnico `site3`, reprovada QC | 242 m | 3,65 km / 0,0 m | 1,21 km / 0,0 m | 19,68 km / +18,6 m |
| Politecnico `site4`, reprovada QC | 258 m | 4,24 km / -7,0 m | 2,44 km / -7,0 m | 2,03 km / -9,4 m |
| Politecnico `site5` | 187 m | 3,10 km / -9,0 m | 0,79 km / -9,0 m | 24,99 km / +301,4 m |
| Politecnico `site6`, reprovada QC | 434 m | 5,13 km / -30,0 m | 2,98 km / -30,0 m | 21,43 km / +160,3 m |
| Politecnico `site7`, reprovada QC | 418 m | 8,29 km / -32,0 m | 1,22 km / -32,0 m | 23,52 km / +176,3 m |

O Open-Meteo `Previous Runs` usa exatamente os mesmos pontos de grade e altitudes do `Historical Forecast`. A diferença de altitude mais acentuada aparece no NASA POWER em regiões de relevo próximo, como `+301,4 m` em `site5` no Piemonte e `+167,6 m` em Alsace-Colmar junto aos Vosges, onde a célula grosseira de cerca de 50 por 60 km média áreas montanhosas vizinhas. Esse registro explicará eventuais desvios térmicos sistemáticos do NASA POWER na Fase 3 sem aplicar correções pós-hoc.

## O que esta fase assume e onde pode falhar

- **Portal do INRAE ainda indisponível em HTTP 503:** enquanto `entrepot.recherche.data.gouv.fr` seguir fora do ar, o lote completo de 54 estações não pode ser baixado nem o `docs/v2/lockbox.txt` pode ser sorteado. A infraestrutura de coleta, cache, QC e estimadores já está pronta para processar o lote completo assim que o portal voltar e a licença for confirmada.
- **Atribuição de altitude das 4 estações do INRAE:** as altitudes das 4 estações locais foram obtidas do catálogo de metadados INRAE AgroClim em `20 m`, `200 m`, `102 m` e `211 m`, a serem conferidas contra o arquivo de metadados do próprio dataset DOI `10.57745/BQ0BWB` assim que o portal voltar.
- **Unidades de radiação e altura do vento:** o `NASA POWER` entrega vento já a `2 m` e radiação em `MJ/h`, convertida para `W/m²`, enquanto `ERA5-Land` e `Historical Forecast` entregam vento a `10 m`, ajustado para `2 m` pela equação FAO-56 apenas dentro do estimador secundário `cart_kim2002`. O estimador primário `rh90_rain` e o secundário `dpd_hysteresis` não dependem da altura do anemômetro.

## Referências principais da Fase 2

- Alduchov, O. A., & Eskridge, R. E. (1996). *Journal of Applied Meteorology*, 35(4), 601–609. https://doi.org/10.1175/1520-0450(1996)035<0601:IMFAOS>2.0.CO;2
- Baldacci, E. (1947). *Atti dell'Istituto Botanico della Università di Pavia*, Serie 5, 8, 45–85.
- Gillespie, T. J., Srivastava, B., & Pitblado, R. E. (1993). *Journal of Applied Meteorology*, 32(3), 567–573. https://doi.org/10.1175/1520-0450(1993)032<0567:UOWDTS>2.0.CO;2
- Goidànich, G. (1964). *Manuale di Patologia Vegetale*, Vol. II. Edagricole, Bologna.
- Kim, K. S., Taylor, S. E., Gleason, M. L., & Koehler, K. J. (2002). *Plant Disease*, 86(2), 179–185. https://doi.org/10.1094/PDIS.2002.86.2.179
- Rossi, V., Caffi, T., Giosuè, S., & Bugiani, R. (2008). *Ecological Modelling*, 212(3–4), 480–491. https://doi.org/10.1016/j.ecolmodel.2007.10.046
