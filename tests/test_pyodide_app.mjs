/**
 * tests/test_pyodide_app.mjs
 * ==========================
 * Teste de integracao real da pagina `docs/app/` no Node usando o pacote npm
 * `pyodide`: carrega `tzdata`, monta `docs/app/vitirule_bundle.json`, extrai
 * `PYTHON_DRIVER` e `buildSampleStationCsv` exatamente de `docs/app/app.js` e
 * executa `run_station_csv_json` nos quatro fusos do menu (`America/Sao_Paulo`,
 * `Europe/Paris`, `Europe/Rome` e `UTC`).
 */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath, pathToFileURL } from "node:url";

const pyodideSpecifier = process.env.PYODIDE_MJS
  ? pathToFileURL(process.env.PYODIDE_MJS).href
  : "pyodide";
const { loadPyodide } = await import(pyodideSpecifier);

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");

const appJs = fs.readFileSync(path.join(ROOT, "docs", "app", "app.js"), "utf8");
const bundle = JSON.parse(
  fs.readFileSync(path.join(ROOT, "docs", "app", "vitirule_bundle.json"), "utf8")
);

// Confere que app.js carrega explicitamente tzdata antes de rodar o driver
assert.ok(
  appJs.includes('loadPackage("tzdata")') || appJs.includes("loadPackage('tzdata')"),
  "docs/app/app.js deve chamar pyodide.loadPackage('tzdata') em initPyodide"
);

// Extrai e avalia PYTHON_DRIVER e buildSampleStationCsv exatamente como o navegador faz em app.js
const driverMatch = appJs.match(/const PYTHON_DRIVER = `[\s\S]*?`;/);
assert.ok(driverMatch, "Nao foi possivel localizar PYTHON_DRIVER em docs/app/app.js");

const sampleFnMatch = appJs.match(/function buildSampleStationCsv\(\) \{[\s\S]*?\n\}/);
assert.ok(sampleFnMatch, "Nao foi possivel localizar buildSampleStationCsv em docs/app/app.js");
const sandbox = {};
vm.runInNewContext(
  `${driverMatch[0]}; ${sampleFnMatch[0]}; this.PYTHON_DRIVER = PYTHON_DRIVER; this.buildSampleStationCsv = buildSampleStationCsv;`,
  sandbox
);
const pythonDriver = sandbox.PYTHON_DRIVER;
const sampleSouthCsv = sandbox.buildSampleStationCsv();
// Gera tambem uma variante em maio-junho para testar janelas do Hemisferio Norte
const sampleNorthCsv = sampleSouthCsv.replace(/2024-11-/g, "2024-05-").replace(/2024-12-/g, "2024-06-");

const pyodide = await loadPyodide();
await pyodide.loadPackage("tzdata");

pyodide.FS.mkdirTree("/vitirule_pkg/vitirule_v2/rules");
for (const [relPath, content] of Object.entries(bundle)) {
  pyodide.FS.writeFile(`/vitirule_pkg/${relPath}`, content, { encoding: "utf8" });
}

await pyodide.runPythonAsync(`
import sys
if "/vitirule_pkg" not in sys.path:
    sys.path.insert(0, "/vitirule_pkg")
${pythonDriver}
`);

const cases = [
  { tz: "America/Sao_Paulo", hemi: "southern_hemisphere", csv: sampleSouthCsv },
  { tz: "Europe/Paris", hemi: "northern_hemisphere", csv: sampleNorthCsv },
  { tz: "Europe/Rome", hemi: "northern_hemisphere", csv: sampleNorthCsv },
  { tz: "UTC", hemi: "southern_hemisphere", csv: sampleSouthCsv },
];

for (const c of cases) {
  pyodide.globals.set("JS_CSV", c.csv);
  pyodide.globals.set("JS_HEMI", c.hemi);
  pyodide.globals.set("JS_TZ", c.tz);
  pyodide.globals.set("JS_SENSOR", false);
  const outRaw = await pyodide.runPythonAsync("run_station_csv_json(JS_CSV, JS_HEMI, JS_TZ, JS_SENSOR)");
  const res = JSON.parse(outRaw);

  assert.equal(res.n_hours, 45 * 24, `Esperado 1080 horas em ${c.tz}`);
  assert.ok(Array.isArray(res.rule_3_10), `rule_3_10 deve ser array em ${c.tz}`);
  assert.ok(Array.isArray(res.goidanich), `goidanich deve ser array em ${c.tz}`);
  assert.ok(Array.isArray(res.mills_revised), `mills_revised deve ser array em ${c.tz}`);
  assert.ok(Array.isArray(res.tomcast_self), `tomcast_self deve ser array em ${c.tz}`);

  const totalAlerts =
    res.rule_3_10.length +
    res.goidanich.length +
    res.mills_revised.length +
    res.tomcast_self.length;
  assert.ok(totalAlerts > 0, `Esperado ao menos um alerta no CSV de exemplo em ${c.tz}`);
  console.log(
    `[OK] ${c.tz} (${c.hemi}): 3-10=${res.rule_3_10.length}, goidanich=${res.goidanich.length}, mills=${res.mills_revised.length}, tomcast=${res.tomcast_self.length}`
  );
}

console.log("Todos os 4 fusos do menu passaram no Pyodide com tzdata.");
