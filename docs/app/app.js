/* vitirule v2 browser runner using Pyodide + frozen vitirule_v2/rules/ bundle */
let pyodide = null;
let loadedCsvText = null;
let lastStationSummary = null;
let lastExportCsv = null;

const statusEl = document.getElementById("pyodide-status");
const runBtn = document.getElementById("run-btn");
const sampleBtn = document.getElementById("sample-btn");
const downloadBtn = document.getElementById("download-btn");
const divBtn = document.getElementById("div-btn");
const csvFileInput = document.getElementById("csv-file");
const csvSummaryEl = document.getElementById("csv-summary");
const stationResultsEl = document.getElementById("station-results");
const divResultsEl = document.getElementById("div-results");

// Tabs
document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(`tab-${btn.dataset.tab}`).classList.add("active");
  });
});

const PYTHON_DRIVER = `
import csv, io, json, math, re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from vitirule_v2.lwd import apply_lwd_estimator
from vitirule_v2.rules import (
    HourlyRecord,
    compute_tomcast_daily,
    detect_mills_infections,
    detect_rule_3_10,
    simulate_tomcast_sprays,
    track_goidanich_incubation,
)

UTC = timezone.utc

def _num(raw):
    if raw is None:
        return None
    s = str(raw).strip().replace(",", ".")
    if not s:
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    if not math.isfinite(v) or v <= -999.0:
        return None
    return v

def _parse_bool_wet(raw):
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if s in ("", "na", "nan", "null", "none"):
        return None
    if s in ("true", "t", "yes", "sim"):
        return True
    if s in ("false", "f", "no", "nao"):
        return False
    v = _num(s)
    if v is None:
        return None
    return v >= 0.5

def parse_station_csv(csv_text, tz_name):
    lines = [ln for ln in csv_text.splitlines() if ln.strip()]
    if not lines:
        raise ValueError("CSV vazio.")
    # Detecta formato oficial do INMET (8 linhas de cabecalho iniciando em REGIAO:)
    if lines[0].upper().startswith("REGIAO"):
        data_lines = lines[8:]
        delim = ";"
    else:
        data_lines = lines
        delim = ";" if lines[0].count(";") > lines[0].count(",") else ","

    reader = csv.reader(io.StringIO("\\n".join(data_lines)), delimiter=delim)
    headers = next(reader, None)
    if not headers:
        raise ValueError("Cabecalho CSV ausente.")

    norm_h = [re.sub(r"\\s+", " ", h.strip().lower()) for h in headers]

    def _find(*needles):
        for i, h in enumerate(norm_h):
            if all(n in h for n in needles):
                return i
        return None

    i_ts = _find("timestamp")
    if i_ts is None:
        i_ts = _find("datetime")
    i_date = _find("data") if i_ts is None else None
    i_hour = _find("hora") if i_ts is None else None
    i_t = _find("temp_c")
    if i_t is None:
        i_t = _find("bulbo seco")
    if i_t is None:
        i_t = _find("temp")
    i_rh = _find("rh_pct")
    if i_rh is None:
        i_rh = _find("umidade relativa", "horaria")
    if i_rh is None:
        i_rh = _find("rh")
    if i_rh is None:
        i_rh = _find("umidade")
    i_p = _find("precip_mm")
    if i_p is None:
        i_p = _find("precipitacao")
    if i_p is None:
        i_p = _find("rain")
    if i_p is None:
        i_p = _find("chuva")
    i_w = _find("wet")
    if i_w is None:
        i_w = _find("lwd")

    if i_t is None or i_rh is None or i_p is None:
        raise ValueError("Nao foi possivel localizar colunas de temperatura, umidade e chuva.")

    tz_local = ZoneInfo(tz_name)
    recs = []
    for row in reader:
        if not row:
            continue
        ts = None
        if i_ts is not None and i_ts < len(row):
            raw_ts = row[i_ts].strip()
            if not raw_ts:
                continue
            dt = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
            ts = dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=tz_local).astimezone(UTC)
        elif i_date is not None and i_hour is not None and max(i_date, i_hour) < len(row):
            raw_d = row[i_date].strip().replace("-", "/")
            raw_h = row[i_hour].strip()
            m_h = re.match(r"^(\\d{2}):?(\\d{2})", raw_h)
            if not raw_d or not m_h:
                continue
            hh, mm = int(m_h.group(1)), int(m_h.group(2))
            dt = datetime.strptime(raw_d, "%Y/%m/%d").replace(hour=hh, minute=mm)
            ts = dt.replace(tzinfo=UTC) if "UTC" in raw_h.upper() else dt.replace(tzinfo=tz_local).astimezone(UTC)
        else:
            continue

        t_val = _num(row[i_t]) if i_t < len(row) else None
        rh_val = _num(row[i_rh]) if i_rh < len(row) else None
        p_val = _num(row[i_p]) if i_p < len(row) else None
        w_val = _parse_bool_wet(row[i_w]) if (i_w is not None and i_w < len(row)) else None
        recs.append(HourlyRecord(ts=ts, temp_c=t_val, rh_pct=rh_val, precip_mm=p_val, wet=w_val))

    recs.sort(key=lambda r: r.ts)
    return recs

def evaluate_records_dict(recs, hemisphere, tz_name, use_sensor_lwd):
    if not recs:
        raise ValueError("Nenhum registro horario valido encontrado.")
    if not use_sensor_lwd:
        proc = apply_lwd_estimator(recs, method="rh90_rain", wind_height_m=10.0)
    else:
        if not any(r.wet is not None for r in recs):
            raise ValueError("Modo sensor selecionado, mas a coluna wet esta ausente ou vazia.")
        proc = recs

    r310 = detect_rule_3_10(proc, tz_name=tz_name, hemisphere=hemisphere, temp_aggregation="daily_min")
    goid = track_goidanich_incubation(proc, [e.trigger_date for e in r310], tz_name=tz_name, hemisphere=hemisphere)
    goid_done = [c for c in goid if c.completed and c.completion_date is not None]
    mills = detect_mills_infections(proc, tz_name=tz_name, hemisphere=hemisphere)
    tc_days = compute_tomcast_daily(proc, tz_name=tz_name, hemisphere=hemisphere)
    tc_sprays = simulate_tomcast_sprays(tc_days, mode="self_reset")

    return {
        "n_hours": len(proc),
        "start_utc": proc[0].ts.isoformat(),
        "end_utc": proc[-1].ts.isoformat(),
        "start_date": proc[0].ts.strftime("%Y-%m-%d"),
        "end_date": proc[-1].ts.strftime("%Y-%m-%d"),
        "rule_3_10": [
            {"date": e.trigger_date.isoformat(), "rain_48h_mm": e.rain_48h_mm, "temp_min_c": e.temp_min_c}
            for e in r310
        ],
        "goidanich": [
            {"trigger_date": c.trigger_date.isoformat(), "completion_date": c.completion_date.isoformat(), "duration_days": c.duration_days}
            for c in goid_done
        ],
        "mills_revised": [
            {"light_ts": e.light_ts.isoformat(), "severity": e.max_severity, "wet_hours": e.wet_hours, "mean_temp_c": e.mean_temp_c}
            for e in mills
        ],
        "tomcast_self": [
            {"date": s.trigger_date.isoformat(), "cum_dsv": s.cum_dsv, "spray_index": s.spray_index}
            for s in tc_sprays
        ],
    }

def run_station_csv_json(csv_text, hemisphere, tz_name, use_sensor_lwd):
    recs = parse_station_csv(csv_text, tz_name)
    res = evaluate_records_dict(recs, hemisphere, tz_name, use_sensor_lwd)
    return json.dumps(res)

def run_open_meteo_divergence_json(csv_text, om_json_text, hemisphere, tz_name, use_sensor_lwd):
    st_recs = parse_station_csv(csv_text, tz_name)
    st_res = evaluate_records_dict(st_recs, hemisphere, tz_name, use_sensor_lwd)
    payload = json.loads(om_json_text)
    h = payload.get("hourly") or {}
    times = h.get("time") or []
    t_c = h.get("temperature_2m") or []
    rh = h.get("relative_humidity_2m") or []
    pr = h.get("precipitation") or []
    om_recs = []
    for i, raw_t in enumerate(times):
        ts = datetime.fromisoformat(str(raw_t)).replace(tzinfo=UTC)
        om_recs.append(HourlyRecord(
            ts=ts,
            temp_c=_num(t_c[i]) if i < len(t_c) else None,
            rh_pct=_num(rh[i]) if i < len(rh) else None,
            precip_mm=_num(pr[i]) if i < len(pr) else None,
            wet=None,
        ))
    om_res = evaluate_records_dict(om_recs, hemisphere, tz_name, False)
    return json.dumps({"station": st_res, "era5_combined": om_res})
`;

async function initPyodide() {
  try {
    pyodide = await loadPyodide();
    statusEl.innerHTML = "Carregando base de fusos horários (<code>tzdata</code>) e pacote congelado <code>vitirule_v2/rules/</code>…";
    await pyodide.loadPackage("tzdata");
    const resp = await fetch("vitirule_bundle.json");
    if (!resp.ok) throw new Error("Falha ao carregar vitirule_bundle.json");
    const files = await resp.json();

    pyodide.FS.mkdirTree("/vitirule_pkg/vitirule_v2/rules");
    for (const [relPath, content] of Object.entries(files)) {
      const fullPath = `/vitirule_pkg/${relPath}`;
      pyodide.FS.writeFile(fullPath, content, { encoding: "utf8" });
    }
    await pyodide.runPythonAsync(`
import sys
if "/vitirule_pkg" not in sys.path:
    sys.path.insert(0, "/vitirule_pkg")
${PYTHON_DRIVER}
`);
    statusEl.innerHTML =
      "<strong>Pronto:</strong> Pyodide carregado com <code>tzdata</code> e o pacote puro congelado <code>vitirule_v2/rules/</code> (execução 100% local no navegador).";
    runBtn.disabled = false;
    sampleBtn.disabled = false;
  } catch (err) {
    statusEl.innerHTML = `<strong style="color:#991b1b;">Erro ao inicializar Pyodide:</strong> ${err.message}`;
  }
}

function buildSampleStationCsv() {
  const rows = ["timestamp,temp_c,rh_pct,precip_mm"];
  const start = new Date("2024-11-01T00:00:00Z");
  for (let h = 0; h < 45 * 24; h++) {
    const dt = new Date(start.getTime() + h * 3600 * 1000);
    const dayIdx = Math.floor(h / 24);
    const hr = dt.getUTCHours();
    const isRainDay = dayIdx % 6 === 2 || dayIdx % 11 === 4;
    const isNight = hr < 10 || hr >= 22;
    const temp = (17.5 + 5.5 * Math.sin(((hr - 11) / 24) * 2 * Math.PI) + (dayIdx % 4) * 0.4).toFixed(1);
    const rh = isRainDay && isNight ? "95.0" : (isNight ? "89.0" : "64.0");
    const precip = isRainDay && hr >= 18 && hr <= 21 ? "3.8" : "0.0";
    rows.push(`${dt.toISOString()},${temp},${rh},${precip}`);
  }
  return rows.join("\n");
}

function renderStationResults(res) {
  lastStationSummary = res;
  const exportRows = ["rule,date_or_timestamp,detail"];
  res.rule_3_10.forEach((e) => exportRows.push(`rule_3_10,${e.date},rain48h=${e.rain_48h_mm}mm;tmin=${e.temp_min_c}C`));
  res.goidanich.forEach((c) => exportRows.push(`goidanich,${c.completion_date},trigger=${c.trigger_date};days=${c.duration_days}`));
  res.mills_revised.forEach((e) => exportRows.push(`mills_revised,${e.light_ts},severity=${e.severity};wet_h=${e.wet_hours};t=${e.mean_temp_c}C`));
  res.tomcast_self.forEach((s) => exportRows.push(`tomcast_self,${s.date},cum_dsv=${s.cum_dsv}`));
  lastExportCsv = exportRows.join("\n");
  downloadBtn.disabled = false;
  divBtn.disabled = false;

  const listItems = (arr, fmt) =>
    arr.length === 0
      ? "<span class='small-note'>Nenhum evento detectado na janela fenológica.</span>"
      : arr.slice(0, 12).map(fmt).join("<br>") + (arr.length > 12 ? `<br><span class='small-note'>… e mais ${arr.length - 12} eventos (use Exportar CSV).</span>` : "");

  stationResultsEl.innerHTML = `
    <p class="small-note" style="margin-top:0;">
      Série processada: <strong>${res.n_hours} horas</strong> (${res.start_date} a ${res.end_date}).
    </p>
    <table>
      <thead>
        <tr><th>Regra congelada</th><th>Total</th><th>Eventos detectados (estação própria)</th></tr>
      </thead>
      <tbody>
        <tr>
          <td><strong>Regra 3-10</strong></td>
          <td>${res.rule_3_10.length}</td>
          <td>${listItems(res.rule_3_10, (e) => `${e.date} (${e.rain_48h_mm.toFixed(1)} mm/48h, Tmin ${e.temp_min_c.toFixed(1)} °C)`)}</td>
        </tr>
        <tr>
          <td><strong>Goidànich</strong></td>
          <td>${res.goidanich.length}</td>
          <td>${listItems(res.goidanich, (c) => `${c.completion_date} (gatilho ${c.trigger_date}, ${c.duration_days} d)`)}</td>
        </tr>
        <tr>
          <td><strong>Mills revisada</strong></td>
          <td>${res.mills_revised.length}</td>
          <td>${listItems(res.mills_revised, (e) => `${e.light_ts.slice(0, 16).replace("T", " ")} UTC — ${e.severity} (${e.wet_hours} h, ${e.mean_temp_c.toFixed(1)} °C)`)}</td>
        </tr>
        <tr>
          <td><strong>TOM-CAST (self_reset)</strong></td>
          <td>${res.tomcast_self.length}</td>
          <td>${listItems(res.tomcast_self, (s) => `Pulverização #${s.spray_index}: ${s.date} (${s.cum_dsv} DSV)`)}</td>
        </tr>
      </tbody>
    </table>
  `;
}

csvFileInput.addEventListener("change", async (ev) => {
  const f = ev.target.files[0];
  if (!f) return;
  loadedCsvText = await f.text();
  csvSummaryEl.textContent = `Arquivo carregado localmente: ${f.name} (${Math.round(f.size / 1024)} KB).`;
});

sampleBtn.addEventListener("click", () => {
  loadedCsvText = buildSampleStationCsv();
  csvSummaryEl.textContent = "CSV sintético de exemplo carregado (45 dias em novembro–dezembro, Hemisfério Sul).";
  runBtn.click();
});

runBtn.addEventListener("click", async () => {
  if (!pyodide) return;
  if (!loadedCsvText) {
    stationResultsEl.innerHTML = "<p class='small-note' style='color:#991b1b;'>Selecione um arquivo CSV ou clique em Carregar CSV de exemplo.</p>";
    return;
  }
  const hemisphere = document.getElementById("hemisphere").value;
  const tzName = document.getElementById("tz-name").value;
  const useSensor = document.getElementById("lwd-mode").value === "sensor";
  try {
    pyodide.globals.set("JS_CSV", loadedCsvText);
    pyodide.globals.set("JS_HEMI", hemisphere);
    pyodide.globals.set("JS_TZ", tzName);
    pyodide.globals.set("JS_SENSOR", useSensor);
    const outJson = await pyodide.runPythonAsync("run_station_csv_json(JS_CSV, JS_HEMI, JS_TZ, JS_SENSOR)");
    renderStationResults(JSON.parse(outJson));
  } catch (err) {
    stationResultsEl.innerHTML = `<p class="small-note" style="color:#991b1b;"><strong>Erro:</strong> ${err.message}</p>`;
  }
});

downloadBtn.addEventListener("click", () => {
  if (!lastExportCsv) return;
  const blob = new Blob([lastExportCsv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "vitirule_v2_station_alerts.csv";
  a.click();
  URL.revokeObjectURL(url);
});

divBtn.addEventListener("click", async () => {
  if (!pyodide || !loadedCsvText || !lastStationSummary) return;
  const lat = parseFloat(document.getElementById("div-lat").value);
  const lon = parseFloat(document.getElementById("div-lon").value);
  const hemisphere = document.getElementById("hemisphere").value;
  const tzName = document.getElementById("tz-name").value;
  const useSensor = document.getElementById("lwd-mode").value === "sensor";

  divResultsEl.innerHTML = "<p class='small-note'>Consultando Open-Meteo Archive (<code>era5_seamless</code>) para demonstração de divergência…</p>";
  try {
    const url =
      `https://archive-api.open-meteo.com/v1/archive?latitude=${lat}&longitude=${lon}` +
      `&start_date=${lastStationSummary.start_date}&end_date=${lastStationSummary.end_date}` +
      `&hourly=temperature_2m,relative_humidity_2m,precipitation&models=era5_seamless&timezone=GMT`;
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`Open-Meteo HTTP ${resp.status}`);
    const omText = await resp.text();

    pyodide.globals.set("JS_CSV", loadedCsvText);
    pyodide.globals.set("JS_OM", omText);
    pyodide.globals.set("JS_HEMI", hemisphere);
    pyodide.globals.set("JS_TZ", tzName);
    pyodide.globals.set("JS_SENSOR", useSensor);
    const out = JSON.parse(
      await pyodide.runPythonAsync("run_open_meteo_divergence_json(JS_CSV, JS_OM, JS_HEMI, JS_TZ, JS_SENSOR)")
    );
    const st = out.station;
    const gr = out.era5_combined;
    divResultsEl.innerHTML = `
      <p class="small-note" style="color:#991b1b;margin-top:0;">
        <strong>Apenas demonstração de divergência:</strong> as contagens da coluna direita não são recomendações de pulverização.
      </p>
      <table>
        <thead>
          <tr><th>Regra</th><th>Sua estação (CSV)</th><th>ERA5 combinado (grade)</th><th>Diferença de contagem</th></tr>
        </thead>
        <tbody>
          <tr><td>Regra 3-10</td><td>${st.rule_3_10.length}</td><td>${gr.rule_3_10.length}</td><td>${gr.rule_3_10.length - st.rule_3_10.length}</td></tr>
          <tr><td>Goidànich</td><td>${st.goidanich.length}</td><td>${gr.goidanich.length}</td><td>${gr.goidanich.length - st.goidanich.length}</td></tr>
          <tr><td>Mills revisada</td><td>${st.mills_revised.length}</td><td>${gr.mills_revised.length}</td><td>${gr.mills_revised.length - st.mills_revised.length}</td></tr>
          <tr><td>TOM-CAST (self_reset)</td><td>${st.tomcast_self.length}</td><td>${gr.tomcast_self.length}</td><td>${gr.tomcast_self.length - st.tomcast_self.length}</td></tr>
        </tbody>
      </table>
    `;
  } catch (err) {
    divResultsEl.innerHTML = `<p class="small-note" style="color:#991b1b;"><strong>Falha na demonstração de divergência:</strong> ${err.message}</p>`;
  }
});

initPyodide();
