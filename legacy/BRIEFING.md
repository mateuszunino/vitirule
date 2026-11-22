# DSS de doenças foliares do tomateiro: briefing do projeto

Leia este arquivo antes de qualquer outro. Ele explica o que o projeto é, em que pé está e em que ordem o trabalho deve ser feito. O `SKILL.md` traz os contratos JSON, o esquema do banco e as regras agronômicas em detalhe. Quando os dois parecerem discordar, vale este briefing para a ordem e o escopo do trabalho e o `SKILL.md` para os detalhes técnicos.

## 1. O projeto em poucas linhas

É um Sistema de Apoio à Decisão (DSS) para duas doenças foliares do tomateiro em Santa Catarina: a pinta-preta, causada pelo fungo *Alternaria solani*, e a requeima, causada pelo oomiceto *Phytophthora infestans*.

O sistema faz quatro coisas em ciclo:

1. mede a severidade da doença numa folha a partir de um vídeo curto;
2. coleta o clima observado e a previsão dos próximos 7 dias;
3. ajusta uma curva de progresso da doença com as medições e projeta a próxima semana;
4. recomenda aplicar fungicida, monitorar ou não fazer nada.

A aplicação registrada volta para o modelo. A próxima medição corrige a previsão. Por isso o projeto é chamado de circuito fechado.

## 2. Mudança de plano: primeiro o modelo, depois o experimento

O plano original previa um ensaio com 20 vasos em São José/SC rodando ao mesmo tempo que o desenvolvimento. **Esse ensaio não vai acontecer agora.** O autor não tem condições de conduzi-lo neste momento.

A nova ordem é:

1. **Construir** o sistema inteiro e fazê-lo funcionar sem plantas, com dados públicos, dados históricos de clima e dados simulados.
2. **Verificar** cada parte contra critérios objetivos (seção 7).
3. **Só depois**, quando houver condições, rodar o experimento de validação descrito na seção 6, Fase 4.

Consequências práticas para quem programa:

* Nenhuma tarefa pode depender de vídeos dos vasos, de folhas marcadas ou de aplicações reais, porque eles ainda não existem.
* Tudo o que o `SKILL.md` diz sobre os vasos `V01` a `V20`, as 60 folhas e a regra de decisão por vaso continua valendo como **desenho** do sistema. Os identificadores, as tabelas e as rotas devem ser implementados como estão. O que muda é a origem dos dados: até a Fase 4, eles vêm do simulador da seção 5.3.
* O sistema precisa de um **modo simulação** desde o começo. Ele é a forma de testar o circuito fechado de ponta a ponta sem lavoura.

## 3. Por que o problema importa

Pinta-preta e requeima estão entre as doenças mais destrutivas do tomateiro. A requeima pode destruir uma lavoura em poucos dias com tempo frio e úmido. A pinta-preta avança mais devagar, favorecida por calor e molhamento foliar prolongado.

Muitos produtores aplicam fungicida por calendário fixo, por exemplo uma vez por semana, chova ou faça sol. Isso gasta produto e mão de obra quando o tempo está seco e pode deixar a lavoura desprotegida quando o tempo vira. Os sistemas de previsão clássicos corrigem parte disso usando o clima:

* **TOM-CAST**, para a pinta-preta: soma valores diários de severidade (DSV, de 0 a 4) a partir das horas de molhamento foliar e da temperatura. Aplica-se quando a soma passa de um limiar.
* **Wallin / BLITECAST**, para a requeima: soma valores de severidade a partir das horas seguidas de umidade alta e da temperatura.

Esses sistemas olham só para o clima. A ideia deste projeto é juntar o clima com a **medição da doença na própria folha**, para a previsão aprender com o que de fato está acontecendo na planta.

A pergunta científica, a ser respondida na Fase 4, é: **um manejo guiado por uma previsão que aprende com a planta e com o clima controla a doença tão bem quanto o calendário fixo, ou melhor, usando menos aplicações?**

## 4. Arquitetura

```
vídeo da folha ──> visão computacional ──> severidade (%) por folha
                                               │
                                   média por planta e por dia
                                               ▼
coletor de clima ──> banco ──> modelo epidemiológico ──> projeção de 7 dias + AACPD
                                               │
                                               ▼
                                   motor de decisão ──> aplicar / monitorar / nada
                                               │
                                registro da aplicação ──> volta para o modelo
```

| Componente | Arquivo | Situação |
|---|---|---|
| Visão computacional | `vision_pipeline.py` | pronto, falta treinar os pesos |
| Modelo epidemiológico | `epidemiology_assimilation.py` | pronto e testado com dados simulados |
| Coletor de clima | `weather_collector.py` | pronto, testado com respostas simuladas e PostgreSQL local; falta rodar contra as APIs reais |
| Testes | `tests/test_smoke.py` | 46 testes, rodam sem rede, sem banco e sem GPU |
| Simulador | `simulator.py` | **a implementar**, seção 5.3 |
| Motor de decisão | `decision_engine.py` | a implementar, contrato no `SKILL.md`, seção 5.4 |
| Acesso ao banco | `db.py` | a implementar |
| API | `app.py` | a implementar, rotas no `SKILL.md`, seção 5.5 |
| Análise em R | `r/aacpd_validacao.R` | a implementar |

### Stack

* Python 3.10 ou mais novo, Flask no backend.
* Banco Supabase (PostgreSQL), acesso por `psycopg2`.
* Treino dos modelos de visão no Google Colab.
* Desenvolvimento e inferência numa GPU NVIDIA GTX 1660 Super com 6 GB. Essa placa tem problema conhecido com meia precisão (FP16). O pipeline já testa e cai para FP32 sozinho. Não force FP16.
* Estatística final em R, com `agricolae` ou `epifitter` para a AACPD e `metan` para as análises.

## 5. O que cada parte faz

### 5.1 Visão computacional (`vision_pipeline.py`)

Entrada: vídeo `.mp4` de 4 a 5 segundos, 1080p, com a folha aberta sobre um fundo de EVA azul-royal ou cinza e um quadrado de referência de 2 x 2 cm no mesmo plano.

Etapas:

1. Escolhe de 3 a 5 quadros nítidos pela variância do Laplaciano e descarta quadros quase repetidos.
2. **Estágio A**: um modelo YOLO de segmentação acha a folha e o quadrado de referência. O quadrado converte pixels em cm².
3. **Estágio B**: outro modelo YOLO de segmentação, rodando só dentro da folha, acha as lesões necróticas e os halos cloróticos.
4. Alinha os quadros entre si e decide cada pixel por voto da maioria, para uma lesão vista em cinco quadros não ser contada cinco vezes.
5. Devolve `severidade (%) = área lesionada / área total da folha x 100`, as áreas em mm² e cm² e uma lista de alertas de qualidade.

Sem pesos treinados, o pipeline usa limiares de cor como reserva. Isso serve para pré-anotar imagens e testar o encadeamento. Não serve como medição.

A visão **não distingue** pinta-preta de requeima. Ela mede necrose e clorose. A doença é informada por quem registra a planta.

### 5.2 Modelo epidemiológico (`epidemiology_assimilation.py`)

* A doença não avança por dia de calendário. Avança por **dias favoráveis acumulados**, calculados hora a hora pela temperatura e pelo molhamento foliar estimado. Molhamento estimado é umidade relativa igual ou acima de 85 % ou chuva na hora.
* Sobre esse tempo, ajusta uma curva logística ou de Gompertz. O parâmetro principal é `r`, a taxa de progresso da doença.
* A cada nova medição, reajusta `r` por mínimos quadrados ponderados, com uma estimativa inicial tirada da literatura. Medições recentes pesam mais.
* Compara a medição nova com o que o ajuste anterior previa. Se a diferença for grande demais, marca mudança de regime e reajusta com mais peso no presente.
* Projeta os próximos 7 dias com intervalo de 95 %, usando a previsão do tempo.
* Calcula a AACPD, a área abaixo da curva de progresso da doença, pela regra dos trapézios.
* Também calcula o DSV do TOM-CAST e o índice de Wallin para a semana prevista.

### 5.3 Simulador (`simulator.py`), a implementar

É a peça nova que a mudança de plano exige. Ele substitui as plantas até a Fase 4.

O simulador deve:

1. Criar plantas virtuais com os mesmos identificadores do `SKILL.md`: vasos `V01` a `V20` e folhas `V01-F1` a `V20-F3`. Os vasos `V01` a `V10` são testemunha, sem aplicação. Os vasos `V11` a `V20` seguem o motor de decisão.
2. Sortear para cada vaso uma taxa `r` verdadeira e uma severidade inicial, a partir das prioris de `PATHOGENS` em `epidemiology_assimilation.py`, com variação entre vasos.
3. Avançar a doença com **clima real**: dados históricos do banco ou de um CSV, reproduzidos hora a hora. Isso deixa a simulação presa a estações de verdade em Santa Catarina.
4. Gerar a cada 2 ou 3 dias uma "medição" por folha, com ruído parecido com o do pipeline de visão: erro mínimo de cerca de 0,3 ponto percentual mais 10 % da severidade.
5. Aplicar o efeito de cada pulverização recomendada, com a mesma eficácia e meia-vida usadas no modelo.
6. Rodar o circuito inteiro: medições -> assimilação -> decisão -> aplicação -> novas medições.
7. Gravar o resultado no mesmo formato e nas mesmas tabelas que os dados reais vão usar. A única diferença é uma coluna ou flag `simulated = true`.
8. Produzir no final a AACPD por vaso e o número de aplicações de cada grupo, para a análise em R.

Com isso dá para responder, antes de ter plantas, se a regra de decisão faz sentido. Por exemplo: o grupo manejado pelo DSS termina com AACPD menor que a testemunha? Quantas aplicações gasta em comparação com um calendário semanal? O resultado varia muito de uma estação para outra?

O simulador **não prova** que o sistema funciona no campo. Ele só mostra que o sistema é coerente com as suposições do próprio modelo. A prova vem da Fase 4.

### 5.4 Coletor de clima (`weather_collector.py`)

Roda de hora em hora. Busca as últimas 72 horas observadas e as próximas 168 horas previstas para São José/SC, latitude -27.5969 e longitude -48.6367. Grava tudo na tabela `weather_hourly`.

Ordem das fontes:

1. **Epagri/Ciram**, estação do Itacorubi. A Epagri não oferece API aberta de dados horários. O coletor lê o CSV baixado do portal de dados ambientais, ou um endpoint JSON se o Ciram liberar acesso.
2. **INMET**, estação automática A806.
3. **Open-Meteo**, única fonte de previsão horária com API aberta. As horas passadas que vêm dele são análise de modelo, não medição.

Fonte melhor sobrescreve fonte pior para a mesma hora, nunca o contrário. Todo horário é gravado em UTC e exibido no fuso de São Paulo.

O coletor pode e deve começar a rodar **já**. Cada semana de clima gravada agora vira dado para o simulador e para o ajuste dos parâmetros.

### 5.5 Motor de decisão (`decision_engine.py`), a implementar

Regras completas no `SKILL.md`, seção 7.4. Em resumo, recomenda aplicar quando:

* o DSV acumulado do TOM-CAST desde a última aplicação chega a 15, no caso da pinta-preta;
* o índice de Wallin da última semana chega a 5, no caso da requeima;
* a probabilidade de a severidade passar de 5 % em 7 dias é de 50 % ou mais.

Respeita um intervalo mínimo de 7 dias entre aplicações. Nunca recomenda nada para a testemunha. Nunca escolhe produto nem dose: isso é do receituário agronômico.

Esses limiares são do projeto e ainda precisam ser confirmados. Devem ficar em constantes fáceis de mudar, porque o simulador vai servir justamente para testar valores diferentes.

## 6. Fases do trabalho

### Fase 1: visão computacional sem experimento

Objetivo: treinar os pesos dos estágios A e B e saber o quanto o pipeline erra.

1. **Dados de imagem.** Procurar primeiro conjuntos públicos de folhas de tomateiro com pinta-preta e requeima. O PlantVillage tem essas duas classes, mas são fotos de laboratório, com uma folha sobre fundo liso e sem máscara de lesão. Procurar também no Kaggle, no Roboflow Universe e no Zenodo conjuntos que já tragam máscaras de lesão. Conferir a licença de cada um antes de usar.
2. **Anotação.** Onde não houver máscara, anotar um subconjunto com ferramenta semiautomática do tipo SAM, corrigindo à mão. O autor já fez isso no TCC com `pliman` e PerSAM.
3. **Vídeos próprios, se possível.** Folhas doentes colhidas de hortas ou feiras, filmadas no protocolo do projeto, com EVA e quadrado de referência. Mesmo poucas dezenas de vídeos já mostram se o modelo treinado em foto de laboratório funciona em vídeo. Isso não é o experimento, porque não há acompanhamento no tempo nem tratamento.
4. **Treino** no Colab com modelos YOLO de segmentação pequenos, versões `n` ou `s`.
5. **Divisão treino e validação** por planta ou por fonte de imagem, nunca por quadro. Quadros do mesmo vídeo dos dois lados inflam a métrica.

### Fase 2: clima e modelo epidemiológico sem experimento

1. Pôr o coletor para rodar por cron e acumular dados.
2. Importar o histórico de 24 meses do CSV da Epagri e do INMET para o banco.
3. **Retrospectiva:** calcular o DSV do TOM-CAST e o índice de Wallin dia a dia nesses 24 meses. Ver se os períodos de risco alto batem com as épocas em que essas doenças costumam aparecer na região, segundo boletins técnicos da Epagri e a literatura.
4. Testar o modelo epidemiológico com epidemias simuladas, conferindo se o intervalo de 95 % contém o valor verdadeiro em cerca de 95 % dos casos. Isso já foi feito uma vez. Deve virar teste automático.
5. Procurar na literatura curvas de progresso publicadas dessas duas doenças para conferir as prioris de `r` e as temperaturas cardinais.

### Fase 3: backend e simulador

1. `db.py`, com todo o acesso ao banco.
2. `simulator.py`, seção 5.3.
3. `decision_engine.py`, seção 5.5.
4. `app.py`, com as rotas do `SKILL.md`.
5. Rodar o simulador sobre várias estações históricas e comparar três estratégias: testemunha, calendário semanal e DSS.
6. Exportar a AACPD por vaso para o R e fazer a mesma análise que será feita no experimento real. Assim o script de R fica pronto e testado antes de existirem dados de campo.

### Fase 4: experimento de validação (futuro)

Só quando houver condições. O desenho já está definido no `SKILL.md`, seção 1:

* 20 vasos, delineamento inteiramente casualizado;
* `V01` a `V10` como testemunha e `V11` a `V20` manejados pelo DSS. Vale considerar um terceiro grupo com calendário semanal, se houver vasos para isso;
* 3 folhas marcadas por vaso, avaliadas por vídeo a cada 2 ou 3 dias;
* o vaso é a unidade experimental e as folhas são subamostras. Tratar as 60 folhas como repetições é pseudorrepetição;
* variáveis de resposta: AACPD por vaso e número de aplicações.

O sistema construído nas fases anteriores deve servir aqui sem mudança de código. Só troca a origem dos dados, do simulador para os vídeos reais.

## 7. O que conta como "funciona"

| Parte | Critério |
|---|---|
| Visão | Concordância de Lin de 0,90 ou mais entre a severidade do pipeline e a anotada à mão, em imagens de validação nunca vistas no treino. Meta do projeto, a confirmar. |
| Calibração de área | Erro de área foliar abaixo de 5 % em vídeos com quadrado de referência. |
| Coletor | Pelo menos 80 % das últimas 72 h com temperatura e umidade, e 90 % das próximas 168 h com previsão. |
| Modelo epidemiológico | Intervalo de 95 % cobrindo o valor verdadeiro entre 90 % e 98 % das vezes em epidemias simuladas. AACPD igual à do R até a sexta casa decimal. |
| Circuito fechado | O simulador roda uma estação inteira sem erro. A AACPD do grupo DSS fica abaixo da testemunha. |
| Código | `python -m pytest tests/ -q` sem falha. |

## 8. Regras para o agente

1. **Antes de implementar algo novo, procure no GitHub projetos open-source que já resolvam o problema.** Compare duas ou três abordagens e só então escreva código. Explique a escolha.
2. Os três módulos prontos já funcionam. Importe e chame. Não reescreva nem duplique a lógica deles.
3. Não invente nome de campo, tabela, coluna, rota, classe de modelo, limiar ou unidade. Se não estiver no `SKILL.md` nem no código, pergunte.
4. Todo horário trafega em ISO 8601 com fuso e é gravado em UTC.
5. Severidade é sempre percentual de 0 a 100.
6. Dado simulado sempre marcado como simulado. Nunca misture com dado real sem essa marca.
7. Não preencha clima ausente com valor inventado. Hora sem dado fica nula.
8. Não coloque senha nem token no código, no log ou no commit. Use `.env`.
9. Não escreva `TODO`, `pass` ou função vazia e chame isso de pronto.
10. Ao terminar uma tarefa, diga o que fez, o que testou e o que ficou sem testar.

## 9. Pontos em aberto

Não resolva sozinho. Pergunte ao autor.

* Se a hora do CSV da Epagri é local ou UTC. O manual do portal não diz.
* Se as rotas da API do INMET e a exigência de token continuam as mesmas.
* Os limiares de decisão e as temperaturas cardinais dos dois patógenos.
* Se haverá vídeos próprios de folhas doentes na Fase 1 e de onde virão.
* As estações meteorológicas ficam longe de onde as plantas estarão. O molhamento estimado por umidade de estação distante é a maior fonte de erro do modelo climático. Um sensor de temperatura e umidade junto às plantas, na Fase 4, reduziria esse erro.

## 10. Glossário

| Termo | Significado |
|---|---|
| DSS | sistema de apoio à decisão |
| Severidade | porcentagem da área da folha com lesão |
| AACPD | área abaixo da curva de progresso da doença, em % x dia |
| DSV | valor diário de severidade do TOM-CAST, de 0 a 4 |
| Índice de Wallin | valor diário de severidade para requeima, de 0 a 4 |
| `r` | taxa de progresso da doença na curva logística ou de Gompertz |
| Dia favorável | unidade de tempo do modelo: um dia inteiro de clima ótimo para a doença |
| Testemunha | grupo sem nenhum manejo, usado como comparação |
| Keyframe | quadro nítido do vídeo escolhido para a medição |
| Circuito fechado | medir, prever, decidir, aplicar e medir de novo |
