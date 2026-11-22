# Nota de método: Fase 0

## O que foi feito

1. **Congelamento da v1:** criada a tag anotada `v1.0` apontando para o commit `e0de19c` antes de qualquer alteração da v2.
2. **Arrumação do repositório:** movidos com `git mv` para `legacy/` os cinco arquivos herdados do projeto do tomateiro que não são importados pela suíte de testes de código Python: `BRIEFING.md`, `SKILL.md`, `protocolo_experimental_e_or_amento_ensaio_tomateiro_dss.md`, `docs/fase1_datasets_visao.md` e `colab/train_yolo_seg.ipynb`. Os módulos Python da raiz e os arquivos da v1 permaneceram intactos. Um teste em `tests/test_phases1_2.py` lia o notebook diretamente em `colab/train_yolo_seg.ipynb` e teve o caminho atualizado para `legacy/train_yolo_seg.ipynb`, preservando todos os 69 testes da linha de base.
3. **Revisão de literatura:** redigida em `docs/v2/revisao.md` com oito trabalhos verificados, confirmando que a lacuna permanece aberta.
4. **Levantamento de implementações:** redigido em `docs/v2/implementacoes.md` após consulta direta à API do GitHub e à documentação do NIBIO VIPS.
5. **Inventário de dados:** redigido em `docs/v2/inventario_dados.md` com checagem local dos anos disponíveis e nova tentativa de verificação de licença no portal Recherche Data Gouv.
6. **Critérios de qualidade:** redigidos às cegas em `docs/v2/criterios_qualidade.md`, antes de baixar qualquer estação nova do INRAE.

## Por que cada escolha foi feita

- **Manter os módulos Python antigos na raiz:** o README e o relatório técnico da v1 citam e linkam arquivos como `vision_pipeline.py` e `epidemiology_assimilation.py`. Movê-los alteraria um entregável já congelado. A v2 nascerá em pacote próprio, isolado da v1.
- **Reimplementar as quatro regras sob MIT:** `GeoModelLab/octopus` usa licença `CC BY-NC-ND 4.0`, que proíbe obras derivadas. `BigDataWUR/A-scab` não tem licença declarada e implementa outro modelo de sarna. A licença do NIBIO VIPS exclui os modelos fitossanitários. `UW-Madison-DSI/ag_forecasting_api` é MIT, porém cobre apenas doenças de milho e soja. Reimplementar funções puras em Python a partir das tabelas publicadas evita conflitos de licença e garante execução direta no navegador via Pyodide na Fase 5.
- **Tratar `Open-Meteo Previous Runs` e a série longa 2019–2025 como análises secundárias:** o arquivo de previsões reais com horizonte de 1 a 7 dias começa em janeiro de 2024, com apenas 2 das 7 estações do Politecnico cobrindo 2024. Já o Historical Forecast tem cobertura operacional completa a partir de 2022 para todas as estações das duas redes. Por isso, a análise principal pareada com todas as quatro fontes cobre 2022–2025, enquanto a série longa sem Historical Forecast em 2019–2025 e o `Previous Runs` em 2024–2025 ficam declarados como análises secundárias no pré-registro.
- **Não baixar as 50 estações extras do INRAE na Fase 0:** o portal `entrepot.recherche.data.gouv.fr` seguiu em HTTP 503 em 22 nov 2026. Respeitamos a regra de não baixar o lote completo antes de confirmar a licença literal do dataset `10.57745/BQ0BWB`.

## O que este levantamento assume e onde pode falhar

- **Acesso temporariamente indisponível:** tanto o portal Recherche Data Gouv do INRAE quanto o `gitlab.nibio.no` não responderam nesta data. Para o NIBIO VIPS a limitação de licença já está documentada nas páginas institucionais do NIBIO; para o INRAE, a confirmação literal da licença fica pendente para o início da Fase 1.
- **Limitação da revisão de literatura:** a busca cobriu literatura indexada em inglês e português. Podem existir boletins regionais europeus em francês, alemão ou italiano comparando estações e grades meteorológicas locais que não aparecem em buscas por DOI.
- **Critérios de qualidade definidos sem olhar os dados novos:** os limiares de 95% de cobertura e 15% de molhamento em ar seco podem se mostrar rigorosos demais se muitas estações do INRAE tiverem manutenção anual na primavera. Se isso ocorrer na Fase 1, qualquer ajuste precisará ser aprovado antes da abertura de métricas e registrado explicitamente.

## Referências principais da Fase 0

- Asadi, P., & Tian, D. (2021). *Agricultural and Forest Meteorology*, 307, 108548. https://doi.org/10.1016/j.agrformet.2021.108548
- Baldacci, E. (1947). *Atti dell'Istituto Botanico della Università di Pavia*, Serie 5, 8, 45–85. Obra impressa anterior ao sistema DOI.
- Bregaglio, S., Del Cavallo, E., Ascari, L., & Rossi, E. (2025). *SoftwareX*, 30, 102085. https://doi.org/10.1016/j.softx.2025.102085
- Cavalcanti, F. R. (2021). Embrapa Uva e Vinho, Circular Técnica 124. https://www.infoteca.cnptia.embrapa.br/infoteca/handle/doc/1134000
- Cavalcanti, F. R., Botton, M., & Fioravanço, J. C. (2024). Embrapa Uva e Vinho, Boletim de Pesquisa e Desenvolvimento 30. https://www.infoteca.cnptia.embrapa.br/infoteca/handle/doc/1165921
- Duttweiler, K. B., Gleason, M. L., Dixon, P. M., Sutton, T. B., McManus, P. S., & Monteiro, J. E. B. A. (2008). *Plant Disease*, 92(8), 1215–1222. https://doi.org/10.1094/PDIS-92-8-1215
- Gillespie, T. J., Srivastava, B., & Pitblado, R. E. (1993). *Journal of Applied Meteorology*, 32(3), 567–573. https://doi.org/10.1175/1520-0450(1993)032<0567:UOWDTS>2.0.CO;2
- Gleason, M. L., et al. (2008). *Scientia Agricola*, 65(spe), 76–87. https://doi.org/10.1590/S0103-90162008000700013
- Goidànich, G. (1964). *Manuale di Patologia Vegetale*, Vol. II. Edagricole, Bologna. Obra impressa sem DOI.
- Kim, K. S., Beresford, R. M., & Henshall, W. R. (2008). *New Zealand Plant Protection*, 61, 296–300. https://doi.org/10.30843/nzpp.2008.61.6839
- MacHardy, W. E., & Gadoury, D. M. (1989). *Phytopathology*, 79(3), 304–310. https://doi.org/10.1094/PHYTO-79-304
- Madden, L., Pennypacker, S. P., & MacNab, A. A. (1978). *Phytopathology*, 68(9), 1354–1358. https://doi.org/10.1094/Phyto-68-1354
- Mensah, T. A., White, N., Rincón-Flórez, V., & Akinsanmi, O. A. (2026). *International Journal of Biometeorology*. https://doi.org/10.1007/s00484-026-03285-3
- Müller, K., & Sleumer, H. (1934). *Landwirtschaftliche Jahrbücher*, 79, 509–576. Obra impressa sem DOI.
- Pitblado, R. E. (1992). *The development and implementation of TOM-CAST*. Ontario Ministry of Agriculture and Food, Ridgetown College, 24 pp. Publicação técnica sem DOI.
- Rowlandson, T., et al. (2015). *Plant Disease*, 99(3), 310–319. https://doi.org/10.1094/PDIS-05-14-0529-FE
- Stensvand, A., Gadoury, D. M., Amundsen, T., Semb, L., & Seem, R. C. (1997). *Phytopathology*, 87(10), 1046–1053. https://doi.org/10.1094/PHYTO.1997.87.10.1046
