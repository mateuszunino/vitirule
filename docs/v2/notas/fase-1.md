# Nota de método: Fase 1

## O que foi feito

1. **Correções da Fase 0 aplicadas antes do código:** atualizamos `docs/v2/revisao.md` e `docs/v2/notas/fase-0.md` com links ou DOIs verificados para todas as entradas, incluindo Kim et al. (2008), Gleason et al. (2008), Cavalcanti (2021, 2024) no Infoteca-e da Embrapa e notas arquivísticas para obras impressas anteriores ao DOI como Baldacci (1947), Müller & Sleumer (1934), Goidànich (1964) e Pitblado (1992). Corrigimos `docs/v2/inventario_dados.md` para adotar a janela pareada principal de `2022 a 2025`, declarando a série longa de `2019 a 2025` sem Historical Forecast e o recorte `2024 a 2025` com `Previous Runs` como análises secundárias. Atualizamos `docs/v2/implementacoes.md` para deixar explícito que os testes da v1 não servem de oráculo. Criamos o rascunho de `docs/v2/preregistro.md` com o aviso de escopo das estações e separação obrigatória por rede.
2. **Pacote isolado `vitirule_v2/`:** implementamos as quatro regras publicadas como funções puras em Python em `vitirule_v2/rules/` usando apenas a biblioteca padrão, sem importar nenhum módulo congelado da v1 nem bibliotecas externas como `numpy` ou `pandas`, garantindo execução direta no navegador via Pyodide na Fase 5.
3. **Parâmetros com fontes e divergências em `vitirule_v2/rules/params.json`:** centralizamos todas as constantes, tabelas, janelas fenológicas fixas, divergências encontradas na literatura, escolhas adotadas e referências bibliográficas primárias num único arquivo JSON.
4. **Controle de qualidade cego e sorteio de lockbox:** implementamos `vitirule_v2/qc.py` seguindo literalmente os critérios aprovados em `docs/v2/criterios_qualidade.md`, além dos leitores isolados em `vitirule_v2/sensors.py`.
5. **Suíte de testes com oráculos primários:** criamos `tests/test_v2_rules.py` com **85 testes novos** ancorados nas tabelas publicadas primárias, verificando isolamento do pacote, janelas fenológicas, casos de borda da regra 3-10, tabela completa de Goidànich, todas as 21 linhas da tabela revisada de Mills com regra de interrupção seca, toda a matriz de DSV do TOM-CAST nos dois modos de reset e testes sintéticos do controle de qualidade e do sorteio estratificado. A comparação cruzada com a v1 ficou isolada na classe `TestV1Consistency`, marcada como conferência de consistência e não como oráculo. Com os 69 testes preservados da v1, a suíte soma **154 testes passando**.
6. **Congelamento das regras na tag `v2-rules`:** antes de executar o passo 4 sobre dados reais, fechamos o commit `64e7f63` e criamos a tag anotada `v2-rules`.
7. **Passo 4 com referência medida apenas:** após criar `v2-rules`, executamos `scripts/v2_compute_reference.py` sobre as estações locais de desenvolvimento já presentes no disco, calculando exclusivamente o controle de qualidade cego e os alertas de referência medida pelo sensor físico. Nenhuma fonte meteorológica candidata rodou na Fase 1.

## Situação do portal INRAE e do lockbox

Em 22 nov 2026, o comando `scripts/download_sensor_datasets.py --dry-run` continuou recebendo `HTTP 503 Service Unavailable` em manutenção no portal `entrepot.recherche.data.gouv.fr` para o DOI `10.57745/BQ0BWB`. Seguindo a regra do projeto, nenhuma das 50 estações extras do INRAE foi baixada antes da confirmação literal da licença, e o sorteio de `docs/v2/lockbox.txt` ficou pendente até o retorno do portal. O download das estações elegíveis, a execução cega do controle de qualidade sobre o lote completo e o commit do `docs/v2/lockbox.txt` ocorrerão assim que o portal voltar ao ar, antes de qualquer calibração de estimador ou avaliação de fontes candidatas.

## Resultados do controle de qualidade cego nas estações locais

Aplicamos `vitirule_v2/qc.py` às cegas sobre as 4 estações locais do INRAE de `2019 a 2025` e sobre as 7 estações do Politecnico di Torino de `2022 a 2024`, avaliando cada combinação estação-safra-cultura. Os números derivados do Politecnico di Torino abaixo são métricas agregadas obtidas a partir de dados sob licença CC BY-NC 4.0 do DOI `10.17632/sd4b8vpvyb.1`, sem redistribuição de dados brutos.

| Rede | Recorte temporal | Cultura | Aprovadas / Avaliadas | Principais motivos de reprovação |
|---|---|---|---|---|
| INRAE local, 4 estações v1 | Principal 2022–2025 | Videira | 11 / 16 | Lacuna acima de 24 h em 2022 e 2024; deriva de sensor em Bordeaux 2023 |
| INRAE local, 4 estações v1 | Principal 2022–2025 | Macieira | 12 / 16 | Lacuna acima de 24 h em 2022 e em Bordeaux 2023 |
| INRAE local, 4 estações v1 | Principal 2022–2025 | Tomateiro | 11 / 16 | Lacuna acima de 24 h em 2022 e 2024; deriva de sensor em Bordeaux 2023 |
| INRAE local, 4 estações v1 | Secundário 2019–2021 | Videira | 10 / 12 | Deriva de sensor em Bordeaux 2021; lacuna de 651 h em Bourgogne 2021 |
| INRAE local, 4 estações v1 | Secundário 2019–2021 | Macieira | 12 / 12 | Sem reprovações |
| INRAE local, 4 estações v1 | Secundário 2019–2021 | Tomateiro | 10 / 12 | Deriva de sensor em Bordeaux 2021; lacuna de 651 h em Bourgogne 2021 |
| Politecnico di Torino, 7 estações | Principal 2022–2025 | Videira | 2 / 7 | Deriva severa em `site2`; lacunas de telemetria de 210 h a 662 h em `site3`, `site4`, `site6`, `site7` |
| Politecnico di Torino, 7 estações | Principal 2022–2025 | Macieira | 2 / 7 | Mesmo padrão de `site2` e lacunas de telemetria nas demais |
| Politecnico di Torino, 7 estações | Principal 2022–2025 | Tomateiro | 2 / 7 | Mesmo padrão de `site2` e lacunas de telemetria nas demais |

Dois achados do filtro cego merecem registro direto:

1. **Rejeição objetiva de sensores com deriva ou travamento:** `site2.csv` do Politecnico caiu automaticamente em todas as culturas por violar simultaneamente fração molhada em ar seco de meio-dia acima de 15%, chegando a `24,2%` a `29,4%`, sequência molhada sem chuva acima de 96 h, chegando a `136 h` a `241 h`, e fração molhada total de `83,5%` na janela da macieira. O mesmo critério detectou uma falha real não percebida na v1 em Bordeaux-Couhins nos verões de 2021 e 2023, com sequências molhadas sem chuva de `309 h` e `287 h` e molhamento em ar seco de meio-dia entre `15,1%` e `20,6%`.
2. **Efeito do teto rígido de lacuna contínua de 24 h em redes IoT:** no Politecnico di Torino, apenas `site1` e `site5`, ambos de 2022, passaram no critério de `95%` de cobertura e lacuna máxima de `24 h`. Os sensores de molhamento de `site3`, `site4`, `site6` e `site7` estavam limpos, com molhamento em ar seco abaixo de `1%` e sequências sem chuva de até `25 h`, porém sofreram quedas de telemetria de `210 h` a `662 h`. No INRAE em 2022, três estações tinham cobertura acima de `95%` e sensores limpos, mas caíram por uma única lacuna entre `46 h` e `115 h`. Mantivemos o critério congelado sem qualquer alteração unilateral, conforme o protocolo experimental.

## Resumo dos alertas de referência medida na janela principal 2022–2025

| Rede | Estações-safra aprovadas por regra | Regra 3-10, eventos por safra | Goidànich, ciclos completos e duração mediana | Mills revisada, eventos por safra | TOM-CAST 15 DSV, pulverizações por safra |
|---|---|---|---|---|---|
| INRAE local, 4 estações v1 | 11 videira, 12 macieira, 11 tomateiro | 5 a 18 eventos | 5 a 17 ciclos; mediana de 6 a 8 dias | 8 a 22 eventos | 2 a 7 pulverizações, com 30 a 116 DSV |
| Politecnico di Torino, dados CC BY-NC 4.0 | 2 videira, 2 macieira, 2 tomateiro | 6 eventos em ambas | 4 a 5 ciclos; mediana de 6 a 10 dias | 6 eventos em ambas | 3 a 9 pulverizações, com 60 a 140 DSV |

Na série secundária longa do INRAE de `2019 a 2021`, foram aprovadas 10 estações-safra de videira, 12 de macieira e 10 de tomateiro, produzindo de 6 a 14 eventos de 3-10, 5 a 12 ciclos completos de Goidànich, 9 a 18 eventos de Mills e 1 a 6 pulverizações de TOM-CAST por safra.

## Por que cada escolha de regra foi feita

- **Regra 3-10 com janela de 48 h e chuva mínima de 0,2 mm no dia do disparo:** a janela de 48 h segue Baldacci (1947) e Goidànich (1964) sem partir chuvas que atravessam a meia-noite local. A exigência de `0,2 mm` no próprio dia impede que um dia completamente seco dispare um segundo alerta apenas pelo carrego da chuva da véspera, e o agrupamento de dias consecutivos garante um evento único por tempestade.
- **Goidànich com fator de umidade relativa de 0,85 abaixo de 75% e marco em 100%:** preserva a formulação completa de Goidànich (1964) sobre a curva de Müller & Sleumer (1934), testando também a fidelidade da umidade relativa entre fontes meteorológicas. O aviso preventivo de 80% fica salvo como metadado auxiliar.
- **Mills revisada com interrupção seca de até 8 h, exigência de 0,2 mm de chuva e interpolação linear:** o limite de 8 h segue a tabela operacional da OMAFRA associada a MacHardy & Gadoury (1989) e Stensvand et al. (1997), sem precisar de uma sub-regra adicional de umidade relativa que se comportaria de modo diferente entre sensor e reanálise. Exigir chuva de pelo menos `0,2 mm` evita que orvalho noturno sem chuva dispare infecções primárias por ascósporos. A interpolação linear reproduz exatamente todas as 21 linhas publicadas e evita degraus artificiais de 2 horas para variações mínimas de temperatura.
- **TOM-CAST com janela local de 12h a 12h, arredondamento half-up e dois modos de memória:** o recorte de meio-dia a meio-dia evita dividir o orvalho de uma mesma noite entre dois dias, seguindo Pitblado (1992) e Gillespie et al. (1993). O arredondamento aritmético half-up garante resultados idênticos entre Python e JavaScript na Fase 5. Implementar `self_reset` e `reference_reset` desde a Fase 1 permite separar o erro de cada intervalo da propagação acumulada de fase ao longo da safra.

## O que esta fase assume e onde pode falhar

- **Janelas fenológicas fixas por calendário:** sem observações fenológicas nas estações, anos de brotação precoce ou tardia podem deixar de fora um evento primário de março ou incluir dias ainda sem folha receptiva no início de abril. Como a mesma janela é aplicada à referência e a todas as candidatas, o erro de comparação entre fontes permanece pareado.
- **Amostra pequena enquanto o portal INRAE segue em 503:** com apenas 4 estações locais do INRAE e 2 estações aprovadas do Politecnico, ainda não há tamanho amostral suficiente nem lockbox sorteado para iniciar a avaliação definitiva. O retorno do portal INRAE é requisito para fechar o lockbox antes de calibrar qualquer modelo na Fase 2.
- **Critério rígido de 24 h de lacuna no Politecnico:** rejeitar 4 estações com sensores saudáveis reduz o Politecnico a 2 estações de 2022, impedindo inclusive qualquer checagem de 2024 nessa rede. Qualquer revisão do critério de lacuna contínua só pode ocorrer se aprovada explicitamente pelo autor antes de abrir métricas comparativas e registrada como desvio em `docs/v2/preregistro.md`.

## Referências principais da Fase 1

- Baldacci, E. (1947). *Atti dell'Istituto Botanico della Università di Pavia*, Serie 5, 8, 45–85.
- Becker, C. M., & Burr, T. J. (1994). *Phytopathology*, 84(7), 732–737. https://doi.org/10.1094/Phyto-84-732
- Gillespie, T. J., Srivastava, B., & Pitblado, R. E. (1993). *Journal of Applied Meteorology*, 32(3), 567–573. https://doi.org/10.1175/1520-0450(1993)032<0567:UOWDTS>2.0.CO;2
- Goidànich, G. (1964). *Manuale di Patologia Vegetale*, Vol. II. Edagricole, Bologna.
- MacHardy, W. E., & Gadoury, D. M. (1989). *Phytopathology*, 79(3), 304–310. https://doi.org/10.1094/PHYTO-79-304
- Madden, L., Pennypacker, S. P., & MacNab, A. A. (1978). *Phytopathology*, 68(9), 1354–1358. https://doi.org/10.1094/Phyto-68-1354
- Mills, W. D. (1944). Cornell Extension Bulletin 630, 4 pp.
- Müller, K., & Sleumer, H. (1934). *Landwirtschaftliche Jahrbücher*, 79, 509–576.
- Pitblado, R. E. (1992). *The development and implementation of TOM-CAST*. Ontario Ministry of Agriculture and Food, Ridgetown College, 24 pp.
- Rossi, V., Caffi, T., Giosuè, S., & Bugiani, R. (2008). *European Journal of Plant Pathology*, 121, 419–435. https://doi.org/10.1007/s10658-007-9254-7
- Schwabe, W. F. S., Jones, A. L., & Jonker, J. P. (1984). *Phytopathology*, 74(10), 1187–1190. https://doi.org/10.1094/Phyto-74-1187
- Stensvand, A., Gadoury, D. M., Amundsen, T., Semb, L., & Seem, R. C. (1997). *Phytopathology*, 87(10), 1046–1053. https://doi.org/10.1094/PHYTO.1997.87.10.1046
