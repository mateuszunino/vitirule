# Levantamento de implementações abertas antes de escrever código

Antes de implementar qualquer regra na v2, inspecionamos os repositórios abertos candidatos para verificar linguagem, licença, aderência às regras escolhidas e possibilidade de reuso ou uso como oráculo de teste.

## Repositórios inspecionados

| Projeto e origem | Linguagem | Licença verificada | Regras contidas | Avaliação para o vitirule v2 |
|---|---|---|---|---|
| NIBIO VIPS, GitLab do NIBIO | Java | NIBIO Open Source License baseada na AGPL-3.0 | Plataforma de alertas com modelos de sarna e TOM-CAST para batata | A instância `gitlab.nibio.no` retornou timeout de conexão na verificação. A documentação oficial do NIBIO declara que a licença aberta cobre apenas a infraestrutura da plataforma e exclui os modelos e algoritmos. Incompatível com MIT e indisponível para reuso direto. |
| `BigDataWUR/A-scab` e `WUR-AI/A-scab`, GitHub | Python e Jupyter Notebook | Sem arquivo de licença declarado no GitHub | Modelo mecanístico A-scab de Rossi et al. (2007) em ambiente Gymnasium | Implementa o simulador completo A-scab, não a tabela revisada de Mills por MacHardy e Gadoury (1989). Sem licença aberta explícita no repositório, o código não pode ser copiado nem portado. |
| `UW-Madison-DSI/ag_forecasting_api`, GitHub | Python | MIT | Modelos logísticos para mancha-de-alcatrão, cercosporiose, mancha-olho-de-rã e mofo-branco em milho e soja | Código limpo e sob licença MIT, verificado em `ag_models_wrappers/forecasting_models.py`. Não contém 3-10, Goidànich, Mills nem TOM-CAST. Serve apenas como referência de organização de interface. |
| `UW-Madison-DSI/crop_disease_forecasting_tool`, GitHub | R | Licença própria marcada como `NOASSERTION` no GitHub | Painel e previsão de mancha-de-alcatrão em milho sobre Wisconet | Focado em milho e escrito em R. Não contém as quatro regras da v2. |
| `GeoModelLab/octopus`, GitHub, Bregaglio et al. (2025) | Metal e código do projeto | CC BY-NC-ND 4.0 verificada em `LICENSE.txt` | Oito modelos de infecção primária do míldio da videira | A licença CC BY-NC-ND 4.0 proíbe obras derivadas e uso comercial. Não é legalmente compatível com portar ou adaptar código para um pacote MIT. |

## Decisão por regra da v2

| Regra | Referência primária | Decisão | Motivo e oráculo de teste |
|---|---|---|---|
| Regra 3-10 para míldio da videira | Baldacci (1947) | Reimplementar como função pura em Python sob MIT | A regra tem três condições objetivas e diretas. Não há implementação MIT limpa compatível com Pyodide. O oráculo de teste serão casos-limite construídos da definição publicada e conferência cruzada com `downy_mildew.py` da v1. |
| Índice de incubação de Goidànich para míldio da videira | Müller & Sleumer (1934); Goidànich (1964) | Reimplementar como função pura em Python sob MIT | O único código aberto encontrado, `octoPus`, está sob CC BY-NC-ND 4.0. A curva de temperatura e incubação publicada será o oráculo de teste, em conferência cruzada com a interpolação linear já validada na v1. |
| Tabela de Mills revisada para sarna da macieira | MacHardy & Gadoury (1989), *Phytopathology* 79:304–310 | Reimplementar como função pura em Python sob MIT | `A-scab` implementa outro modelo e não tem licença declarada; NIBIO VIPS exclui os modelos da licença aberta. O oráculo de teste serão as linhas exatas de temperatura e horas de molhamento da tabela revisada de MacHardy e Gadoury (1989), além das regras de interrupção seca. |
| TOM-CAST para pinta-preta do tomate | Pitblado (1988); Gillespie, Srivastava & Pitblado (1993) | Reimplementar como função pura em Python sob MIT | NIBIO VIPS é em Java com exclusão de modelos na licença. A tabela discreta de DSV já está verificada em 19 casos na suíte `tests/test_smoke.py` da v1, que servirá de oráculo junto com a tabela original publicada. |

## Resumo da decisão

Nenhuma das implementações externas pode ser reusada ou portada diretamente sem conflito de licença, diferença de modelo ou dependência incompatível com o alvo de navegador via Pyodide. As quatro regras serão escritas como funções puras em Python no pacote novo da v2, com parâmetros isolados em arquivo próprio e testes ancorados diretamente nas tabelas primárias da literatura.
