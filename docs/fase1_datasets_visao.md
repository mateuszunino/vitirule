# Fase 1 — Visão Computacional sem Experimento: Datasets, Licenças e Fluxo de Treino

Este guia consolida o levantamento de conjuntos públicos (seção 6, Fase 1 do `BRIEFING.md`) e o fluxo para treinar `models/stage_a_leaf.pt` e `models/stage_b_lesion.pt` sem depender ainda do ensaio em vasos.

## 1. Catálogo de Datasets Públicos e Licenças

| Dataset | Plataforma | O que traz para tomateiro | Tipo de anotação | Licença | Restrições e uso recomendado |
|---|---|---|---|---|---|
| **PlantSeg** (`tqwei05/PlantSeg`) | GitHub / Zenodo / Roboflow mirror | `tomato early blight` e `tomato late blight` em campo (*in-the-wild*) | **Máscaras de segmentação semântica** de lesão | **CC BY-NC-ND 4.0** | Uso **não comercial**; não redistribuir versões derivadas/modificadas. Excelente para pré-treino/validação acadêmica do **Estágio B** (lesões). |
| **Tomato Leaf Object Detection / Segmentation** | Roboflow Universe (`segmentationmodel`) | Folhas e lesões de tomateiro | **Segmentação de instância** (Mask R-CNN / polígonos) | **MIT** | Muito permissiva (uso acadêmico ou comercial com crédito). Boa base para **Estágio A** (`leaf`) e **Estágio B**. |
| **PlantVillage** (subconjunto Tomate) | Kaggle / Mendeley | `Tomato___Early_blight`, `Tomato___Late_blight`, `Tomato___healthy` (~3.000+ fotos) | Apenas **classificação** (sem máscara), folha isolada sobre fundo liso | **CC0 (Domínio Público)** | Sem máscara nativa; ideal para **pré-anotação rápida** com `vision_prep.py` + SAM (fundo liso facilita separar o limbo foliar e treinar o **Estágio B**). |
| **PlantDoc** | GitHub / Kaggle | Folhas de tomateiro com pinta-preta e requeima em ambiente real | Bounding boxes / classificação | **CC BY 4.0** | Útil para extrair exemplos difíceis de iluminação real (requer anotação de máscara com SAM). |

> **Atenção ao gap de domínio:** Nenhum dataset público contém o **quadrado de referência de 2 × 2 cm** nem o **fundo EVA azul-royal** do protocolo (`SKILL.md` seção 8). Por isso, para o **Estágio A** (`0: leaf`, `1: ref_square`), é indispensável gravar pelo menos 20–40 vídeos curtos próprios de folhas de tomateiro (de hortas ou feiras, sadias e com lesões) apoiadas no EVA azul-royal com o quadrado de 2 × 2 cm.

## 2. Regras Obrigatórias de Classes e Recorte (`SKILL.md` seção 8)

* **Estágio A (`models/stage_a_leaf.pt`):**
  * `0: leaf` (limbo inteiro, incluindo necrose e clorose; fora: pecíolo, dedos, folhas vizinhas)
  * `1: ref_square` (quadrado 2 × 2 cm inteiro no mesmo plano)
  * Modelos permitidos: `yolo11n-seg` ou `yolo11s-seg` (nunca `m`, `l` ou `x`), `imgsz=640`.
* **Estágio B (`models/stage_b_lesion.pt`):**
  * `0: necrosis`
  * `1: chlorosis` (pixel com ambas as classes conta como `necrosis`)
  * Treinado **obrigatoriamente** em recortes da folha com fundo pintado de **cinza 114** (gerado por `vision_prep.build_stage_b_crop`, idêntico ao `vision_pipeline.py` na inferência).
  * Modelos permitidos: `yolo11n-seg` ou `yolo11s-seg`, `imgsz=1024`.
* **Divisão treino / validação:** sempre por **grupo** (vaso, planta, vídeo ou origem do dataset) via `vision_prep.py split`, nunca por frame. Nos vasos do ensaio, `V05`, `V10`, `V15` e `V20` ficam sempre na validação.

## 3. Fluxo Prático de Execução

1. **Pré-anotação rápida (reserva clássica + revisão manual/SAM):**
   ```powershell
   .venv\Scripts\python.exe vision_prep.py preannotate caminho/dos/videos_ou_fotos --out-dir data/pre_anotado
   ```
   Corrija as máscaras no CVAT / Label Studio / Roboflow (ou refine com SAM/PerSAM).
2. **Divisão sem vazamento por grupo e geração dos YAMLs:**
   ```powershell
   .venv\Scripts\python.exe vision_prep.py split --source-dir data/pre_anotado/stage_a --dest-dir data/datasets/stage_a --stage stage_a
   .venv\Scripts\python.exe vision_prep.py split --source-dir data/pre_anotado/stage_b --dest-dir data/datasets/stage_b --stage stage_b
   ```
3. **Treino no Google Colab:** abra [colab/train_yolo_seg.ipynb](../colab/train_yolo_seg.ipynb), envie os arquivos `stage_a` e `stage_b`, treine os pesos e baixe `stage_a_leaf.pt` e `stage_b_lesion.pt` para `models/`.
4. **Validação objetiva local (`BRIEFING.md` seção 7):**
   ```powershell
   .venv\Scripts\python.exe vision_eval.py data/validacao_visao.csv
   ```
   Critérios de aceite: **CCC de Lin >= 0,90** e **erro de área calibrada < 5 %**.
