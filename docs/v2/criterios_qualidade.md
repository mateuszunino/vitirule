# Critérios de controle de qualidade de estações e sensores de molhamento

Estes critérios são definidos na Fase 0, antes de baixar ou inspecionar qualquer estação nova da rede INRAE AgroClim. Nenhuma estação será excluída por nome. Depois de aprovados pelo autor e congelados no pré-registro, os mesmos filtros serão aplicados automaticamente a todas as estações-safra do INRAE, do Politecnico di Torino e, na Fase 4, das redes brasileiras.

## 1. Unidade de avaliação: estação-safra

Cada registro de controle de qualidade avalia uma **estação-safra**, definida como uma estação específica durante a janela fenológica fixa de um ano civil para uma regra. Uma estação pode ser aprovada em um ano e rejeitada em outro se houve falha de sensor apenas naquele ano.

## 2. Regras de integridade e cobertura horária

Para cada janela de safra, todas as quatro variáveis obrigatórias de referência são checadas: temperatura do ar, umidade relativa, precipitação horária e leitura do sensor de molhamento foliar.

1. **Cobertura mínima na janela da safra:** pelo menos **95,0%** das horas esperadas devem conter valores válidos e não nulos em todas as quatro variáveis simultaneamente.
2. **Lacuna contínua máxima:** nenhuma variável obrigatória pode ter falha contínua superior a **24 horas consecutivas** dentro da janela da safra. Lacunas curtas de até 24 horas serão registradas no relatório de qualidade e tratadas de forma idêntica para a referência e para as fontes candidatas, mascarando as mesmas horas faltantes na comparação.
3. **Carimbo de tempo único e monotônico:** timestamps duplicados, fora de ordem ou sem fuso horário explícito rejeitam o arquivo até correção documentada de leitura.

## 3. Limites físicos das variáveis meteorológicas

Leituras fora dos intervalos fisicamente plausíveis para agricultura temperada e subtropical são marcadas como inválidas e contam contra o limite de cobertura da seção 2:

- Temperatura do ar: de `-20 °C` a `50 °C`.
- Umidade relativa: de `5%` a `100%`, aceitando leituras entre `100%` e `105%` apenas se documentadas pelo fabricante como saturação e truncadas a `100%`.
- Precipitação horária: de `0 mm/h` a `150 mm/h`. Valores negativos são marcados como inválidos.
- Sensor de molhamento: na escala original da rede, `[0, 1]` horas no INRAE ou valores não negativos no Politecnico, binarizado pela definição congelada de cada rede.

## 4. Detecção objetiva de deriva ou travamento do sensor de molhamento

Sensores resistivos e capacitivos de molhamento podem apresentar deriva de linha de base, sujeira ou curto-circuito que os faz reportar folha molhada de forma quase permanente, ou desconexão que os mantém zerados. Aplicamos quatro critérios objetivos por estação-safra:

1. **Fração mínima de horas molhadas:** pelo menos **1,0%** das horas válidas da safra devem ser classificadas como molhadas. Abaixo disso, presume-se sensor desconectado, insensível ou safra sem sinal útil para avaliação de alertas.
2. **Fração máxima de horas molhadas:** no máximo **80,0%** das horas válidas da safra podem ser classificadas como molhadas. Acima desse teto, a série indica travamento ou deriva severa de linha de base.
3. **Teste de falso molhamento em ar seco:** selecionam-se todas as horas válidas sem chuva na janela em que a umidade relativa medida na própria estação é menor que **60%** e a hora local fica entre 11h e 16h. Se o sensor acusar molhamento em mais de **15,0%** dessas horas secas de meio-dia, a estação-safra é rejeitada por deriva de sensor. Esse critério exige apenas temperatura, UR, chuva e hora local, funcionando mesmo em redes sem piranômetro.
4. **Sequência molhada ininterrupta sem chuva:** qualquer sequência contínua de mais de **96 horas seguidas** de sensor molhado em que a precipitação acumulada nos últimos 3 dias da sequência seja menor que `0,2 mm` indica travamento e rejeita a estação-safra.

## 5. Separação entre desenvolvimento e lockbox

Depois de aplicar os filtros das seções 2 a 4 de forma automática:

1. As 4 estações do INRAE e as 7 estações do Politecnico usadas na v1 ficam obrigatoriamente fora do lockbox, pois já participaram da avaliação de estimadores na v1. Todas as estações-safra aprovadas do Politecnico ficam no conjunto de desenvolvimento.
2. Entre as estações novas do INRAE que tiverem pelo menos duas safras aprovadas no controle de qualidade, sorteia-se **20%** das estações, com mínimo de 2 estações, para `docs/v2/lockbox.txt`, estratificando por grande região climática ou administrativa se o número de estações aprovadas permitir.
3. O sorteio usa gerador pseudoaleatório com semente fixa declarada no commit de criação do `docs/v2/lockbox.txt`.
4. Os dados das estações sorteadas para o lockbox passam apenas pelo script automático de controle de qualidade e não são abertos para nenhuma inspeção exploratória até a tag `v2-lockbox` na Fase 3.

## 6. O que este critério assume e onde pode falhar

- O critério de 15% de molhamento em ar seco de meio-dia assume que não há irrigação por aspersão atingindo o sensor da estação. Estações instaladas dentro de talhões irrigados por aspersão podem ser rejeitadas por falso positivo de deriva, o que na prática também é desejável porque a reanálise não enxerga irrigação artificial.
- O limite de cobertura de 95% pode descartar estações com uma única semana de manutenção no meio da safra. Escolhemos esse valor rígido para evitar que lacunas escondam justamente o principal evento de infecção da temporada.
- A verificação de consistência do critério sobre o Politecnico di Torino, onde `site2.csv` teve 99,9% de leituras positivas na v1, só será executada na Fase 1 após sua aprovação deste documento.
