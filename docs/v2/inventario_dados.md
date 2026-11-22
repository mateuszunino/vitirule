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
| Open-Meteo Historical Weather, modelo ERA5-Land | 1950 até presente para ERA5-Land; 1940 para ERA5 | 0,1 grau, cerca de 9 a 11 km; horária | Temperatura 2 m, UR 2 m, ponto de orvalho, chuva, vento 10 m, radiação de onda curta | **CC BY 4.0**, exige atribuição a Open-Meteo.com; nível gratuito restrito a uso não comercial | 10.000 chamadas por dia, 5.000 por hora, 600 por minuto no plano gratuito |
| Open-Meteo Historical Forecast | A partir de 2021 ou 2022 conforme o modelo regional ou global | 1 a 11 km conforme o modelo; horária | Temperatura, UR, ponto de orvalho, chuva, vento, radiação | **CC BY 4.0**, nível gratuito não comercial | Cada hora vem da inicialização mais recente, então o horizonte efetivo é de poucas horas; funciona como quase-análise, não como previsão real de 1 a 3 dias |
| Open-Meteo Previous Runs e Single Runs | A partir de janeiro de 2024 para a maioria dos modelos arquivados | Variável conforme o modelo; horária com horizontes fixos de 1 a 7 dias antes | Mesmas variáveis com sufixos `_previous_day1`, `_previous_day2` até `_previous_day7` | **CC BY 4.0**, nível gratuito não comercial | Permite medir previsão real sem vazamento de futuro; ver cobertura de estações-safra abaixo |
| NASA POWER, base MERRA-2 | Horária de 2001 até próximo do tempo real | 0,5 por 0,625 grau, cerca de 50 por 60 km; horária | `T2M`, `RH2M`, `T2MDEW`, `PRECTOTCORR`, `WS2M`, `ALLSKY_SFC_SW_DWN` | Domínio público federal dos EUA / NASA Open Data Policy, uso livre com citação | Sem autenticação; resolução espacial cerca de 5 vezes mais grosseira que ERA5-Land |
| INMET, estações automáticas brasileiras | 2000 até presente conforme data de instalação da estação | Pontual, horária em UTC | Temperatura, UR, ponto de orvalho, chuva, vento e radiação; sem sensor de molhamento | Dados públicos abertos do governo brasileiro, gratuitos | Pacotes anuais ZIP em `portal.inmet.gov.br/uploads/dadoshistoricos/` ou API `apitempo` em janelas de até 6 meses; entra na Fase 4 como estação brasileira sem sensor |

## 3. Checagem de cobertura de 2024 em diante para `Previous Runs`

Para avaliar previsões reais com horizonte de 1 a 3 dias via Open-Meteo Previous Runs, precisamos de estações-safra a partir de janeiro de 2024. Conferimos a cobertura temporal dos arquivos já disponíveis localmente:

- **INRAE local, 4 estações da v1:** todas cobrem até `2025-12-31`, oferecendo 2 safras completas em 2024 e 2025 por estação, total de 8 estações-safra. Quando a licença do INRAE for confirmada e as demais estações elegíveis forem baixadas na Fase 1, o total de estações-safra em 2024 e 2025 tende a crescer para dezenas de unidades.
- **Politecnico di Torino local, 7 estações:** apenas `site6.csv` e `site7.csv` cobrem o ano de 2024. As demais cobrem 2022 (`site1`, `site3`, `site5`) ou 2023 (`site2`, `site4`).

**Conclusão operacional para o pré-registro:** no Politecnico di Torino existem apenas 2 estações-safra em 2024, número insuficiente para estimar incerteza por rede. No INRAE a amostra em 2024 e 2025 será maior se as demais estações também chegarem até 2025, mas cobre apenas dois anos climáticos. Por isso, `Open-Meteo Previous Runs` entra como **análise secundária** focada no recorte 2024–2025, separada da comparação principal de 2019–2025 que usa estação sem sensor, ERA5-Land, Historical Forecast e NASA POWER.

## 4. Pendências de licença e acesso

1. **INRAE AgroClim:** o comando `.\.venv\Scripts\python.exe scripts/download_sensor_datasets.py --dry-run` retornou HTTP 503 em 22 nov 2026 no portal `entrepot.recherche.data.gouv.fr`. Nenhuma das 50 estações adicionais será baixada até a licença literal do dataset `10.57745/BQ0BWB` ser confirmada. Se a licença impuser qualquer restrição de redistribuição, os arquivos do INRAE receberão o mesmo bloqueio de Git e CI já aplicado ao Politecnico.
2. **Epagri/Ciram:** acesso pendente do pedido formal do autor para a Fase 4.
