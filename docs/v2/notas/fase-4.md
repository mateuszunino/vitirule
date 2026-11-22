# Nota de método: Fase 4, transferência brasileira em Santa Catarina

> **Estado:** transferência brasileira concluída após o congelamento do adendo em **`v2-freeze-br`** usando exclusivamente estações automáticas oficiais do INMET em Santa Catarina de 2022 a 2025. O portal `entrepot.recherche.data.gouv.fr` permaneceu em HTTP 503 em 22 nov 2026, mantendo pendente o conjunto confirmatório europeu `v2-confirmatory`. Nenhum leitor da Epagri/Ciram foi implementado nesta etapa, conforme definido em `v2-freeze-br`.

## O que foi feito

1. **Adendo pré-registrado antes de baixar dados brasileiros:** congelamos a seção 9 de `docs/v2/preregistro.md` na tag anotada **`v2-freeze-br`** no commit `29c364b`, fixando a regra objetiva de seleção de estações do INMET, a restrição de interpretação entre estimativa de erro e divergência, a ausência de leitor Epagri/Ciram e o caráter exploratório do diagnóstico de relevo e chuva convectiva.
2. **Coleta e leitor oficial do INMET + filtro IBGE PAM:** implementamos `vitirule_v2/sources/inmet.py`, extraímos exclusivamente os CSVs catarinenses de `2022.zip` a `2025.zip` em `data/inmet_sc/`, fora do Git, consultamos a tabela SIDRA `5457` da Produção Agrícola Municipal do IBGE de 2025 para área colhida de maçã, uva e tomate em todos os 295 municípios de Santa Catarina e adicionamos 3 testes unitários em `tests/test_v2_phase4_inmet.py`.
3. **Execução cega e coleta de grades em UTC:** aplicamos `scripts/v2_phase4_brazil.py` com `vitirule_v2/qc.py` no Hemisfério Sul sem sensor de LWD e coletamos em UTC, com cache em `data/v2_cache/`, as séries do **ERA5 combinado: T e UR do ERA5-Land, chuva, vento e radiação do ERA5**, do **Open-Meteo Historical Forecast** e do **NASA POWER** com `time-standard=UTC` para todas as 11 estações aprovadas. Registramos em `grid_metadata` a distância horizontal e a diferença de altitude tanto do ponto ERA5-Land de `0,1 grau` quanto do ponto ERA5 de `0,25 grau` usado na precipitação.

## Verificações de integridade após `v2-freeze` e `v2-freeze-br`

1. **`git diff --stat v2-freeze -- vitirule_v2/metrics.py vitirule_v2/rules/`:** saída vazia, zero linhas alteradas. Nenhuma regra agronômica, tabela de limiares, tolerância de pareamento ou métrica mudou desde `v2-freeze`.
2. **`git diff v2-freeze-br -- vitirule_v2/qc.py`:** a única mudança em todo o arquivo foi a adição do parâmetro opcional `require_lwd_sensor: bool = True` em `_is_valid_hour`, `compute_raw_gap_hours`, `compute_masked_hours_for_rule` e `evaluate_station_season_qc`. Com o padrão `True`, nenhum critério de aprovação ou comportamento muda para as redes europeias com sensor. Com `False`, usado exclusivamente no INMET conforme pré-registrado na seção 9.1 de `v2-freeze-br`, omitem-se apenas a exigência de `rec.wet` não nulo e os três testes exclusivos do sensor físico de molhamento foliar, preservando integralmente cobertura mínima de `95,0%`, unicidade e monotonicidade de timestamps UTC, limites físicos congelados e política `mask_with_warmup`. Verificamos também que `0` horas em todas as 24 estações catarinenses de 2022 a 2025 caem na faixa intermediária entre os limites físicos congelados em `qc.py` e os limites citados no texto da seção 9.1.
3. **Correção de chamada em Goidànich:** registrada na seção 8 de `docs/v2/preregistro.md`. A primeira execução de `scripts/v2_phase4_brazil.py` foi vista com zero eventos em Goidànich por omissão do argumento `hemisphere="southern_hemisphere"` na chamada de `track_goidanich_incubation`, corrigida sem alterar nenhuma regra nem métrica.

## Seleção cega das 24 estações automáticas do INMET em Santa Catarina

Aplicando estritamente a regra congelada em `v2-freeze-br` sobre as **24 estações automáticas** oficiais de Santa Catarina em `2022–2025`, **7 estações** saíram pelo filtro pré-registrado de município produtor da PAM 2025 do IBGE, **6 estações** de municípios produtores saíram pelo controle de qualidade cego por aprovarem menos de 2 safras e **11 estações** entraram em pelo menos uma cultura. Em 100% das estações-safra reprovadas no QC, o único critério violado foi **`coverage_below_0.95`**.

| Código | Município / Estação INMET | Passou IBGE PAM 2025 | PAM 2025: maçã / uva / tomate, ha | Safras reprovadas no QC e critério | Decisão `v2-freeze-br` |
|---|---|---|---|---|---|
| `A806` | Florianópolis | Não | 0 / 0 / 0 | Macieira 1/4, videira 1/3, tomateiro 1/3 (`coverage_below_0.95`) | Excluída pelo filtro IBGE |
| `A814` | Urussanga | Sim | 0 / 102 / 0 | Macieira 3/4, videira 1/3, tomateiro 1/3 (`coverage_below_0.95`) | Incluída: videira, tomateiro |
| `A815` | São Joaquim | Sim | 9.600 / 201 / 0 | Macieira 2/4, videira 1/3, tomateiro 1/3 (`coverage_below_0.95`) | Incluída: macieira, videira, tomateiro |
| `A816` | Novo Horizonte | Sim | 0 / 0 / 1 | Macieira 2/4, videira 2/3, tomateiro 2/3 (`coverage_below_0.95`) | Incluída: macieira |
| `A817` | Indaial | Sim | 0 / 0 / 20 | Macieira 3/4, videira 2/3, tomateiro 1/3 (`coverage_below_0.95`) | Incluída: tomateiro |
| `A841` | Joaçaba | Sim | 0 / 3 / 0 | Macieira 4/4, videira 2/3, tomateiro 2/3 (`coverage_below_0.95`) | Excluída no QC: `< 2` safras em todas |
| `A845` | Bom Jardim da Serra, Morro da Igreja | Sim | 1.450 / 1 / 0 | Macieira 3/4, videira 2/3, tomateiro 2/3 (`coverage_below_0.95`) | Excluída no QC: `< 2` safras em todas |
| `A848` | Dionísio Cerqueira | Sim | 0 / 3 / 0 | Macieira 3/4, videira 1/3, tomateiro 1/3 (`coverage_below_0.95`) | Incluída: videira, tomateiro |
| `A851` | Itapoá | Não | 0 / 0 / 0 | Macieira 1/4, videira 1/3, tomateiro 1/3 (`coverage_below_0.95`) | Excluída pelo filtro IBGE |
| `A857` | São Miguel do Oeste | Sim | 0 / 2 / 0 | Macieira 4/4, videira 3/3, tomateiro 3/3 (`coverage_below_0.95`) | Excluída no QC: `0` safras válidas |
| `A858` | Xanxerê | Não | 0 / 0 / 0 | Macieira 3/4, videira 1/3, tomateiro 1/3 (`coverage_below_0.95`) | Excluída pelo filtro IBGE |
| `A859` | Caçador | Sim | 85 / 425 / 450 | Macieira 2/4, videira 1/3, tomateiro 1/3 (`coverage_below_0.95`) | Incluída: macieira, videira, tomateiro |
| `A860` | Curitibanos | Sim | 0 / 8 / 0 | Macieira 2/4, videira 1/3, tomateiro 0/3 (`coverage_below_0.95`) | Incluída: macieira, videira, tomateiro |
| `A861` | Rio do Campo | Sim | 0 / 2 / 0 | Macieira 3/4, videira 2/3, tomateiro 1/3 (`coverage_below_0.95`) | Incluída: tomateiro |
| `A862` | Rio Negrinho | Não | 0 / 0 / 0 | Macieira 4/4, videira 3/3, tomateiro 2/3 (`coverage_below_0.95`) | Excluída pelo filtro IBGE |
| `A863` | Ituporanga | Sim | 0 / 5 / 15 | Macieira 1/4, videira 1/3, tomateiro 1/3 (`coverage_below_0.95`) | Incluída: macieira, videira, tomateiro |
| `A864` | Major Vieira | Sim | 8 / 3 / 25 | Macieira 4/4, videira 3/3, tomateiro 2/3 (`coverage_below_0.95`) | Excluída no QC: `< 2` safras em todas |
| `A865` | Lages | Sim | 0 / 14 / 9 | Macieira 4/4, videira 3/3, tomateiro 2/3 (`coverage_below_0.95`) | Excluída no QC: `< 2` safras em todas |
| `A866` | Laguna, Farol de Santa Marta | Não | 0 / 0 / 0 | Macieira 4/4, videira 3/3, tomateiro 2/3 (`coverage_below_0.95`) | Excluída pelo filtro IBGE |
| `A867` | Araranguá | Não | 0 / 0 / 0 | Macieira 4/4, videira 2/3, tomateiro 2/3 (`coverage_below_0.95`) | Excluída pelo filtro IBGE |
| `A868` | Itajaí | Não | 0 / 0 / 0 | Macieira 1/4, videira 1/3, tomateiro 1/3 (`coverage_below_0.95`) | Excluída pelo filtro IBGE |
| `A870` | Rancho Queimado | Sim | 0 / 6 / 120 | Macieira 4/4, videira 3/3, tomateiro 3/3 (`coverage_below_0.95`) | Excluída no QC: `0%` cobertura em todas |
| `A895` | Chapecó | Sim | 0 / 50 / 0 | Macieira 2/4, videira 1/3, tomateiro 1/3 (`coverage_below_0.95`) | Incluída: macieira, videira, tomateiro |
| `A898` | Campos Novos | Sim | 0 / 20 / 0 | Macieira 1/4, videira 0/3, tomateiro 0/3 (`coverage_below_0.95`) | Incluída: macieira, videira, tomateiro |

Totais efetivos incluídos no recorte pareado `2022–2025`: **7 estações e 16 estações-safra** na macieira, **8 estações e 17 estações-safra** na videira e **10 estações e 22 estações-safra** no tomateiro.

## Tabela revisada de Mills: divergência contra a estação do INMET, candidata a estimativa de erro

Conforme a seção 9.2 de `docs/v2/preregistro.md`, o conjunto confirmatório europeu `v2-confirmatory` ainda não rodou porque o portal do INRAE permaneceu em HTTP 503. Portanto, o resultado abaixo em Mills revisada é **divergência contra a estação do INMET, candidata a estimativa de erro se o conjunto confirmatório europeu repetir o resultado exploratório**.

Além disso, o critério pré-registrado de usabilidade foi definido contra **molhamento foliar medido por sensor físico**. Nesta seção ele é aplicado a uma **referência substituta**, a estação do INMET com estimador `rh90_rain`, que no conjunto exploratório europeu perdeu `16,9%` dos eventos de Mills. Nas tabelas abaixo, **ERA5 combinado** designa a fonte **ERA5 combinado: T e UR do ERA5-Land, chuva, vento e radiação do ERA5**.

| Fonte em grade | INMET / Grade | Sem par no INMET, IC 95% | Razão de extras | F1 | Deslocamento mediano, IQR | Valor custo-perda `0,05` / `0,10` / `0,20` | Severidade exata / superestimada |
|---|---:|---|---:|---:|---|---|---|
| ERA5 combinado | 306 / 285 | 37,6% `[29,1; 42,4]` | 33,0% | 0,646 | -0,13 d `[-0,29; +0,04]` | `-2,03` / `-0,51` / `+0,26` | 61,8% / 34,6% |
| Historical Forecast | 306 / 283 | 37,9% `[30,9; 46,8]` | 32,9% | 0,645 | -0,08 d `[-0,25; 0,00]` | `-1,94` / `-0,46` / `+0,28` | 63,2% / 33,2% |
| NASA POWER | 306 / 202 | 59,2% `[51,4; 64,3]` | 38,1% | 0,492 | -0,38 d `[-0,58; -0,25]` | `-3,37` / `-1,14` / `-0,02` | 60,0% / 40,0% |

Mesmo frente à referência substituta do INMET, **nenhuma das três fontes gratuitas em grade atingiu os limiares do critério de usabilidade em Mills revisada**. Tanto o ERA5 combinado quanto o Historical Forecast deixam sem par cerca de `38%` dos eventos do INMET com razão de extras ao redor de `33%` e valor de custo-perda negativo nos cenários `C/L = 0,05` e `0,10`. O NASA POWER deixa sem par `59,2%` dos eventos e apresenta valor negativo nos três cenários. Entre pares detectados, as três fontes tendem a superestimar a severidade em `33%` a `40%` dos casos por prolongarem a duração das horas úmidas em relação à estação local.

## Regra 3-10, Goidànich e TOM-CAST: divergência entre grade e INMET

Conforme a seção 9.2 de `docs/v2/preregistro.md`, todos os números desta seção representam estritamente **divergência** entre a fonte em grade e a estação automática do INMET, sem leitura como erro.

| Regra | Fonte em grade | INMET / Grade | Sem par no INMET, IC 95% | Razão de extras | F1 de concordância | Deslocamento mediano, IQR | Valor custo-perda relativo `0,05` / `0,10` / `0,20` |
|---|---|---:|---|---:|---:|---|---|
| Regra 3-10 | NASA POWER | 299 / 256 | 26,4% `[22,5; 31,5]` | 14,1% | 0,793 | 0,0 d `[0,0; 0,0]` | `-0,65` / `0,18` / `0,35` |
| Regra 3-10 | ERA5 combinado | 299 / 292 | 22,4% `[18,0; 27,2]` | 20,5% | 0,785 | 0,0 d `[0,0; 0,0]` | `-0,50` / `0,25` / `0,39` |
| Regra 3-10 | Historical Forecast | 299 / 292 | 26,4% `[22,0; 31,9]` | 24,7% | 0,745 | 0,0 d `[0,0; 0,0]` | `-0,66` / `0,17` / `0,32` |
| Goidànich | ERA5 combinado | 254 / 252 | 20,5% `[15,4; 25,5]` | 19,8% | 0,798 | 0,0 d `[-0,75; 0,0]` | `-0,23` / `0,36` / `0,28` |
| Goidànich | NASA POWER | 254 / 218 | 29,5% `[23,9; 34,3]` | 17,9% | 0,758 | 0,0 d `[-1,0; 0,0]` | `-0,59` / `0,19` / `0,10` |
| Goidànich | Historical Forecast | 254 / 250 | 25,2% `[19,6; 31,3]` | 24,0% | 0,754 | 0,0 d `[-1,0; 0,0]` | `-0,39` / `0,28` / `0,19` |
| TOM-CAST `self_reset` | Historical Forecast | 186 / 326 | 8,1% `[4,0; 13,9]` | 47,5% | 0,668 | -1,0 d `[-2,0; 1,0]` | `-0,19` / `-0,02` / `-0,24` |
| TOM-CAST `self_reset` | ERA5 combinado | 186 / 350 | 7,0% `[2,0; 15,0]` | 50,6% | 0,645 | 0,0 d `[-2,0; 1,0]` | `-0,15` / `0,01` / `-0,23` |
| TOM-CAST `self_reset` | NASA POWER | 186 / 464 | 0,5% `[0,0; 2,4]` | 60,1% | 0,569 | 0,0 d `[-1,0; 1,0]` | `-0,16` / `-0,04` / `-0,35` |

No **TOM-CAST**, a separação entre `reference_reset` e `self_reset` confirma o mesmo mecanismo estrutural visto na Europa. Em `reference_reset`, avaliando a fidelidade da entrada em relação à estação do INMET sob `rh90_rain`, **100% dos 186 intervalos** atingiram `15 DSV` antes da data do INMET nas três fontes em grade, com excesso médio de `+11,38 DSV` no Historical Forecast, `+13,16 DSV` no ERA5 combinado e `+21,41 DSV` no NASA POWER, antecipando cada pulverização em mediana de `-3` a `-4 dias`. Em `self_reset`, essa antecipação sistemática desloca todos os zeramentos seguintes e multiplica o número total de aplicações na safra em `1,8` a `2,5 vezes`, de `186` para `326` a `464`, elevando a razão de pulverizações extras para `47,5%` a `60,1%`.

Na **Regra 3-10** e em **Goidànich**, a concordância bruta entre grades e INMET é ligeiramente maior do que no conjunto europeu, com F1 entre `0,745` e `0,798`, provavelmente pela maior frequência de frentes frias organizadas de escala sinótica na primavera e no verão do Sul do Brasil. Ainda assim, `20,5%` a `29,5%` dos eventos detectados pela estação local não são reproduzidos dentro de `±2 dias` pelas fontes em grade.

## Diagnóstico exploratório por relevo e regime de chuva convectiva

> **Aviso:** toda esta seção é estritamente **exploratória**, conforme congelado na seção 9.3 de `docs/v2/preregistro.md`. Com 7 a 10 estações por cultura, as associações abaixo servem para gerar hipóteses físicas, não para inferência confirmatória.

A tabela abaixo cruza altitude da estação, fração da chuva de verão de outubro a março caída em horas convectivas intensas de pelo menos `10 mm/h`, distância horizontal e diferença de altitude até os três pontos de grade e o F1 local em Mills e na Regra 3-10.

| Estação INMET | Altitude | Chuva `>= 10 mm/h` | ERA5 `0,1°` T/UR: dist. / Δ alt. | ERA5 `0,25°` chuva: dist. / Δ alt. | NASA POWER: dist. / Δ alt. | Mills F1: ERA5 / HF / NASA | 3-10 F1: ERA5 / HF / NASA |
|---|---:|---:|---:|---:|---:|---|---|
| `A814` Urussanga | 40,6 m | 33,9% | 3,9 km / -2 m | 7,3 km / +215 m | 6,9 km / +427 m | n/a | 0,796 / 0,818 / 0,810 |
| `A817` Indaial | 72,2 m | 33,8% | 3,5 km / -3 m | 9,8 km / +243 m | 14,3 km / +396 m | n/a | n/a |
| `A863` Ituporanga | 479,8 m | 36,1% | 5,1 km / -10 m | 13,6 km / +110 m | 28,3 km / +197 m | 0,562 / 0,641 / 0,470 | 0,723 / 0,667 / 0,691 |
| `A861` Rio do Campo | 591,7 m | 43,8% | 6,1 km / +1 m | 12,5 km / +299 m | 16,0 km / +38 m | n/a | n/a |
| `A895` Chapecó | 679,0 m | 35,3% | 3,9 km / +2 m | 14,8 km / +6 m | 16,5 km / -89 m | 0,743 / 0,765 / 0,647 | 0,842 / 0,700 / 0,889 |
| `A848` Dionísio Cerqueira | 807,5 m | 46,9% | 3,6 km / -7 m | 12,3 km / -225 m | 26,4 km / -275 m | n/a | 0,753 / 0,723 / 0,795 |
| `A816` Novo Horizonte | 943,6 m | 42,3% | 5,0 km / +10 m | 14,4 km / -425 m | 29,3 km / -260 m | 0,727 / 0,703 / 0,609 | n/a |
| `A859` Caçador | 944,3 m | 34,3% | 2,6 km / -1 m | 7,8 km / +35 m | 33,0 km / +3 m | 0,609 / 0,674 / 0,442 | 0,874 / 0,780 / 0,800 |
| `A898` Campos Novos | 963,0 m | 35,2% | 2,0 km / -23 m | 12,8 km / -118 m | 12,8 km / -161 m | 0,733 / 0,593 / 0,489 | 0,737 / 0,667 / 0,811 |
| `A860` Curitibanos | 978,1 m | 39,7% | 1,3 km / -1 m | 11,2 km / -31 m | 23,6 km / -59 m | 0,638 / 0,701 / 0,524 | 0,851 / 0,826 / 0,843 |
| `A815` São Joaquim | 1.400,1 m | 27,2% | 4,3 km / 0 m | 7,0 km / -178 m | 25,8 km / -408 m | 0,667 / 0,494 / 0,381 | 0,692 / 0,684 / 0,788 |

Padrões exploratórios observados:

1. **Desníveis extremos na escarpa da Serra Geral e nos vales encaixados:** enquanto o cabeçalho de `0,1 grau` do Open-Meteo corrige a altitude para o ponto da estação, o centro real da célula de chuva ERA5 de `0,25 grau` sofre desníveis de `-425 m` em Novo Horizonte, `+299 m` em Rio do Campo, `+243 m` em Indaial, `-225 m` em Dionísio Cerqueira e `-178 m` em São Joaquim. No NASA POWER MERRA-2, a célula de `50 por 60 km` produz erros de altitude de `+427 m` em Urussanga, `+396 m` em Indaial e `-408 m` em São Joaquim.
2. **Pior desempenho em Mills no polo principal da macieira:** em São Joaquim, a `1.400 m` e responsável por `9.600 ha` de maçã na PAM 2025, o F1 de Mills cai ao menor valor do estado tanto no Historical Forecast (`0,494`) quanto no NASA POWER (`0,381`), puxando correlações de Spearman negativas entre altitude e F1 de Mills nessas duas fontes (`-0,50` e `-0,43`). No extremo oposto de relevo, Ituporanga no fundo de vale do Alto Vale do Itajaí também sofre degradação forte (`0,562` no ERA5 combinado e `0,470` no NASA POWER), sugerindo que heterogeneidade orográfica local pesa tanto quanto altitude absoluta.
3. **Regime convectivo versus orografia:** a parcela de chuva convectiva intensa varia de `27,2%` em São Joaquim a `46,9%` em Dionísio Cerqueira. A correlação positiva observada entre fração convectiva e F1 de Mills no Historical Forecast (`+0,64`) e no NASA POWER (`+0,71`) confunde-se com o gradiente altitudinal, porque São Joaquim combina a maior altitude com o menor percentual convectivo e maior peso de chuvas frontais frias e neblinas orográficas mal representadas nas grades.

## O que esta fase assume e onde pode falhar

- **Ausência de sensor físico de molhamento no INMET:** o molhamento foliar local no Brasil foi estimado por `rh90_rain`. Por isso, mesmo em Mills o resultado é divergência contra a estação do INMET, candidata a estimativa de erro se o conjunto confirmatório europeu repetir o resultado exploratório. Além disso, o critério de usabilidade foi aplicado a uma referência substituta que perdeu `16,9%` dos eventos de Mills na Europa exploratória. A medição direta de erro com sensor físico em Santa Catarina depende da chegada futura dos dados da Epagri/Ciram.
- **Baixa cobertura de telemetria em parte da rede INMET:** seis estações em municípios produtores relevantes, entre elas Lages, Bom Jardim da Serra e Rancho Queimado, reprovaram no QC cego por cobertura abaixo de `95%`. O recorte aprovado representa bem os polos de São Joaquim, Caçador, Curitibanos, Campos Novos, Chapecó, Urussanga e Ituporanga, mas não substitui a densidade da rede estadual catarinense.
- **Conjunto confirmatório europeu ainda pendente:** o portal `entrepot.recherche.data.gouv.fr` continuou em HTTP 503 em 22 nov 2026; assim que voltar e a licença do DOI `10.57745/BQ0BWB` for verificada, a rodada única `v2-confirmatory` completará a evidência confirmatória.

## Referências principais da Fase 4

- IBGE. (2026). *Produção Agrícola Municipal, PAM 2025, Tabela SIDRA 5457: Área colhida por município em Santa Catarina*. Instituto Brasileiro de Geografia e Estatística. https://servicodados.ibge.gov.br/api/v3/agregados/5457/metadados
- INMET. (2026). *Banco de Dados Meteorológicos, arquivos históricos anuais das estações automáticas de 2022 a 2025*. Instituto Nacional de Meteorologia. https://portal.inmet.gov.br/dadoshistoricos
- MacHardy, W. E., & Gadoury, D. M. (1989). *Phytopathology*, 79(3), 304–310. https://doi.org/10.1094/Phyto-79-304
- Richardson, D. S. (2000). *Quarterly Journal of the Royal Meteorological Society*, 126(563), 649–667. https://doi.org/10.1002/qj.49712656313
