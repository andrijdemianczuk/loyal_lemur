/* ED triage dashboard: Alpine component + ECharts. State arrives as a full
   snapshot over server-sent events once a second. */

const ARMS = [
  { key: "ai", name: "AI-assisted", slot: 1 },
  { key: "baseline", name: "Manual", slot: 2 },
];

const KPIS = [
  { key: "waiting", label: "Waiting now", unit: "n" },
  { key: "avg_wait_open_min", label: "Avg wait to physician, since opening", unit: "min" },
  { key: "p90_wait_open_min", label: "P90 wait, since opening", unit: "min" },
  { key: "slo_breaches", label: "Walk-ins past 4 h SLO", unit: "n" },
  { key: "under_triaged", label: "Under-triaged at intake", unit: "n" },
  { key: "lwbs", label: "Left without being seen", unit: "n" },
];

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

// Kept outside Alpine's reactive state: proxying chart instances is costly.
const CHARTS = {};

function cssVar(name) {
  return getComputedStyle(document.body).getPropertyValue(name).trim();
}

function app() {
  return {
    snap: { run: null, arms: {}, series: [], events: [], telemetry: { sinks: {}, event_counts: {} } },
    form: { seed: 3, startHour: "14", surge: 1, ai_mode: "replay", volume: 150, warm: true },
    speeds: [0.5, 1, 2, 5, 10, 20, 30, 45, 60],
    speedIdx: 2,
    kpis: KPIS,
    showTruth: false,
    decFilter: null,
    decisionKinds: [
      { key: "triage", label: "triage raised above rules" },
      { key: "queue", label: "seen out of CTAS order" },
      { key: "intake", label: "zone used after hours" },
      { key: "bed", label: "beds requested at triage" },
    ],
    theme: "light",
    detail: null,
    busy: false,

    init() {
      this.theme = localStorage.getItem("theme")
        || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
      document.documentElement.dataset.theme = this.theme;
      // ?snapshot renders one state fetch with no live connection
      // (used for headless screenshots and printing).
      if (new URLSearchParams(location.search).has("snapshot")) {
        fetch("/api/state").then((r) => r.json()).then((snap) => {
          this.snap = snap;
          this.syncForm();
          this.showTruth = new URLSearchParams(location.search).has("truth");
          this.$nextTick(() => this.updateCharts());
        });
        return;
      }
      const source = new EventSource("/api/stream");
      source.onmessage = (msg) => {
        const first = !this.snap.run;
        this.snap = JSON.parse(msg.data);
        if (first && this.snap.run) this.syncForm();
        if (this.snap.run && !this.speedTouched) {
          const i = this.speeds.indexOf(this.snap.run.speed);
          if (i >= 0) this.speedIdx = i;
        }
        this.updateCharts();
      };
      window.addEventListener("resize", () => Object.values(CHARTS).forEach((c) => c.resize()));
    },

    // -- controls ------------------------------------------------------------
    async post(url, body) {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: body ? JSON.stringify(body) : undefined,
      });
      if (!res.ok) throw new Error(await res.text());
      return res.json();
    },
    async startRun() {
      this.busy = true;
      try {
        const hh = String(this.form.startHour).padStart(2, "0");
        await this.post("/api/run", {
          seed: this.form.seed,
          speed: this.speeds[this.speedIdx],
          surge: Number(this.form.surge),
          volume: this.form.volume,
          ai_mode: this.form.ai_mode,
          start: `2026-11-06T${hh}:00:00-07:00`,
          warmup_hours: this.form.warm ? 30 : 0,
        });
        this.speedTouched = false;
      } finally {
        this.busy = false;
      }
    },
    syncForm() {
      // Reflect the running run's settings in the controls.
      const p = this.snap.params;
      if (!p) return;
      this.form.seed = p.seed;
      this.form.surge = p.surge;
      this.form.ai_mode = p.ai_mode;
      // String, to match the <option> values the select compares against.
      this.form.startHour = String(Number(p.start.slice(11, 13)));
      this.form.warm = p.warmup_hours > 0;
    },
    setSpeed() {
      this.speedTouched = true;
      this.post("/api/speed", { speed: this.speeds[this.speedIdx] });
    },
    toggleTheme() {
      this.theme = this.theme === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = this.theme;
      localStorage.setItem("theme", this.theme);
      for (const k of Object.keys(CHARTS)) { CHARTS[k].dispose(); delete CHARTS[k]; }
      this.$nextTick(() => this.updateCharts());
    },

    // -- formatting ----------------------------------------------------------
    clockText() {
      const t = this.snap.run?.sim_time;
      if (!t) return "";
      const d = new Date(t.slice(0, 10) + "T12:00:00Z");
      return `${WEEKDAYS[d.getUTCDay()]} ${t.slice(11, 16)}`;
    },
    warmupText() {
      const w = this.snap.run?.warmup;
      if (!w) return "";
      const n = Math.round((w.in_ed.ai + w.in_ed.baseline) / 2);
      let text = `Warm start: ${w.hours} h simulated before opening · ${n} patients already in each ED · KPIs count from opening`;
      if (w.ai?.rules_fallbacks && this.snap.params.ai_mode !== "rules") {
        text += ` · ${w.ai.rules_fallbacks} warm-up triages used rules (not recorded)`;
      }
      return text;
    },
    diffWord(key) {
      const d = this.metric("baseline", key) - this.metric("ai", key);
      return { n: Math.abs(d), word: d >= 0 ? "fewer" : "more" };
    },
    bedRequestText() {
      const a = this.snap.arms.ai?.admission;
      if (!a) return "–";
      return `${a.true_pos + a.false_pos} made · ${a.true_pos} needed · ${a.false_neg} admissions missed`;
    },
    metric(arm, key) {
      return this.snap.arms[arm]?.metrics?.[key] ?? 0;
    },
    byCtas(arm, level) {
      return this.snap.arms[arm]?.metrics?.by_ctas?.[level] || { waiting: 0, avg_wait_min: 0 };
    },
    fmt(v, unit) {
      if (unit === "min") return v >= 120 ? this.dur(v) : `${Math.round(v)} min`;
      return String(v);
    },
    dur(min) {
      const m = Math.round(min);
      return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")}`;
    },
    deltaText(k) {
      const ai = this.metric("ai", k.key), base = this.metric("baseline", k.key);
      if (ai === base) return "No difference yet";
      if (k.unit === "n") {
        const d = Math.abs(base - ai);
        return ai < base ? `${d} fewer with AI` : `${d} more with AI`;
      }
      if (!base) return "";
      const pct = Math.round(((ai - base) / base) * 100);
      return pct < 0 ? `▼ ${-pct}% with AI` : `▲ ${pct}% with AI`;
    },
    deltaClass(k) {
      return this.metric("ai", k.key) < this.metric("baseline", k.key) ? "good" : "";
    },
    laneName(lane) {
      return { main: "main", fast: "fast track", intake: "intake" }[lane] || "";
    },
    sourceName(a) {
      if (a.source === "nurse") return "Triage nurse";
      if (a.source === "rules") {
        return a.rationale.startsWith("Provisional") ? "CTAS rules (provisional, AI pending)"
          : a.rationale.startsWith("AI unavailable") ? "CTAS rules (AI fallback)" : "CTAS rules";
      }
      return a.model?.includes("sonnet") ? "Claude Sonnet 5.5 (escalated)" : "Claude Haiku 5.5";
    },

    // -- live feed -----------------------------------------------------------
    decisionItems() {
      const out = [];
      for (const e of (this.snap.decisions || []).slice().reverse()) {
        const d = e.data || {};
        if (this.decFilter && d.decision !== this.decFilter) continue;
        const who = `${d.age}${d.sex} ${d.complaint.charAt(0).toLowerCase()}${d.complaint.slice(1)}`;
        let tag, text;
        switch (d.decision) {
          case "triage": tag = "Triage"; text = `Raised to CTAS ${d.ctas} (rules: ${d.rules_ctas}): ${who}`; break;
          case "queue": tag = "Queue"; text = `Seen ahead of ${d.moved_ahead_of}: ${who}`; break;
          case "intake": tag = "Zone"; text = `Rapid-assessment zone kept open: ${who}`; break;
          case "bed": tag = "Bed"; text = `Bed requested at triage: ${who}`; break;
          default: continue;
        }
        out.push({ ...e, tag, text });
        if (out.length >= 30) break;
      }
      return out;
    },

    // -- detail drawer -------------------------------------------------------
    async openDetail(id, retry = true) {
      const res = await fetch(`/api/encounter/${id}`);
      if (res.status === 404 && retry) {
        setTimeout(() => this.openDetail(id, false), 1200);
        return;
      }
      if (res.ok) this.detail = await res.json();
    },

    // -- charts --------------------------------------------------------------
    initCharts() {
      // Created lazily once the panel is visible; a hidden element has no size.
      for (const id of ["wait", "slo", "ctas"]) {
        const el = document.getElementById(`chart-${id}`);
        if (el && el.clientWidth && !CHARTS[id]) CHARTS[id] = echarts.init(el, null, { renderer: "svg" });
      }
    },
    baseOptions() {
      const muted = cssVar("--text-muted"), grid = cssVar("--grid"), axis = cssVar("--axis");
      return {
        animation: false,
        textStyle: { fontFamily: "system-ui, -apple-system, 'Segoe UI', sans-serif" },
        grid: { left: 44, right: 92, top: 16, bottom: 28 },
        tooltip: {
          trigger: "axis",
          axisPointer: { type: "line", lineStyle: { color: axis } },
          backgroundColor: cssVar("--surface-1"),
          borderColor: cssVar("--border"),
          textStyle: { color: cssVar("--text-primary"), fontSize: 12 },
        },
        xAxis: {
          type: "category", boundaryGap: false,
          axisLine: { lineStyle: { color: axis } }, axisTick: { show: false },
          axisLabel: { color: muted, fontSize: 11 },
        },
        yAxis: {
          type: "value", min: 0,
          splitLine: { lineStyle: { color: grid, width: 1 } },
          axisLabel: { color: muted, fontSize: 11 },
        },
      };
    },
    lineSeries(key) {
      const secondary = cssVar("--text-secondary");
      // Direct labels at the line ends, unless the ends are too close to read
      // apart; the legend still identifies both lines.
      const last = this.snap.series.at(-1);
      const values = this.snap.series.flatMap((p) => [p.ai[key], p.baseline[key]]);
      const range = Math.max(1, ...values);
      const tooClose = last && Math.abs(last.ai[key] - last.baseline[key]) < range * 0.08;
      return ARMS.map((a, i) => ({
        name: a.name, type: "line", showSymbol: false, symbolSize: 8,
        color: cssVar(`--series-${a.slot}`),
        lineStyle: { width: 2 },
        endLabel: { show: !(tooClose && i === 1), formatter: "{a}", color: secondary, fontSize: 11 },
        emphasis: { focus: "series" },
        data: this.snap.series.map((p) => p[a.key][key]),
      }));
    },
    tooltipMinutes(params) {
      // Values lead, labels follow; series keyed by a short line.
      const rows = params.map((p) =>
        `<div style="display:flex;align-items:center;gap:6px">` +
        `<span style="display:inline-block;width:12px;height:2px;background:${p.color}"></span>` +
        `<b>${Math.round(p.value)} min</b> <span style="opacity:.7">${p.seriesName}</span></div>`);
      return `<div style="font-size:11px;opacity:.7">${params[0].axisValue}</div>` + rows.join("");
    },
    updateCharts() {
      if (!this.snap.run) return;
      this.initCharts();
      if (!CHARTS.wait) {
        // Panel not laid out yet: retry briefly, never loop forever.
        this._chartRetries = (this._chartRetries || 0) + 1;
        if (this._chartRetries <= 20) setTimeout(() => this.updateCharts(), 100);
        return;
      }
      this._chartRetries = 0;
      const times = this.snap.series.map((p) => p.t.slice(11, 16));
      const base = this.baseOptions();
      const tip = { ...base.tooltip, formatter: (p) => this.tooltipMinutes(p) };

      CHARTS.wait.setOption({
        ...base, tooltip: tip,
        xAxis: { ...base.xAxis, data: times },
        series: this.lineSeries("avg_wait"),
      }, true);

      const sloSeries = this.lineSeries("max_walk_in_wait");
      const peak = Math.max(260, ...this.snap.series.flatMap((p) => [p.ai.max_walk_in_wait, p.baseline.max_walk_in_wait]));
      sloSeries[0].markLine = {
        silent: true, symbol: "none",
        lineStyle: { color: cssVar("--text-secondary"), type: "dashed", width: 1 },
        label: { formatter: "4 h SLO", color: cssVar("--text-secondary"), position: "insideEndTop", fontSize: 11 },
        data: [{ yAxis: 240 }],
      };
      CHARTS.slo.setOption({
        ...base, tooltip: tip,
        xAxis: { ...base.xAxis, data: times },
        yAxis: { ...base.yAxis, max: Math.ceil(peak * 1.1 / 30) * 30 },
        series: sloSeries,
      }, true);

      const levels = ["1", "2", "3", "4", "5"];
      CHARTS.ctas.setOption({
        ...base,
        grid: { left: 32, right: 12, top: 16, bottom: 28 },
        tooltip: { ...base.tooltip, trigger: "item",
          formatter: (p) => `<b>${p.value} waiting</b> <span style="opacity:.7">${p.seriesName} · ${p.name}</span>` },
        xAxis: { ...base.xAxis, boundaryGap: true, data: levels.map((l) => `CTAS ${l}`) },
        yAxis: { ...base.yAxis, minInterval: 1 },
        series: ARMS.map((a) => ({
          name: a.name, type: "bar", barMaxWidth: 18, barGap: "12%",
          color: cssVar(`--series-${a.slot}`),
          itemStyle: { borderRadius: [4, 4, 0, 0] },
          emphasis: { itemStyle: { opacity: 0.85 } },
          data: levels.map((l) => this.byCtas(a.key, l).waiting),
        })),
      }, true);
    },
  };
}
