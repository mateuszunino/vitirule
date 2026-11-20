# Protocolo Experimental e Orçamento: Ensaio de Tomateiro em Vasos (DSS Fitopatológico)

**Local:** Quintal residencial — São José / Grande Florianópolis, SC  
**Estação Meteorológica de Referência:** EPAGRI/CIRAM — Florianópolis (Itacorubi / INMET A806)  
**Duração:** 8 Semanas (Ciclo de Verão: Novembro – Janeiro)  
**Objetivo:** Gerar série temporal de vídeos/imagens de alta qualidade para treino e validação de visão computacional (severidade foliar) acoplada a modelos epidemiológicos (TOM-CAST / curvas de progresso) e previsão meteorológica da EPAGRI.

---

## 1. Lista de Compras e Orçamento Estimado (São José / Grande Florianópolis)

Valores baseados em preços médios de agropecuárias locais (ex: Agropecuária Koerich, Casas da Água, Cassol, lojas de jardinagem em São José/Florianópolis) e plataformas online.

| Categoria | Item | Quantidade | Preço Unit. Est. (R$) | Subtotal Est. (R$) | Especificação / Observação |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Recipientes** | Vaso plástico preto de cultivo (12 L a 15 L) | 20 un. | 6,50 | 130,00 | Modelos flexíveis de viveiro ("vaso pote 15L") são muito mais baratos que vasos decorativos. |
| **Substrato** | Terra vegetal peneirada (saco 20 kg ou 25 L) | 8 sacos (~180 L) | 14,00 | 112,00 | Base estrutural do substrato (60% do volume total de ~280 L). |
| **Substrato** | Húmus de minhoca ou composto orgânico (saco 20 kg) | 4 sacos (~80 L) | 18,00 | 72,00 | Matéria orgânica e retenção de umidade (30% do volume). |
| **Substrato** | Areia grossa lavada ou casca de arroz carbonizada (saco 20 kg) | 2 sacos (~30 L) | 12,00 | 24,00 | Garante drenagem e evita encharcamento radicular (10% do volume). |
| **Material Vegetal** | Mudas de tomateiro (porte determinado, ex: *Santa Clara*, *IPA-6* ou *Cereja Anão*) | 24 mudas | 1,50 | 36,00 | Comprar 4 mudas extras de reserva para eventual replantio na Semana 1. Evitar híbridos F1 super-resistentes. |
| **Tutoramento** | Estacas de bambu (1,20 m a 1,50 m) | 20 un. | 2,50 | 50,00 | Pode ser substituído por taquara coletada gratuitamente se disponível. |
| **Tutoramento** | Rolo de fitilho plástico ou barbante de algodão | 1 rolo | 8,00 | 8,00 | Para amarração das hastes às estacas sem estrangular o caule. |
| **Nutrição** | Fertilizante mineral NPK 4-14-8 (pacote 1 kg) | 1 pct | 14,00 | 14,00 | Adubação de plantio (15 g por vaso = 300 g total). |
| **Nutrição** | Fertilizante mineral NPK 10-10-10 (pacote 1 kg) | 1 pct | 14,00 | 14,00 | Adubação de cobertura quinzenal (5 g/vaso a cada 15 dias). |
| **Manejo ($T_2$)** | Calda bordalesa pronta (pó 200 g) **OU** Biofungicida (*Bacillus subtilis* / *Trichoderma* 100 mL) | 1 un. | 28,00 | 28,00 | Aplicado *apenas* no grupo $T_2$ quando o algoritmo atingir o limiar de ação. |
| **Manejo ($T_2$)** | Pulverizador manual de compressão prévia (1,5 L ou 2 L) | 1 un. | 32,00 | 32,00 | Uso exclusivo para aplicação de tratamento no grupo $T_2$. |
| **Visão Comp.** | Placa de EVA fosco (azul-royal ou cinza neutro, 40x60 cm) + prancheta rígida | 2 folhas + 1 prancheta | 12,00 | 12,00 | Fundo padrão de alto contraste para isolamento da folha nas filmagens. |
| **Identificação** | Etiquetas plásticas de identificação / fita crepe + caneta permanente | 1 kit | 15,00 | 15,00 | Identificação dos vasos (`V01`–`V20`) e marcação das 60 folhas (`F1`–`F3`). |
| **TOTAL ESTIMADO** | — | — | — | **R$ 533,00** | *Pode cair para ~R$ 380,00 reaproveitando baldes/bambu e comprando substrato a granel.* |

---

## 2. Preparo Inicial e Delineamento Experimental (Dia 0)

### Preparo do Substrato e Plantio
1. Misture homogeneamente os componentes na proporção **6 : 3 : 1** (6 partes de terra vegetal + 3 partes de húmus/composto + 1 parte de areia grossa).
2. Incorpore **15 g (1 colher de sopa rasa) de NPK 4-14-8** por vaso nos 15 cm superiores do substrato.
3. Transplante 1 muda por vaso no final da tarde, enterrando o caule até a inserção das primeiras folhas cotiledonares (estimula raízes adventícias e dá firmeza).
4. Insira a estaca de bambu a 5 cm da muda e regue abundantemente apenas o solo.

### Delineamento Estatístico: DIC (Delineamento Inteiramente Casualizado)
* **Unidade Experimental:** 1 vaso = 1 repetição ($n = 20$ vasos).
* **Separação Física:** Divida o quintal em duas sub-áreas separadas por pelo menos **2,5 metros** (ou instale uma lona/plástico transparente de 1,20 m de altura entre os grupos) para evitar que a pulverização do $T_2$ atinja o $T_1$ por deriva do vento.
* **Espaçamento:** 0,50 m entre vasos na linha e 0,80 m entre linhas, em local com mínimo de **5 a 6 horas de sol direto** pela manhã.

#### Grupos Experimentais
* **Tratamento 1 ($T_1$ — Testemunha / Vasos `V01` a `V10`):**
  * **Função:** Epidemia natural sem intervenção (0% a >70% de severidade) para gerar dados completos de progressão de lesão para a visão computacional e validar o modelo climático puro.
  * **Manejo:** Zero aplicação de fungicidas ou biofungicidas.
* **Tratamento 2 ($T_2$ — Manejo Guiado pelo DSS / Vasos `V11` a `V20`):**
  * **Função:** Validação agronômica do sistema (redução da Área Abaixo da Curva de Progresso da Doença — $AACPD$).
  * **Manejo:** Aplicação de Calda Bordalesa (0,5%) ou *Bacillus* exclusivamente quando o algoritmo disparar o **Limiar de Ação** ($\text{Severidade} \ge 2\%$ **OU** $\text{DSV acumulado} \ge 15$).

### Regra Crítica de Irrigação
* **NUNCA molhe as folhas durante a rega.** Aplique água diretamente na base do substrato (aprox. 500 mL a 1 L/dia conforme temperatura).
* **Por quê:** Isso garante que o molhamento foliar real das plantas seja governado exclusivamente pela chuva e pelo orvalho atmosférico registrados pela estação da EPAGRI/CIRAM.
* **Gatilho de Contingência:** Se até o final da Semana 3 houver estiagem prolongada e nenhuma lesão surgir naturalmente, realize uma **nebulização foliar com água limpa às 18h30** em todos os 20 vasos por 2 dias seguidos para simular orvalho noturno e induzir a germinação de esporos presentes no ambiente.

---

## 3. Protocolo Padronizado de Captura de Vídeo e Imagem

1. **Marcação Longitudinal:** Na Semana 2, selecione **3 folhas/folíolos do terço inferior a médio** de cada planta e marque o pecíolo com fita identificadora (`V01-F1`, `V01-F2`, `V01-F3`, totalizando **60 folhas monitoradas** continuamente ao longo do ciclo).
2. **Fundo e Escala:** Posicione a prancheta revestida com EVA **azul-royal ou cinza neutro fosco** imediatamente atrás da folha marcada, mantendo um quadrado de referência de **2 cm $\times$ 2 cm** visível no canto superior da placa.
3. **Janela de Iluminação:** Grave sempre entre **07h30 e 09h00** ou **16h30 e 18h00** (luz difusa, sem sol a pino para evitar reflexo especular branco sobre a folha).
4. **Parâmetros do Celular:**
   * Resolução: **1080p a 30 fps**.
   * Exposição e foco travados (**AE/AF Lock**) sobre a placa de fundo.
   * Distância padrão: **25 a 30 cm** da folha.
   * Duração: **4 a 5 segundos** por folha marcada (movimento suave de $\pm 15^\circ$ para capturar variação angular) + **1 foto panorâmica** do dossel de cada vaso a $45^\circ$.

---

## 4. Cronograma de Execução (8 Semanas)

| Semana | Fase da Cultura | Atividades de Campo & Coleta | Entregas de Software & Dados |
| :--- | :--- | :--- | :--- |
| **Sem 1** | Transplante e pegamento | Preparo do substrato, plantio dos 20 vasos, tutoramento e etiquetagem (`V01`–`V20`). | Criação do banco no Supabase + script Python de ingestão horária da estação EPAGRI (Itacorubi/A806) e previsão diária (06h00). |
| **Sem 2** | Crescimento vegetativo | Marcação das 60 folhas (`F1`–`F3`). Primeira coleta de vídeo (**Baseline $t_0$ — 0% de severidade**). | Pipeline de extração de keyframes e segmentação de 1º estágio (máscara da folha inteira sobre fundo azul/cinza). |
| **Sem 3–4** | Início de floração | Avaliações a cada **3 dias** (Seg/Qui). Adubação de cobertura (Sem 3). Início esperado das primeiras lesões (*Alternaria solani* ou *Phytophthora infestans*). | Anotação assistida com SAM 2 das primeiras lesões + treino/ajuste do segmentador de lesões e cálculo de Severidade (%). |
| **Sem 5–6** | Frutificação inicial (Pico epidêmico) | Avaliações a cada **2 dias** (Seg/Qua/Sex). Adubação de cobertura (Sem 5). Execução das pulverizações no grupo $T_2$ conforme alertas do sistema. | Acoplamento dinâmico: ajuste da curva Logística/Gompertz combinando severidade visual atual + DSV previsto para os próximos 7 dias. |
| **Sem 7** | Enchimento de frutos | Continuação das filmagens a cada 2–3 dias. Registro de desfolha precoce no grupo $T_1$. | Análise estatística no R (`AACPD`, ANOVA/teste de médias $T_1$ vs. $T_2$, $R^2$ e RMSE entre severidade visual e CV). |
| **Sem 8** | Encerramento do ensaio | Avaliação final, colheita e pesagem dos frutos por vaso ($T_1$ vs. $T_2$) e descarte sanitário dos restos culturais. | Consolidação do repositório público, dashboard final e redação do preprint/relatório técnico. |

---

## 5. Estrutura da Planilha de Registro (`campo_log.csv`)

Cada linha registra a avaliação de uma folha marcada em uma data específica, pronta para junção (*join*) com a tabela meteorológica da EPAGRI:

| Coluna | Tipo | Descrição / Exemplo |
| :--- | :--- | :--- |
| `timestamp` | `DATETIME` | `2026-12-03T08:15:00-03:00` |
| `vaso_id` | `VARCHAR` | `V01` a `V20` |
| `tratamento` | `ENUM` | `T1_TESTEMUNHA` ou `T2_MANEJO_DSS` |
| `folha_id` | `VARCHAR` | `F1`, `F2`, `F3` |
| `estadio_bbch` | `INT` | Código fenológico BBCH (ex: `61` = primeira inflorescência aberta) |
| `sev_visual_ref` | `FLOAT` | Severidade estimada por escala diagramática (`0.0` a `100.0%`) — *Ground Truth* |
| `sev_modelo_cv` | `FLOAT` | Severidade calculada pelo pipeline de visão computacional (`%`) |
| `doenca_predom` | `VARCHAR` | `Alternaria_solani`, `Phytophthora_infestans`, `Sadia` |
| `intervencao_aplicada` | `BOOLEAN` | `TRUE` se houve aplicação de manejo neste vaso nas últimas 24h |
| `video_path` | `VARCHAR` | `raw_videos/2026-12-03/V01_F1.mp4` |
| `epagri_tmed_24h` | `FLOAT` | Temperatura média nas últimas 24h na estação EPAGRI ($^\circ\text{C}$) |
| `epagri_ur_horas_85` | `INT` | Horas com Umidade Relativa $\ge 85\%$ nas últimas 24h (proxy de molhamento foliar) |
| `epagri_chuva_24h` | `FLOAT` | Precipitação acumulada nas últimas 24h ($\text{mm}$) |
| `dsv_acumulado` | `INT` | *Disease Severity Value* acumulado (modelo TOM-CAST) |