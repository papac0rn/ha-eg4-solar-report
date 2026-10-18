/*
 * EG4 Solar Report card, shipped and loaded by the integration (no HACS frontend install needed).
 * Renders the report sensor's attributes as one console-style page: header, verdict, readouts, panels,
 * day-by-day table, findings ledger, charts and the "What to do" list.
 *
 *   type: custom:eg4-solar-report-card
 *   entity: sensor.my_station_report
 *
 * The other entities (period, end date, Generate button, chart images) are found from the report
 * sensor's device, so only the report entity is needed.
 */
const CSS = `
:host{
  --bg:#0d1020; --panel:#141931; --panel2:#1a2040; --rule:#2a3157;
  --fg:#e4e7f6; --dim:#98a0c8; --faint:#6f78a6;
  --south:#f2b950; --east:#4fd0c4; --west:#c592f5;
  --ok:#62d594; --watch:#f2b950; --act:#ff7d6e; --info:#7fb0ff;
  --mono:ui-monospace,"SF Mono","Cascadia Mono","JetBrains Mono",Menlo,Consolas,"Liberation Mono",monospace;
  display:block;
}
*{box-sizing:border-box}
.page{background:var(--bg);color:var(--fg);font-family:var(--mono);font-size:13.5px;line-height:1.55;
  padding:18px 16px 36px;font-variant-numeric:tabular-nums;border-radius:var(--ha-card-border-radius,12px)}
.wrap{max-width:1040px;margin-inline:auto;display:flex;flex-direction:column;gap:22px}
header{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:flex-end;gap:6px 24px;border-bottom:1px solid var(--rule);padding-bottom:10px}
header .ttl{font-size:clamp(18px,2.6vw,24px);font-weight:600;letter-spacing:.02em}
header .id{letter-spacing:.14em;text-transform:uppercase;color:var(--dim);font-size:11.5px}
header .id b{color:var(--fg);font-weight:600}
.controls{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.controls select,.controls input,.controls button{font-family:var(--mono);font-size:12px;background:var(--panel);color:var(--fg);
  border:1px solid var(--rule);padding:6px 10px;border-radius:0;min-height:32px}
.controls button{background:var(--panel2);cursor:pointer;letter-spacing:.08em;text-transform:uppercase}
.controls button:hover{border-color:var(--dim)}
.controls .busy{color:var(--watch);font-size:11.5px}
.verdict{background:linear-gradient(180deg,var(--panel2),var(--panel));border:1px solid var(--rule);border-left:3px solid var(--ok);
  padding:18px 20px;display:flex;flex-direction:column;gap:10px}
.verdict.watch{border-left-color:var(--watch)} .verdict.act,.verdict.error{border-left-color:var(--act)}
.verdict .tag{font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:var(--ok)}
.verdict.watch .tag{color:var(--watch)} .verdict.act .tag,.verdict.error .tag{color:var(--act)}
.verdict h1{margin:0;font-size:clamp(19px,3.2vw,26px);line-height:1.25;font-weight:600}
.verdict p{margin:0;color:var(--dim);max-width:78ch}
.chips{display:flex;flex-wrap:wrap;gap:8px}
.chip{font-size:11.5px;padding:3px 9px;border:1px solid var(--rule);color:var(--dim)}
.chip i{font-style:normal;margin-right:6px}
.c-ok i{color:var(--ok)} .c-info i{color:var(--info)} .c-watch i{color:var(--watch)} .c-act i{color:var(--act)}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1px;background:var(--rule);border:1px solid var(--rule)}
.stat{background:var(--panel);padding:12px 14px;min-width:0}
.stat .k{font-size:10.5px;letter-spacing:.13em;text-transform:uppercase;color:var(--faint)}
.stat .v{font-size:23px;font-weight:600;line-height:1.25;margin-top:3px;overflow-wrap:anywhere}
.stat .s{font-size:11.5px;color:var(--dim);margin-top:2px}
h2{font-size:11.5px;letter-spacing:.16em;text-transform:uppercase;color:var(--dim);margin:0 0 10px;font-weight:600;display:flex;align-items:center;gap:10px}
h2::after{content:"";flex:1;height:1px;background:var(--rule)}
.two{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,430px),1fr));gap:22px}
.tbl{overflow-x:auto;border:1px solid var(--rule);background:var(--panel)}
table{border-collapse:collapse;width:100%;font-size:12.5px}
table.wide{min-width:780px}
th,td{padding:7px 10px;text-align:right;border-top:1px solid var(--rule);white-space:nowrap}
th{font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--faint);font-weight:600;border-top:0}
th:first-child,td:first-child{text-align:left}
td.l,th.l{text-align:left;white-space:normal}
td.hot{color:var(--act)} tr.tot td{font-weight:600;background:var(--panel2)}
th.m1{color:var(--south)} th.m2{color:var(--east)} th.m3{color:var(--west)}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;vertical-align:middle}
.d-ok{background:var(--ok)} .d-info{background:var(--info)} .d-watch{background:var(--watch)} .d-act{background:var(--act)}
.note{color:var(--faint);font-size:11.5px}
.ledger{display:flex;flex-direction:column;border:1px solid var(--rule)}
.row{display:grid;grid-template-columns:74px 210px minmax(0,1fr);gap:4px 16px;padding:12px 14px;background:var(--panel);border-top:1px solid var(--rule)}
.row:first-child{border-top:0}
.pill{font-size:10.5px;letter-spacing:.12em;text-transform:uppercase;padding:2px 0;text-align:center;border:1px solid;align-self:start}
.p-ok{color:var(--ok)} .p-watch{color:var(--watch)} .p-act{color:var(--act)} .p-info{color:var(--info)}
.row .t{font-weight:600}
.row .d{color:var(--dim);min-width:0}
.row .d .do{color:var(--fg);margin-top:6px}
@media (max-width:720px){.row{grid-template-columns:74px minmax(0,1fr)}.row .d{grid-column:1/-1}}
.charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,480px),1fr));gap:16px}
.charts img{display:block;width:100%;height:auto;border:1px solid var(--rule);border-radius:8px;background:var(--panel)}
ol.todo{margin:0;padding:0;list-style:none;counter-reset:n;display:flex;flex-direction:column;border:1px solid var(--rule)}
ol.todo li{counter-increment:n;display:grid;grid-template-columns:34px minmax(0,1fr);gap:0 10px;padding:11px 14px;background:var(--panel);border-top:1px solid var(--rule);color:var(--dim)}
ol.todo li:first-child{border-top:0}
ol.todo li::before{content:counter(n,decimal-leading-zero);color:var(--faint)}
details{border:1px solid var(--rule);background:var(--panel)}
summary{cursor:pointer;padding:10px 14px;color:var(--dim);letter-spacing:.12em;text-transform:uppercase;font-size:11.5px}
footer{color:var(--faint);font-size:11.5px;border-top:1px solid var(--rule);padding-top:10px}
.empty{padding:40px 20px;text-align:center;color:var(--dim)}
`;

const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const SEV = { ok: "OK", info: "Info", watch: "Watch", act: "Act" };
const CHARTS = ["harvest", "energy", "pv_ac", "grid_voltage", "soc", "cell_voltage", "temperatures"];

class Eg4SolarReportCard extends HTMLElement {
  setConfig(config) {
    if (!config || !config.entity) throw new Error("Set 'entity' to the report sensor, for example sensor.my_station_report");
    this._config = config;
    this._key = null;
    if (this._hass) this.hass = this._hass;
  }

  static getStubConfig(hass) {
    const id = Object.keys(hass.states).find((e) => e.startsWith("sensor.") && e.endsWith("_report") && hass.states[e].attributes.checks !== undefined);
    return { entity: id || "sensor.my_station_report" };
  }

  getCardSize() {
    return 40;
  }

  getGridOptions() {
    return { columns: "full" };
  }

  set hass(hass) {
    this._hass = hass;
    // Some devices hand over hass before setConfig; wait for the config instead of failing
    if (!this._config) return;
    try {
      this._update(hass);
    } catch (err) {
      // Show the real problem in the card rather than Home Assistant's bare "Configuration error"
      if (!this.shadowRoot) this.attachShadow({ mode: "open" });
      this.shadowRoot.innerHTML = `<style>${CSS}</style><div class="page"><div class="empty">EG4 Solar Report card error: ${esc(err && err.message)}</div></div>`;
      console.error("eg4-solar-report-card", err);
    }
  }

  _update(hass) {
    const st = hass.states[this._config.entity];
    const related = this._related(hass);
    // Re-render only when something shown actually changed
    const key = JSON.stringify([
      st && st.last_updated,
      related.map((id) => (hass.states[id] ? hass.states[id].state + (hass.states[id].attributes.entity_picture || "") : "")),
    ]);
    if (key === this._key) return;
    this._key = key;
    this._render(st, related);
  }

  _related(hass) {
    if (this._relatedIds) return this._relatedIds;
    const reg = (hass && hass.entities) || {};
    const me = reg[this._config.entity];
    const ids = me && me.device_id ? Object.keys(reg).filter((id) => reg[id].device_id === me.device_id) : [];
    if (ids.length) this._relatedIds = ids;
    return ids;
  }

  _find(suffix) {
    return (this._relatedIds || []).find((id) => id.endsWith(suffix));
  }

  _render(st, related) {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const root = this.shadowRoot;
    if (!st) {
      root.innerHTML = `<style>${CSS}</style><div class="page"><div class="empty">Entity ${esc(this._config.entity)} not found.</div></div>`;
      return;
    }
    const a = st.attributes || {};
    const verdict = st.state;
    const period = this._find("_report_period");
    const endDate = this._find("_report_end_date");
    const generate = this._find("_generate_report");
    const h = this._hass;
    const periodState = period && h.states[period];
    const dateState = endDate && h.states[endDate];
    const range = a.range ? `${a.range.start} → ${a.range.end}` : "";
    const labels = a.array_labels || [];

    const controls = `
      <div class="controls">
        ${periodState ? `<select id="period">${(periodState.attributes.options || []).map((o) =>
          `<option ${o === periodState.state ? "selected" : ""}>${esc(o)}</option>`).join("")}</select>` : ""}
        ${dateState ? `<input id="end" type="date" value="${esc(dateState.state)}">` : ""}
        ${generate ? `<button id="gen">Generate report</button>` : ""}
        ${a.running ? `<span class="busy">● downloading from EG4…</span>` : ""}
      </div>`;

    const header = `
      <header>
        <div>
          <div class="ttl">${a.period === "7 days" ? "Week review" : a.period === "Today" ? "Day review" : "Solar Report"}</div>
          <div class="id"><b>${esc(range)}</b>${a.samples ? ` · ${Number(a.samples).toLocaleString()} samples @ ${esc(a.interval_min)} min` : ""}</div>
        </div>
        ${controls}
      </header>`;

    if (!a.summary && verdict !== "error") {
      root.innerHTML = `<style>${CSS}</style><div class="page"><div class="wrap">${header}
        <div class="empty">No report yet. Pick a period and press <b>Generate report</b>.</div></div></div>`;
      this._wire();
      return;
    }

    const tag = { healthy: "● Healthy", watch: "▲ Watch", act: "■ Act", error: "■ Report failed" }[verdict] || verdict;
    const chips = (a.chips || []).map((c) =>
      `<span class="chip c-${esc(c.status)}"><i>${c.status === "ok" ? "●" : c.status === "act" ? "■" : c.status === "watch" ? "▲" : "◆"}</i>${esc(c.label)}</span>`).join("");
    const verdictHtml = `
      <section class="verdict ${esc(verdict)}">
        <div class="tag">${esc(tag)}</div>
        <h1>${esc(verdict === "error" ? a.error : a.summary)}</h1>
        ${a.detail ? `<p>${esc(a.detail)}</p>` : ""}
        <div class="chips">${chips}</div>
      </section>`;

    const stats = `<section class="stats">${(a.stats || []).map((s) =>
      `<div class="stat"><div class="k">${esc(s.label)}</div><div class="v">${esc(s.value)}</div><div class="s">${esc(s.sub)}</div></div>`).join("")}</section>`;

    const alarms = `<div><h2>Alarm status</h2><div class="tbl"><table>
      <tr><th class="l">Alarm</th><th>Count</th><th>Last</th></tr>
      ${(a.alarms || []).map((r) => `<tr><td class="l"><span class="dot d-${esc(r.verdict)}"></span>${esc(r.alarm)}</td>
        <td>${esc(r.count)}</td><td>${esc((r.last || "").slice(5, 16).replace("T", " "))}</td></tr>`).join("")}
      </table></div></div>`;

    const unit = a.temp_unit || "";
    const temps = `<div><h2>Temperatures</h2><div class="tbl"><table>
      <tr><th class="l">Sensor</th><th>Min</th><th>Typical</th><th>Max</th></tr>
      ${(a.temperatures || []).map((t) => `<tr><td class="l"><span class="dot d-${esc(t.status)}"></span>${esc(t.sensor)}
        ${t.note ? `<div class="note">${esc(t.note)}</div>` : ""}</td>
        <td>${esc(t.min)}</td><td>${esc(t.typical)}</td><td>${esc(t.max)} ${esc(unit)}</td></tr>`).join("")}
      </table></div></div>`;

    const daily = `<section><h2>Day by day</h2><div class="tbl"><table class="wide">
      <tr><th>Day</th><th>PV kWh</th>${labels.map((l, i) => `<th class="m${i + 1}">${esc(l)}</th>`).join("")}
        <th>Peak kW</th><th>Load</th><th>Export</th><th>Import</th><th>SOC %</th><th>V max</th><th>h &gt; 254 V</th><th>Clip min</th></tr>
      ${(a.daily || []).map((d) => `<tr><td>${esc(d.day)}${d.through ? ` <span class="note">to ${esc(d.through)}</span>` : ""}</td>
        <td>${esc(d.pv)}</td>${(d.arrays || []).map((v) => `<td>${esc(v)}</td>`).join("")}
        <td>${esc(d.peak_kw)}</td><td>${esc(d.load)}</td><td>${esc(d.export)}</td><td>${esc(d.import)}</td>
        <td>${esc(d.soc_min)}–${esc(d.soc_max)}</td><td class="${d.h_over > 0 ? "hot" : ""}">${esc(d.v_max)}</td>
        <td>${esc(d.h_over)}</td><td>${esc(d.clip_min)}</td></tr>`).join("")}
      ${a.totals ? `<tr class="tot"><td>Total</td><td>${esc(a.totals.pv)}</td>${(a.totals.arrays || []).map((v) => `<td>${esc(v)}</td>`).join("")}
        <td></td><td>${esc(a.totals.load)}</td><td>${esc(a.totals.export)}</td><td>${esc(a.totals.import)}</td><td></td><td></td>
        <td>${esc(a.totals.h_over)}</td><td>${esc(a.totals.clip_min)}</td></tr>` : ""}
      </table></div></section>`;

    const findings = `<section><h2>Findings</h2><div class="ledger">${(a.findings || []).map((f) => `
      <div class="row"><span class="pill p-${esc(f.severity)}">${esc(f.group === "Note" ? "Note" : SEV[f.severity] || f.severity)}</span>
        <div class="t">${esc(f.title)}</div>
        <div class="d">${esc(f.detail)}${f.action && f.action !== "None." ? `<div class="do">→ ${esc(f.action)}</div>` : ""}</div></div>`).join("")
      || `<div class="row"><span class="pill p-ok">OK</span><div class="t">Nothing to report</div><div class="d">All 21 checks passed.</div></div>`}
      </div></section>`;

    const imgs = CHARTS.map((k) => this._find(`_chart_${k}`)).filter(Boolean)
      .map((id) => h.states[id] && h.states[id].attributes.entity_picture)
      .filter(Boolean)
      .map((src) => `<img loading="lazy" alt="" src="${esc(src)}">`).join("");
    const charts = imgs ? `<section><h2>Charts</h2><div class="charts">${imgs}</div></section>` : "";

    const todo = (a.actions || []).length ? `<section><h2>What to do</h2><ol class="todo">${a.actions.map((x) => `<li>${esc(x)}</li>`).join("")}</ol></section>` : "";

    const checks = `<details><summary>All ${(a.checks || []).length} checks</summary><div class="tbl" style="border:0"><table>
      ${(a.checks || []).map((c) => `<tr><td class="l"><span class="dot d-${esc(c.status)}"></span>${esc(c.group)}</td>
        <td class="l">${esc(c.check)}</td><td class="l">${esc(c.result)}</td></tr>`).join("")}</table></div></details>`;

    const gen = a.generated_at ? new Date(a.generated_at).toLocaleString() : "";
    const footer = `<footer>Generated ${esc(gen)}${a.trigger ? ` · ${esc(a.trigger)}` : ""}. From your inverter's Monitor Center log; energy figures are the inverter's day counters.</footer>`;

    root.innerHTML = `<style>${CSS}</style><div class="page"><div class="wrap">
      ${header}${verdictHtml}${stats}<div class="two">${alarms}${temps}</div>${findings}${charts}${daily}${todo}${checks}${footer}
      </div></div>`;
    this._wire();
  }

  _wire() {
    const r = this.shadowRoot;
    const h = this._hass;
    const period = this._find("_report_period");
    const endDate = this._find("_report_end_date");
    const generate = this._find("_generate_report");
    const sel = r.getElementById("period");
    if (sel) sel.addEventListener("change", (e) => h.callService("select", "select_option", { entity_id: period, option: e.target.value }));
    const end = r.getElementById("end");
    if (end) end.addEventListener("change", (e) => h.callService("date", "set_value", { entity_id: endDate, date: e.target.value }));
    const gen = r.getElementById("gen");
    if (gen) gen.addEventListener("click", () => h.callService("button", "press", { entity_id: generate }));
  }
}

if (!customElements.get("eg4-solar-report-card")) {
  customElements.define("eg4-solar-report-card", Eg4SolarReportCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "eg4-solar-report-card",
    name: "EG4 Solar Report",
    description: "The full EG4 Solar Report: verdict, readouts, findings, charts and tables.",
  });
}
