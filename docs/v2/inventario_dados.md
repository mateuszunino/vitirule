# Inventário de fontes meteorológicas e de sensores para o vitirule v2

Este inventário registra cobertura temporal, resolução, variáveis horárias, licença e limites operacionais de cada fonte considerada na v2, antes de baixar qualquer série nova.

## 1. Redes de referência com sensor físico de molhamento foliar

| Fonte | Cobertura temporal | Resolução e escopo | Variáveis horárias relevantes | Licença verificada | Estado atual |
|---|---|---|---|---|---|
| INRAE AgroClim, DOI `10.57745/BQ0BWB` | Séries multidecadais até 31 dez 2025 nas 4 estações já locais | 54 estações automáticas na França; passo horário em UTC | Temperatura do ar, UR, precipitação, vento a 2 m, radiação global, duração de molhamento `h` em `[0, 1]` | Artigo *Data in Brief* 2025 sob CC BY 4.0. Licença literal do dataset pendente: o portal Recherche Data Gouv retornou HTTP 503 em `scripts/download_sensor_datasets.py --dry-run` em 22 nov 2026 | 4 estações da v1 em cache local; as demais 50 não serão baixadas até confirmar a licença |
| Politecnico di Torino / iXem Labs, DOI `10.17632/sd4b8vpvyb.1` | 2022 a 2024, 1 ano por estação | 7 estações na Itália; passo horário em UTC | Temperatura do ar, UR, precipitação, vento, radiação ou solo e sensor capacitivo dupla face `leaf_top` | **CC BY-NC 4.0** confirmada via Mendeley Data API e DataCite | 7 estações já em cache local, fora do Git; todas ficam no conjunto de desenvolvimento da v2 |
| Epagri/Ciram, Santa Catarina | A confirmar conforme liberação oficial | Rede estadual catarinense com estações em áreas de maçã, uva e tomate | Temperatura, UR, chuva e molhamento foliar horário | Depende do termo de cessão do pedido formal | Pendente; pedido formal a ser enviado pelo autor para a Fase 4 |

## 2. Fontes candidatas sem sensor de molhamento

| Fonte | Cobertura temporal | Resolução espacial e temporal | Variáveis horárias | Licença e atribuição | Limites de uso e observações técnicas |
|---|---|---|---|---|---|
| Estação local sem sensor de molhamento | Idêntica à respectiva estação de referência | Pontual, horária | Temperatura, UR, chuva, vento e radiação medidos na estação; molhamento estimado por fórmula | Herda a licença da rede de estação | Isola quanto se perde ao remover apenas o sensor físico de LWD, mantendo a meteorologia local real |
| ERA5 combinado: T e UR do ERA5-Land, chuva, vento e radiação do ERA5, via Open-Meteo Archive `era5_seamless` | 1950 até presente para ERA5-Land; 1940 para ERA5 | 0,1 grau, cerca de 9 a 11 km, para temperatura e UR; 0,25 grau, cerca de 25 a 28 km, para chuva, vento e radiação; passo horário | Temperatura 2 m e UR 2 m do ERA5-Land; chuva, vento 10 m e radiação de onda curta do ERA5 | **CC BY 4.0**, exige atribuição a Open-Meteo.com; nível gratuito restrito a uso não comercial | 10.000 chamadas por dia, 5.000 por hora, 600 por minuto no plano gratuito; `models=era5_land` isolado retorna `null` em chuva, vento e radiação no Open-Meteo |
| Open-Meteo Historical Forecast | Previsões arquivadas contínuas a partir de 2022 para a maioria dos modelos, com `gfs_seamless` desde março de 2021, `icon_seamless` desde 2023 e `ecmwf_ifs025` desde 2024 | 1 a 11 km conforme o modelo; horária | Temperatura, UR, ponto de orvalho, chuva, vento, radiação | **CC BY 4.0**, nível gratuito não comercial | Cada hora vem da inicialização mais recente, funcionando como quase-análise e não como previsão real de 1 a 3 dias; `2022` é o primeiro ano civil completo com cobertura em todas as estações das duas redes |
| Open-Meteo Previous Runs e Single Runs | A partir de janeiro de 2024 para a maioria dos modelos arquivados | Variável conforme o modelo; horária com horizontes fixos de 1 a 7 dias antes | Mesmas variáveis com sufixos `_previous_day1`, `_previous_day2` até `_previous_day7` | **CC BY 4.0**, nível gratuito não comercial | Permite medir previsão real sem vazamento de futuro; entra como análise secundária em 2024–2025 |
| NASA POWER, base MERRA-2 | Horária de 2001 até próximo do tempo real | 0,5 por 0,625 grau, cerca de 50 por 60 km; horária | `T2M`, `RH2M`, `T2MDEW`, `PRECTOTCORR`, `WS2M`, `ALLSKY_SFC_SW_DWN` | Domínio público federal dos EUA / NASA Open Data Policy, uso livre com citação | Sem autenticação; o padrão da API horária é Local Solar Time, exigindo o parâmetro explícito `time-standard=UTC` em todas as consultas; resolução espacial cerca de 5 vezes mais grosseira que ERA5-Land |
| INMET, estações automáticas brasileiras | 2000 até presente conforme data de instalação da estação | Pontual, horária em UTC | Temperatura, UR, ponto de orvalho, chuva, vento e radiação; sem sensor de molhamento | Dados públicos abertos do governo brasileiro, gratuitos | Pacotes anuais ZIP em `portal.inmet.gov.br/uploads/dadoshistoricos/` ou API `apitempo` em janelas de até 6 meses; entra na Fase 4 como estação brasileira sem sensor |

## 3. Janela temporal pareada da análise principal e análises secundárias

A comparação principal exige pareamento estrito: entram apenas estações-safra em que todas as quatro fontes candidatas principais existem simultaneamente. Essas quatro fontes são estação local sem sensor, ERA5 combinado, Historical Forecast e NASA POWER.

Verificamos diretamente na API `historical-forecast-api.open-meteo.com/v1/forecast` em 22 nov 2026 a disponibilidade horária das cinco variáveis obrigatórias para Bordeaux e Turim. O modelo `gfs_seamless` começa em março de 2021, `icon_seamless` em 2023 e `ecmwf_ifs025` em 2024, enquanto a documentação do Open-Meteo situa o início geral do arquivo de previsões de alta resolução em 2022. No conjunto do Politecnico di Torino, todas as sete estações cobrem os anos de 2022 a 2024. No INRAE, as quatro estações locais cobrem continuamente até `2025-12-31`.

Com base nesses limites, ficam definidas três janelas separadas no pré-registro:

1. **Análise principal pareada, de 2022 a 2025:** primeiro ano civil completo em que o Historical Forecast cobre integralmente todas as estações das duas redes. Inclui quatro safras por estação no INRAE e 100% das estações aprovadas no controle de qualidade do Politecnico di Torino.
2. **Análise secundária de série longa sem Historical Forecast, de 2019 a 2025:** restrita ao INRAE, comparando estação sem sensor, ERA5 combinado e NASA POWER em sete safras para checar estabilidade interanual dos resultados.
3. **Análise secundária de previsão com horizonte real, de 2024 a 2025:** usa `Open-Meteo Previous Runs` com horizontes de 1, 2 e 3 dias nas estações-safra disponíveis a partir de janeiro de 2024. No Politecnico apenas `site6.csv` e `site7.csv` cobrem 2024, número insuficiente para inferência isolada nessa rede; no INRAE o recorte cobre 2024 e 2025 em todas as estações aprovadas.

## 4. Pendências de licença e acesso

1. **INRAE AgroClim:** o portal `entrepot.recherche.data.gouv.fr` seguiu retornando HTTP 503 em manutenção em 22 nov 2026. Nenhuma das 50 estações adicionais será baixada até a licença literal do dataset `10.57745/BQ0BWB` ser confirmada. Se a licença impuser qualquer restrição de redistribuição, os arquivos do INRAE receberão o mesmo bloqueio de Git e CI já aplicado ao Politecnico.
2. **Epagri/Ciram:** acesso pendente do pedido formal do autor para a Fase 4.
