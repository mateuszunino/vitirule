# Levantamento de implementações abertas antes de escrever código

Antes de implementar qualquer regra na v2, inspecionamos os repositórios abertos candidatos para verificar linguagem, licença, aderência às regras escolhidas e possibilidade de reuso.

## Repositórios inspecionados

| Projeto e origem | Linguagem | Licença verificada | Regras contidas | Avaliação para o vitirule v2 |
|---|---|---|---|---|
| NIBIO VIPS, GitLab do NIBIO | Java | NIBIO Open Source License baseada na AGPL-3.0 | Plataforma de alertas com modelos de sarna e TOM-CAST para batata | A instância `gitlab.nibio.no` retornou timeout de conexão na verificação. A documentação oficial do NIBIO declara que a licença aberta cobre apenas a infraestrutura da plataforma e exclui os modelos e algoritmos. Incompatível com MIT e indisponível para reuso direto. |
| `BigDataWUR/A-scab` e `WUR-AI/A-scab`, GitHub | Python e Jupyter Notebook | Sem arquivo de licença declarado no GitHub | Modelo mecanístico A-scab de Rossi et al. (2007) em ambiente Gymnasium | Implementa o simulador completo A-scab, não a tabela revisada de Mills por MacHardy e Gadoury (1989). Sem licença aberta explícita no repositório, o código não pode ser copiado nem portado. |
| `UW-Madison-DSI/ag_forecasting_api`, GitHub | Python | MIT | Modelos logísticos para mancha-de-alcatrão, cercosporiose, mancha-olho-de-rã e mofo-branco em milho e soja | Código limpo e sob licença MIT, verificado em `ag_models_wrappers/forecasting_models.py`. Não contém 3-10, Goidànich, Mills nem TOM-CAST. Serve apenas como referência de organização de interface. |
| `UW-Madison-DSI/crop_disease_forecasting_tool`, GitHub | R | Licença própria marcada como `NOASSERTION` no GitHub | Painel e previsão de mancha-de-alcatrão em milho sobre Wisconet | Focado em milho e escrito em R. Não contém as quatro regras da v2. |
| `GeoModelLab/octopus`, GitHub, Bregaglio et al. (2025) | Metal e código do projeto | CC BY-NC-ND 4.0 verificada em `LICENSE.txt` | Oito modelos de infecção primária do míldio da videira | A licença CC BY-NC-ND 4.0 proíbe obras derivadas e uso comercial. Não é legalmente compatível com portar ou adaptar código para um pacote MIT. |

## Decisão por regra e política de oráculos de teste

Os testes escritos na v1 não servem de oráculo para a v2 porque nasceram no mesmo processo que o código da v1. O gabarito de cada regra na v2 vem exclusivamente da tabela ou definição publicada na fonte primária. Qualquer comparação com os módulos congelados da v1 entra apenas como teste separado de consistência, identificado de forma explícita.

| Regra | Referência primária | Decisão | Oráculo primário de teste |
|---|---|---|---|
| Regra 3-10 para míldio da videira | Baldacci (1947); consolidação operacional em Goidànich (1964) e Rossi et al. (2008) | Reimplementar como função pura em Python sob MIT | Definição publicada de temperatura, chuva acumulada e janela fenológica, cobrindo casos-limite de borda e desagregação de tempestades consecutivas. |
| Índice de incubação de Goidànich para míldio da videira | Müller & Sleumer (1934); Goidànich (1964) | Reimplementar como função pura em Python sob MIT | Pontos publicados da tabela de duração de incubação por temperatura e umidade relativa, verificando a soma até 100% em cenários constantes e variáveis. |
| Tabela de Mills revisada para sarna da macieira | MacHardy & Gadoury (1989); extensão de baixas temperaturas em Stensvand et al. (1997) | Reimplementar como função pura em Python sob MIT | Linhas exatas de temperatura e horas mínimas de molhamento para infecção leve, moderada e severa da tabela publicada, além dos casos-limite da regra de interrupção seca. |
| TOM-CAST para pinta-preta do tomate | Madden, Pennypacker & MacNab (1978); Pitblado (1988, 1992); Gillespie, Srivastava & Pitblado (1993) | Reimplementar como função pura em Python sob MIT | Matriz completa de DSV de 0 a 4 por faixa de temperatura e horas molhadas publicada na fonte primária, além dos dois modos de reset de pulverização. |

## Resumo da decisão

Nenhuma das implementações externas pode ser reusada ou portada diretamente sem conflito de licença, diferença de modelo ou dependência incompatível com o alvo de navegador via Pyodide. As quatro regras serão escritas como funções puras em Python no pacote isolado `vitirule_v2`, com parâmetros e referências em `vitirule_v2/rules/params.json` e testes ancorados exclusivamente nas publicações primárias.
