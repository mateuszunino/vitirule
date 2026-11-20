#!/usr/bin/env Rscript
# ---------------------------------------------------------------------------
# r/aacpd_validacao.R
# Validação da AACPD (Python vs R até 1e-6) e análise estatística em DIC
# (SKILL.md seção 9 e BRIEFING.md seção 7 / Fase 3).
#
# Unidade experimental: o vaso (V01-V20). Nunca tratar folhas como repetições.
# Uso:
#   Rscript r/aacpd_validacao.R r/dados/aacpd_por_vaso.csv [r/dados/series_por_vaso.csv]
# ---------------------------------------------------------------------------

args <- commandArgs(trailingOnly = TRUE)
input_csv <- if (length(args) >= 1 && nzchar(args[1])) args[1] else "r/dados/aacpd_por_vaso.csv"
series_csv <- if (length(args) >= 2 && nzchar(args[2])) args[2] else ""

if (!file.exists(input_csv)) {
  stop(sprintf("Arquivo de entrada não encontrado: %s", input_csv))
}

required_cols <- c("pot_id", "treatment", "disease", "aacpd", "n_avaliacoes", "primeira_data", "ultima_data")
df <- read.csv(input_csv, stringsAsFactors = FALSE)
missing_cols <- setdiff(required_cols, names(df))
if (length(missing_cols) > 0) {
  stop(sprintf("Colunas obrigatórias ausentes em %s: %s", input_csv, paste(missing_cols, collapse = ", ")))
}

# Verificação anti-pseudorrepetição: 1 linha por vaso (por tratamento e doença)
dup_key <- paste(df$pot_id, df$treatment, df$disease, sep = "|")
if (any(duplicated(dup_key))) {
  stop("Detectadas múltiplas linhas para o mesmo vaso/tratamento/doença (risco de pseudorrepetição).")
}

# Função AUDPC (prioriza epifitter::AUDPC, depois agricolae::audpc, depois trapézio exato)
audpc_engine <- "trapezio_base"
calc_audpc <- function(days, severity_pct) {
  ord <- order(days)
  t <- as.numeric(days[ord])
  y <- as.numeric(severity_pct[ord])
  if (length(t) < 2) return(0.0)
  if (requireNamespace("epifitter", quietly = TRUE)) {
    audpc_engine <<- "epifitter::AUDPC"
    return(as.numeric(epifitter::AUDPC(time = t, y = y, y_proportion = FALSE, type = "absolute")))
  }
  if (requireNamespace("agricolae", quietly = TRUE)) {
    audpc_engine <<- "agricolae::audpc"
    return(as.numeric(agricolae::audpc(y, t, type = "absolute")))
  }
  sum(diff(t) * (y[-length(y)] + y[-1]) / 2.0)
}

cat("=== Validação da AACPD e Análise Estatística (DIC) ===\n")
cat(sprintf("Arquivo AACPD: %s (%d unidades experimentais)\n", input_csv, nrow(df)))

# 1. Conferência Python vs R até 1e-6 (quando a série diária por vaso é informada)
if (nzchar(series_csv)) {
  if (!file.exists(series_csv)) {
    stop(sprintf("Arquivo de séries não encontrado: %s", series_csv))
  }
  ser <- read.csv(series_csv, stringsAsFactors = FALSE)
  keys <- unique(ser[, c("pot_id", "treatment", "disease")])
  r_vals <- numeric(nrow(keys))
  for (i in seq_len(nrow(keys))) {
    sub <- ser[
      ser$pot_id == keys$pot_id[i] &
      ser$treatment == keys$treatment[i] &
      ser$disease == keys$disease[i],
    ]
    r_vals[i] <- calc_audpc(sub$day, sub$severity_pct)
  }
  keys$aacpd_r <- r_vals
  merged <- merge(df, keys, by = c("pot_id", "treatment", "disease"))
  merged$abs_diff <- abs(merged$aacpd - merged$aacpd_r)
  max_diff <- max(merged$abs_diff)
  cat(sprintf("Motor AUDPC usado no R: %s\n", audpc_engine))
  cat(sprintf("Diferença máxima |Python - R|: %.3e (limite SKILL.md: 1e-6)\n", max_diff))
  if (max_diff > 1e-6) {
    stop(sprintf("FALHA na validação cruzada Python vs R: max_diff = %.3e > 1e-6", max_diff))
  }
  cat("OK: AACPD Python e R coincidem até a 6ª casa decimal.\n\n")
}

# 2. Estatísticas descritivas por tratamento (com `metan` se disponível)
df$treatment <- as.factor(df$treatment)
cat("--- Estatísticas descritivas por tratamento ---\n")
if (requireNamespace("metan", quietly = TRUE)) {
  desc <- suppressWarnings(metan::desc_stat(df, aacpd, by = treatment, stats = "main"))
  print(as.data.frame(desc))
} else {
  desc <- do.call(rbind, lapply(split(df$aacpd, df$treatment), function(x) {
    data.frame(n = length(x), mean = mean(x), sd = sd(x), median = median(x), min = min(x), max = max(x))
  }))
  print(desc)
}
cat("\n")

# 3. Análise de variância (DIC) e pressupostos
n_groups <- nlevels(df$treatment)
if (n_groups >= 2 && all(table(df$treatment) >= 2)) {
  fit_aov <- aov(aacpd ~ treatment, data = df)
  cat("--- ANOVA (Delineamento Inteiramente Casualizado) ---\n")
  print(summary(fit_aov))

  res <- residuals(fit_aov)
  if (length(res) >= 3 && length(res) <= 5000 && sd(res) > 0) {
    shapiro <- shapiro.test(res)
    cat(sprintf("\nNormalidade dos resíduos (Shapiro-Wilk): W = %.4f, p = %.4g\n",
                shapiro$statistic, shapiro$p.value))
  }
  if (all(tapply(df$aacpd, df$treatment, sd) > 0)) {
    bart <- bartlett.test(aacpd ~ treatment, data = df)
    cat(sprintf("Homogeneidade de variâncias (Bartlett): K2 = %.4f, p = %.4g\n",
                bart$statistic, bart$p.value))
  }

  if (n_groups == 2) {
    tt <- t.test(aacpd ~ treatment, data = df)
    wt <- wilcox.test(aacpd ~ treatment, data = df)
    cat(sprintf("\nTeste t de Welch: t = %.4f, df = %.2f, p = %.4g\n",
                tt$statistic, tt$parameter, tt$p.value))
    cat(sprintf("Teste de Wilcoxon (Mann-Whitney): W = %.2f, p = %.4g\n",
                wt$statistic, wt$p.value))
  } else {
    cat("\n--- Comparações múltiplas (Tukey HSD) ---\n")
    print(TukeyHSD(fit_aov))
    kw <- kruskal.test(aacpd ~ treatment, data = df)
    cat(sprintf("Kruskal-Wallis: chi2 = %.4f, p = %.4g\n", kw$statistic, kw$p.value))
  }
}

out_summary <- file.path(dirname(input_csv), "resumo_aacpd_r.csv")
summary_tbl <- aggregate(aacpd ~ treatment + disease, data = df, FUN = function(x) {
  c(n = length(x), mean = mean(x), sd = sd(x), median = median(x))
})
summary_df <- cbind(summary_tbl[, c("treatment", "disease")], as.data.frame(summary_tbl$aacpd))
write.csv(summary_df, out_summary, row.names = FALSE)
cat(sprintf("\nResumo salvo em: %s\n", out_summary))
