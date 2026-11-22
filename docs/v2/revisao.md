# Revisão curta de literatura: efeito da fonte meteorológica em alertas de doenças de plantas

Esta revisão verifica se existe na literatura aberta uma avaliação sistemática que compare fontes gratuitas de clima pelo efeito direto no disparo de alertas fitossanitários, usando sensores reais de molhamento foliar como referência e cobrindo mais de uma regra publicada.

## Trabalhos analisados

| Estudo | Doença e cultura | Região | Fontes comparadas | Métrica principal | Código aberto |
|---|---|---|---|---|---|
| Duttweiler et al. (2008), *Plant Disease* 92:1215–1222, DOI 10.1094/PDIS-92-8-1215 | Fuligem e pinta-de-mosca em maçã | Iowa e Meio-Oeste dos EUA | Estação no pomar com sensor de molhamento contra estimativa comercial site-specific sem sensor | Acumulado de horas molhadas, data do alerta e incidência no campo | Não |
| Kim, Beresford & Henshall (2008), *New Zealand Plant Protection* 61:296–300 | Podridão-cinzenta em videira | Nova Zelândia | Estação medida contra interpolação espacial e vizinho mais próximo | Modelo econômico de custo-perda e valor financeiro do alerta | Não |
| Gleason et al. (2008), *Scientia Agricola* 65:76–87 | Revisão multicultura sobre sistemas de alerta | EUA, Canadá, Itália e Brasil | Sensores de molhamento, estações convencionais e modelos empíricos de LWD | Erro de duração de molhamento e síntese de impactos operacionais | Não |
| Rowlandson et al. (2015), *Plant Disease* 99:310–319, DOI 10.1094/PDIS-05-14-0529-FE | Revisão multicultura sobre LWD em alertas | Américas e Europa | Sensores de campo, modelos físicos, CART, lógica nebulosa e UR | Erro médio absoluto em horas por dia e acertos de molhamento | Não |
| Asadi & Tian (2021), *Agric. Forest Meteorol.* 307:108548, DOI 10.1016/j.agrformet.2021.108548 | Sem regra de doença aplicada | Estados Unidos | Reanálise NLDAS-2 e ERA5 com modelos de machine learning contra sensores de LWD | Acurácia, F1, erro em horas de molhamento | Não publicado como pacote de alertas |
| Cavalcanti (2021), Embrapa Circ. Téc. 124; Cavalcanti, Botton & Fioravanço (2024), Embrapa Bol. Pesq. 30 | Míldio da videira | Serra Gaúcha, Brasil | Redes locais de microestações IoT com algoritmo MAHM contra manejo do produtor | Redução no número de pulverizações e controle em campo | Não |
| Bregaglio et al. (2025), *SoftwareX* 30:102085, DOI 10.1016/j.softx.2025.102085 | Míldio da videira, infecções primárias | Itália | Oito modelos de infecção primária combinados por ensemble sobre dados de estação | Desempenho de detecção de infecções primárias | Sim, sob CC BY-NC-ND 4.0 |
| Mensah et al. (2026), *Int. J. Biometeorol.*, DOI 10.1007/s00484-026-03285-3 | Queima floral da macadâmia | Queensland, Austrália | Quatro fontes: sensor no dossel, estação na fazenda, estação BOM e grade SILO | Erros de previsão de infecção por patógeno e concordância entre fontes | Não |

## O que essa literatura mostra

Os estudos mais antigos, como Duttweiler et al. (2008) em Iowa e Kim et al. (2008) na Nova Zelândia, já demonstravam que substituir a estação local por clima estimado ou interpolado muda a data do alerta e o retorno econômico do manejo. No caso da Nova Zelândia, a avaliação passou por uma análise de custo-perda, mas restrita a uma doença, uma região e interpolação entre estações locais, sem reanálise global gratuita nem código aberto.

Na linha de molhamento foliar, Gleason et al. (2008), Rowlandson et al. (2015) e Asadi & Tian (2021) concentraram o foco no erro da variável meteorológica em horas por dia. Eles mostram com clareza que estimar molhamento sobre reanálise degrada a precisão, porém não traduzem esse erro em alertas perdidos, alarmes falsos e atraso em dias para regras clássicas de decisão.

Os trabalhos recentes de 2024 a 2026 chegam mais perto do problema, mas cada um cobre apenas uma fatia. O MAHM da Embrapa opera em vinhedos brasileiros com boa resposta operacional, mas seu algoritmo é fechado e não compara fontes gratuitas contra sensores de molhamento. O octoPus de Bregaglio et al. (2025) abre o código de oito modelos para míldio sob licença restritiva CC BY-NC-ND 4.0, mas foca na combinação de modelos biológicos e não na troca entre fontes climáticas gratuitas. O trabalho de Mensah et al. (2026) em Queensland é o paralelo mais próximo ao desenho da v2, pois compara quatro fontes climáticas diretamente na saída do modelo de doença, porém cobre apenas queima floral da macadâmia na Austrália, usa a grade regional SILO em vez de reanálises globais gratuitas e não disponibiliza código aberto nem pré-registro com lockbox.

## Conclusão sobre a lacuna

A lacuna se confirma. Não encontramos na literatura um protocolo aberto, pré-registrado e com lockbox geográfico que compare fontes meteorológicas gratuitas globais contra estações com sensor real de molhamento, medindo o impacto direto em alertas perdidos, alarmes falsos e atraso em dias para múltiplas regras clássicas publicadas em mais de uma cultura e região. Podemos avançar com o desenho da v2.
