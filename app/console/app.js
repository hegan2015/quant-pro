/* quant-pro 控制台（Vue3 全局构建 + Element Plus 本地 vendored，无构建步骤）。
 * 所有数据来自 /api（Bearer 门禁）；前端不做任何判定复算，门禁/风控状态由后端字段驱动。 */
const API = location.port === "8101" ? "http://127.0.0.1:8102" : "";
const { createApp, ref, reactive, computed, onMounted, watch, h } = Vue;

function token() { return localStorage.getItem("qp_token") || ""; }
async function api(path, opts = {}) {
  const res = await fetch(API + path, {
    ...opts,
    headers: { "Content-Type": "application/json",
               ...(token() ? { Authorization: "Bearer " + token() } : {}),
               ...(opts.headers || {}) },
  });
  if (res.status === 401) { localStorage.removeItem("qp_token"); location.hash = "#/login";
    throw new Error("会话过期或未登录（401）"); }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const msg = body.reasons ? body.reasons.join("；") : (body.message || body.detail || res.status);
    const e = new Error(msg); e.status = res.status; e.body = body; throw e;
  }
  return body;
}
const fmtPct = v => v == null ? "—" : (v * 100).toFixed(2) + "%";
const fmtNum = (v, d = 2) => v == null ? "—" : Number(v).toFixed(d);
const cls = v => v > 0 ? "up" : v < 0 ? "down" : "";

/* ---------------------------------------------------------------- 图表（内联 SVG，离线） */
const LineChart = {
  props: { series: Array, labels: Array, height: { default: 240 } },
  setup(p) {
    const svg = computed(() => {
      const W = 1000, H = p.height, pad = 40;
      const clean = p.series
        .map(x => ({ ...x, values: x.values.map(Number).filter(Number.isFinite) }))
        .filter(x => x.values.length);
      if (!clean.length) return "";
      const all = clean.flatMap(x => x.values);
      let lo = Math.min(...all), hi = Math.max(...all);
      const span = (hi - lo) || 1; lo -= span * .06; hi += span * .06;
      const n = Math.max(...clean.map(x => x.values.length));
      const X = i => pad + i * (W - pad - 12) / Math.max(n - 1, 1);
      const Y = v => H - pad - (v - lo) / (hi - lo) * (H - pad * 2);
      const colors = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)"];
      const parts = [`<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="净值曲线">`];
      parts.push(`<defs><linearGradient id="navfill" x1="0" y1="0" x2="0" y2="1">`
        + `<stop offset="0%" stop-color="${colors[0]}" stop-opacity="0.22"/>`
        + `<stop offset="100%" stop-color="${colors[0]}" stop-opacity="0"/></linearGradient></defs>`);
      for (let k = 0; k < 5; k++) {
        const y = pad + k * (H - pad * 2) / 4, v = hi - k * (hi - lo) / 4;
        parts.push(`<line x1="${pad}" y1="${y.toFixed(1)}" x2="${W - 12}" y2="${y.toFixed(1)}"`
          + ` stroke="var(--line-1)"${k ? ' stroke-dasharray="3 3"' : ' stroke-width="1.2"'}/>`);
        parts.push(`<text x="2" y="${(y + 3).toFixed(1)}">${v.toFixed(3)}</text>`);
      }
      const base = Y(Math.max(lo, 0));
      parts.push(`<polygon fill="url(#navfill)" points="${pad},${base.toFixed(1)} `
        + clean[0].values.map((v, i) => `${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(" ")
        + ` ${X(clean[0].values.length - 1).toFixed(1)},${base.toFixed(1)}"/>`);
      clean.forEach((x, j) => {
        const pts = x.values.map((v, i) => `${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(" ");
        parts.push(`<polyline fill="none" stroke="${colors[j % 4]}" stroke-width="1.8"`
          + ` points="${pts}"${x.dash ? ' stroke-dasharray="5 4"' : ""}/>`);
      });
      const step = Math.max(1, Math.floor(n / 8));
      for (let i = 0; i < n; i += step) {
        const t = (p.labels && p.labels[i]) || "";
        if (t) parts.push(`<text x="${(X(i) - 22).toFixed(1)}" y="${H - pad + 15}">${t}</text>`);
      }
      parts.push("</svg>");
      const legend = clean.map((x, i) =>
        `<span><i style="background:${colors[i % 4]}"></i>${x.name}</span>`).join("");
      return `<div class="legend">${legend}</div>` + parts.join("");
    });
    return () => h("div", { innerHTML: svg.value });
  },
};

/* 迷你走势线：KPI 卡右下角，用同一份净值序列，不额外请求 */
const Spark = {
  props: { values: Array, color: { default: "var(--chart-1)" } },
  setup(p) {
    const d = computed(() => {
      const v = (p.values || []).map(Number).filter(Number.isFinite);
      if (v.length < 2) return "";
      const W = 92, H = 30, lo = Math.min(...v), hi = Math.max(...v), sp = (hi - lo) || 1;
      return v.map((x, i) => `${(i * W / (v.length - 1)).toFixed(1)},${(H - (x - lo) / sp * H).toFixed(1)}`).join(" ");
    });
    return () => h("svg", { class: "spark", viewBox: "0 0 92 30", "aria-hidden": "true" },
      [h("polyline", { fill: "none", stroke: p.color, "stroke-width": 1.4, points: d.value })]);
  },
};

/* ---------------------------------------------------------------- 页面 */
const Login = {
  setup() {
    const t = ref(token()); const err = ref(""); const busy = ref(false);
    async function submit() {
      busy.value = true; err.value = "";
      localStorage.setItem("qp_token", t.value.trim());
      try { await api("/api/status"); location.hash = "#/dashboard"; }
      catch (e) { err.value = e.message; localStorage.removeItem("qp_token"); }
      finally { busy.value = false; }
    }
    return { t, err, busy, submit };
  },
  template: `
  <div class="login-box"><el-card>
    <h2 style="margin:0 0 8px">quant-pro 控制台</h2>
    <p class="sub">输入 dev 令牌（由 bootstrap 生成于 ~/.config/quant-pro/auth.json，600）</p>
    <el-input v-model="t" placeholder="qp-..." show-password style="margin:12px 0"/>
    <el-alert v-if="err" :title="err" type="error" :closable="false" style="margin-bottom:12px"/>
    <el-button type="primary" :loading="busy" @click="submit" style="width:100%">登录</el-button>
  </el-card></div>`,
};

const Dashboard = {
  components: { LineChart, Spark },
  setup() {
    const st = ref(null), eq = ref([]), run = ref(null), err = ref("");
    const loading = ref(true);   // 区分「加载中」与「真的没有数据」，避免空态误导
    onMounted(async () => {
      try {
        st.value = await api("/api/status");
        const runs = await api("/api/backtests?limit=1");
        if (runs.length) {
          run.value = await api("/api/backtests/" + runs[0].run_id);
          eq.value = await api(`/api/backtests/${runs[0].run_id}/equity`);
        }
      } catch (e) { err.value = e.message; }
      finally { loading.value = false; }
    });
    const series = computed(() => {
      if (!eq.value.length) return [];
      const out = [{ name: "本组合", values: eq.value.map(x => x.nav) }];
      const bench = eq.value.map(x => x.benchmark_nav);
      if (bench.some(v => Number.isFinite(v))) {
        out.push({ name: "基准 " + (eq.value[0].benchmark_name || "000300"),
                   values: bench, dash: true });
      }
      return out;
    });
    const labels = computed(() => eq.value.map((x, i) => i % 60 === 0 ? String(x.ts).slice(0, 7) : ""));
    const navLast = computed(() => eq.value.length ? Number(eq.value[eq.value.length - 1].nav) : 1);
    // /api/backtests/{id} 的 metrics 是 {full,in,oos,sensitivity} 包装，取 full 展示
    const metrics = computed(() => {
      const m = run.value && run.value.metrics;
      const full = m && (m.full || (m.收益 ? m : null));
      return full && full.收益 ? full : null;
    });
    return { st, eq, run, err, loading, series, labels, navLast, metrics, fmtPct, fmtNum };
  },
  template: `
  <div>
    <el-alert v-if="err" :title="err" type="error" :closable="false"/>
    <el-alert v-if="st && st.breaker_open" type="error" :closable="false" style="margin-bottom:16px"
      title="熔断进行中：仅拒绝新增买入，不强平已有持仓（需 role:risk 人工解除）"/>
    <div class="kpi-grid" v-if="st">
      <div class="kpi">
        <div class="label">组合净值（期末）</div>
        <div class="value" :class="navLast >= 1 ? 'up' : 'down'">{{navLast.toFixed(4)}}</div>
        <div class="delta" :class="navLast - 1 >= 0 ? 'up' : 'down'">
          {{((navLast - 1) * 100).toFixed(2)}}%{{navLast - 1 >= 0 ? ' ▲' : ' ▼'}} 累计
        </div>
        <spark :values="eq.map(x => x.nav)"/>
      </div>
      <div class="kpi">
        <div class="label">年化收益 / Sharpe</div>
        <div class="value sm num">{{metrics ? fmtPct(metrics.收益.年化收益) : '—'}}</div>
        <div class="delta" v-if="metrics">
          <span class="mono-sm">Sharpe {{metrics.比值.Sharpe ?? '—'}} · 回撤 {{fmtPct(metrics.风险.max_drawdown)}}</span>
        </div>
        <div class="delta" v-else><span class="mono-sm">暂无回测记录</span></div>
      </div>
      <div class="kpi">
        <div class="label">行情水位</div>
        <div class="value sm num">{{st.latest_trade_date}}</div>
        <div class="delta"><span class="mono-sm">{{st.bars.toLocaleString()}} 行 · dv {{st.data_version}}</span></div>
      </div>
      <div class="kpi">
        <div class="label">风控 / 模拟盘</div>
        <div class="value sm num" :class="st.open_risk_events ? 'neg' : ''">{{st.open_risk_events}}<span class="sub"> 未确认事件</span></div>
        <div class="delta"><span class="mono-sm">{{st.accounts}} 个账户{{st.breaker_open ? ' · 熔断中' : ''}}</span></div>
      </div>
    </div>
    <el-card style="margin-top:16px" v-if="run">
      <div class="card-h"><h2>最近回测 {{run.run_id}}（{{run.strategy_id}}）</h2>
        <span class="sub">门禁 {{run.lookahead_status}} · 体检见回测页</span></div>
      <line-chart :series="series" :labels="labels"/>
    </el-card>
    <div v-else-if="loading" class="card">
      <div class="mono-sm">正在读取最近回测…</div>
      <div class="skeleton" style="height:220px;margin-top:10px"></div>
    </div>
    <el-empty v-else description="尚无回测记录，去回测页发起"/>
  </div>`,
};

const DataPage = {
  setup() {
    const issues = ref([]), jobs = ref([]), blocking = ref(true), busy = ref(false);
    const dlg = ref(false); const form = reactive({ ts: "", symbol: "", field: "close", new_value: "", reason: "" });
    async function load() {
      issues.value = await api(`/api/data/issues?blocking=${blocking.value}&limit=200`);
      jobs.value = await api("/api/jobs");
    }
    onMounted(load);
    async function submit() {
      busy.value = true;
      try { await api("/api/data/amendments", { method: "POST", body: JSON.stringify(form) });
        ElementPlus.ElMessage.success("已留痕，原行保留"); dlg.value = false; await load(); }
      catch (e) { ElementPlus.ElMessage.error(e.message); }
      finally { busy.value = false; }
    }
    async function runQuality() {
      busy.value = true;
      try { const r = await api("/api/jobs/quality_check/run", { method: "POST" });
        ElementPlus.ElMessage.success(`校验完成：${r.issues} 条 issue`); await load(); }
      catch (e) { ElementPlus.ElMessage.error(e.message); }
      finally { busy.value = false; }
    }
    return { issues, jobs, blocking, load, dlg, form, submit, busy, runQuality };
  },
  template: `
  <div>
    <div class="filters">
      <el-switch v-model="blocking" active-text="仅阻断项" @change="load"/>
      <el-button @click="load">刷新</el-button>
      <el-button type="primary" :loading="busy" @click="runQuality">重跑质量校验</el-button>
      <el-button @click="dlg=true">新增修正（留痕）</el-button>
    </div>
    <el-card><div class="card-h"><h2>数据质量 issue</h2><span class="sub">{{issues.length}} 条</span></div>
      <el-table :data="issues" size="small" max-height="420">
        <el-table-column prop="ts" label="交易日" width="110"/>
        <el-table-column prop="symbol" label="标的" width="110"/>
        <el-table-column prop="kind" label="类型" width="200"/>
        <el-table-column prop="detail" label="详情"/>
        <el-table-column label="阻断" width="80"><template #default="s">
          <el-tag :type="s.row.blocking?'danger':'info'" size="small">{{s.row.blocking?'是':'否'}}</el-tag>
        </template></el-table-column>
        <el-table-column prop="status" label="状态" width="90"/>
      </el-table>
    </el-card>
    <el-card style="margin-top:16px"><div class="card-h"><h2>作业</h2></div>
      <el-table :data="jobs" size="small" max-height="300">
        <el-table-column prop="job_id" label="作业"/><el-table-column prop="trade_date" label="交易日" width="110"/>
        <el-table-column prop="status" label="状态" width="110"/><el-table-column prop="rows_affected" label="行数" width="110"/>
        <el-table-column prop="error" label="错误"/>
      </el-table>
    </el-card>
    <el-dialog v-model="dlg" title="新增数据修正（原行保留，另记流水）" width="480">
      <el-form label-width="90">
        <el-form-item label="交易日"><el-input v-model="form.ts" placeholder="2024-01-02"/></el-form-item>
        <el-form-item label="标的"><el-input v-model="form.symbol"/></el-form-item>
        <el-form-item label="字段"><el-input v-model="form.field"/></el-form-item>
        <el-form-item label="新值"><el-input v-model="form.new_value"/></el-form-item>
        <el-form-item label="理由"><el-input v-model="form.reason" type="textarea"/></el-form-item>
      </el-form>
      <template #footer><el-button @click="dlg=false">取消</el-button>
        <el-button type="primary" :loading="busy" @click="submit">提交修正</el-button></template>
    </el-dialog>
  </div>`,
};

const Research = {
  setup() {
    const factors = ref([]), busy = ref("");
    onMounted(async () => { factors.value = await api("/api/factors"); });
    async function ev(id) {
      busy.value = id;
      try { const r = await api(`/api/factors/${id}/evaluate`, { method: "POST" });
        ElementPlus.ElMessage.success(`${id}: ICIR=${r.icir ?? "—"} IC均值=${r.ic_mean ?? "—"}`);
        factors.value = await api("/api/factors"); }
      catch (e) { ElementPlus.ElMessage.error(e.message); }
      finally { busy.value = ""; }
    }
    return { factors, ev, busy, fmtNum };
  },
  template: `
  <el-card><div class="card-h"><h2>因子库</h2><span class="sub">IC 向量化评估，与 SQL 平均秩实现逐值一致</span></div>
    <el-table :data="factors" size="small">
      <el-table-column prop="factor_id" label="因子" width="140"/>
      <el-table-column prop="name" label="名称"/>
      <el-table-column prop="direction" label="方向" width="70"/>
      <el-table-column label="ICIR" width="90"><template #default="s">{{s.row.eval[0]?.icir ?? '—'}}</template></el-table-column>
      <el-table-column label="IC均值" width="90"><template #default="s">{{s.row.eval[0]?.ic_mean ?? '—'}}</template></el-table-column>
      <el-table-column label="操作" width="120"><template #default="s">
        <el-button size="small" :loading="busy===s.row.factor_id" @click="ev(s.row.factor_id)">评估</el-button>
      </template></el-table-column>
    </el-table>
  </el-card>`,
};

const Backtest = {
  components: { LineChart },
  setup() {
    const form = reactive({ strategy_id: "s2_multifactor", start: "2016-01-04", end: "2025-12-31",
                            train_end: "2021-12-31", top_n: 30, initial_capital: 10000000, sensitivity: false });
    const busy = ref(false), res = ref(null), eq = ref([]), orders = ref([]), err = ref("");
    async function run() {
      busy.value = true; err.value = ""; res.value = null;
      try {
        const params = { top_n: form.top_n,
          factors: { mom_20: .25, mom_60: .15, vol_60: .15, size_float: .15, turnover_20: .15, amihud_20: .15 },
          constraints: { max_weight: .10, max_positions: form.top_n, min_positions: 5, max_turnover: .6 } };
        res.value = await api("/api/backtests", { method: "POST", body: JSON.stringify({
          strategy_id: form.strategy_id, params, start: form.start, end: form.end,
          train_end: form.train_end, initial_capital: form.initial_capital, sensitivity: form.sensitivity }) });
        eq.value = await api(`/api/backtests/${res.value.run_id}/equity`);
        orders.value = await api(`/api/backtests/${res.value.run_id}/orders?status=REJECTED`);
      } catch (e) { err.value = e.message; }
      finally { busy.value = false; }
    }
    const series = computed(() => eq.value.length ? [
      { name: "净值", values: eq.value.map(x => x.nav) },
      { name: "基准", values: eq.value.map(x => x.benchmark_nav), dash: true }] : []);
    const gate = computed(() => res.value?.metrics ? null : null);
    return { form, busy, run, res, eq, orders, err, series, fmtPct, fmtNum, cls };
  },
  template: `
  <div>
    <el-card><div class="card-h"><h2>发起回测</h2><span class="sub">T 日信号 → T+1 开盘成交；滑点进成交价</span></div>
      <el-form inline>
        <el-form-item label="策略"><el-select v-model="form.strategy_id" style="width:180px">
          <el-option value="s2_multifactor" label="S2 多因子月度"/>
          <el-option value="s1_trend" label="S1 双均线择时"/>
          <el-option value="s3_rotation" label="S3 行业轮动"/></el-select></el-form-item>
        <el-form-item label="起"><el-input v-model="form.start" style="width:120px"/></el-form-item>
        <el-form-item label="止"><el-input v-model="form.end" style="width:120px"/></el-form-item>
        <el-form-item label="留出起点"><el-input v-model="form.train_end" style="width:120px"/></el-form-item>
        <el-form-item label="持仓数"><el-input-number v-model="form.top_n" :min="5" :max="100"/></el-form-item>
        <el-form-item label="初始资金"><el-input-number v-model="form.initial_capital" :step="1000000"/></el-form-item>
        <el-form-item label="成本敏感性"><el-switch v-model="form.sensitivity"/></el-form-item>
        <el-form-item><el-button type="primary" :loading="busy" @click="run">发起回测</el-button></el-form-item>
      </el-form>
      <el-alert v-if="err" :title="err" type="error" :closable="false"/>
    </el-card>
    <template v-if="res">
      <div class="kpi-grid" style="margin-top:16px">
        <el-card><div class="sub">年化收益</div><div class="num" :class="cls(res.metrics.收益.年化收益)" style="font-size:20px">{{fmtPct(res.metrics.收益.年化收益)}}</div></el-card>
        <el-card><div class="sub">Sharpe</div><div class="num" style="font-size:20px">{{fmtNum(res.metrics.比值.Sharpe)}}</div></el-card>
        <el-card><div class="sub">最大回撤</div><div class="num neg" style="font-size:20px">{{fmtPct(res.metrics.风险.max_drawdown)}}</div></el-card>
        <el-card><div class="sub">年化换手(单边)</div><div class="num" style="font-size:20px">{{fmtNum(res.metrics.交易.annual_turnover)}}</div></el-card>
      </div>
      <el-card style="margin-top:16px"><div class="card-h"><h2>净值</h2>
        <span class="sub">config_hash {{res.config_hash}} · 门禁
          <span :class="'gate-'+res.lookahead_status">{{res.lookahead_status}}</span> ·
          体检 <span :class="'gate-'+res.checklist_status">{{res.checklist_status}}</span></span></div>
        <line-chart :series="series"/>
        <el-button size="small" tag="a" :href="'/api/backtests/'+res.run_id+'/report'" target="_blank">打开离线报告</el-button>
      </el-card>
      <el-card style="margin-top:16px"><div class="card-h"><h2>拒单留痕</h2><span class="sub">{{orders.length}} 笔</span></div>
        <el-table :data="orders.slice(0,200)" size="small" max-height="320">
          <el-table-column prop="exec_date" label="执行日" width="110"/>
          <el-table-column prop="symbol" label="标的" width="110"/>
          <el-table-column prop="side" label="方向" width="70"/>
          <el-table-column prop="reject_reason" label="原因"/>
        </el-table>
      </el-card>
    </template>
  </div>`,
};

const Signals = {
  setup() {
    const list = ref([]), cur = ref(null), dlg = ref(false), pub = ref(false), wd = ref(false);
    const form = reactive({ trade_date: "", top_n: 30 }); const confirm = ref(false); const reason = ref("");
    const busy = ref(false);
    async function load() { list.value = await api("/api/signals"); }
    onMounted(async () => { const st = await api("/api/status"); form.trade_date = st.latest_trade_date; await load(); });
    async function create() {
      busy.value = true;
      try { const r = await api("/api/signals", { method: "POST", body: JSON.stringify({
          trade_date: form.trade_date, params: { top_n: form.top_n,
            factors: { mom_20: .25, mom_60: .15, vol_60: .15, size_float: .15, turnover_20: .15, amihud_20: .15 },
            constraints: { max_weight: .1, max_positions: form.top_n, min_positions: 5 } } }) });
        ElementPlus.ElMessage.success("草稿已生成 " + r.run_id); dlg.value = false; await load(); await open(r.run_id); }
      catch (e) { ElementPlus.ElMessage.error(e.message); } finally { busy.value = false; }
    }
    async function open(id) { cur.value = await api("/api/signals/" + id); }
    async function doPublish() {
      busy.value = true;
      try { const r = await api(`/api/signals/${cur.value.run_id}/publish`, { method: "POST",
          body: JSON.stringify({ confirm: confirm.value }) });
        ElementPlus.ElMessage.success("已发布"); pub.value = false; await open(cur.value.run_id); await load(); }
      catch (e) { ElementPlus.ElMessage.error(e.message); } finally { busy.value = false; }
    }
    async function doWithdraw() {
      busy.value = true;
      try { await api(`/api/signals/${cur.value.run_id}/withdraw`, { method: "POST",
          body: JSON.stringify({ reason: reason.value }) });
        ElementPlus.ElMessage.success("已撤回"); wd.value = false; await open(cur.value.run_id); await load(); }
      catch (e) { ElementPlus.ElMessage.error(e.message); } finally { busy.value = false; }
    }
    return { list, cur, dlg, pub, wd, form, confirm, reason, busy, load, create, open, doPublish, doWithdraw, fmtPct };
  },
  template: `
  <div>
    <div class="filters"><el-button type="primary" @click="dlg=true">生成当日信号</el-button>
      <el-button @click="load">刷新</el-button></div>
    <el-card><el-table :data="list" size="small" @row-click="r=>open(r.run_id)">
      <el-table-column prop="trade_date" label="信号日" width="110"/>
      <el-table-column prop="run_id" label="run_id"/>
      <el-table-column prop="strategy_id" label="策略" width="140"/>
      <el-table-column label="状态" width="110"><template #default="s">
        <el-tag :type="{draft:'info',published:'success',withdrawn:'danger',superseded:'warning'}[s.row.status]" size="small">{{s.row.status}}</el-tag>
      </template></el-table-column>
      <el-table-column prop="created_by" label="创建人" width="100"/>
    </el-table></el-card>
    <el-card v-if="cur" style="margin-top:16px">
      <div class="card-h"><h2>{{cur.run_id}}</h2><span class="sub">{{cur.status}}</span>
        <div class="right">
          <el-button v-if="cur.status==='draft'" type="primary" size="small" @click="pub=true;confirm=false">发布</el-button>
          <el-button v-if="cur.status==='published'" type="danger" size="small" @click="wd=true;reason=''">撤回</el-button>
        </div></div>
      <div class="checks">
        <div v-for="c in cur.checks" :class="'check '+(c.status==='pass'?'pass':c.status==='FAIL'?'fail':'warn')">
          <span class="n">{{c.name}}</span><span :class="'gate-'+c.status">{{c.status}}</span>
          <span class="mono-sm">{{c.detail}}</span>
        </div>
      </div>
      <el-table :data="cur.items" size="small" max-height="360" style="margin-top:12px">
        <el-table-column prop="symbol" label="标的" width="120"/>
        <el-table-column label="目标权重" width="110"><template #default="s">{{fmtPct(s.row.target_weight)}}</template></el-table-column>
        <el-table-column label="当前权重" width="110"><template #default="s">{{fmtPct(s.row.current_weight)}}</template></el-table-column>
        <el-table-column label="Δ" width="110"><template #default="s">{{fmtPct(s.row.delta)}}</template></el-table-column>
      </el-table>
    </el-card>
    <el-dialog v-model="dlg" title="生成信号草稿" width="420">
      <el-form label-width="90"><el-form-item label="信号日"><el-input v-model="form.trade_date"/></el-form-item>
        <el-form-item label="持仓数"><el-input-number v-model="form.top_n" :min="5" :max="100"/></el-form-item></el-form>
      <template #footer><el-button @click="dlg=false">取消</el-button>
        <el-button type="primary" :loading="busy" @click="create">生成</el-button></template>
    </el-dialog>
    <el-dialog v-model="pub" title="发布信号（不可逆）" width="460">
      <p class="sub">发布后模拟盘次日按此目标建仓；发布内容不可修改，只能撤回。</p>
      <el-checkbox v-model="confirm">我已确认口径与影响（必填勾选）</el-checkbox>
      <template #footer><el-button @click="pub=false">取消</el-button>
        <el-button type="primary" :loading="busy" :disabled="!confirm" @click="doPublish">确认发布</el-button></template>
    </el-dialog>
    <el-dialog v-model="wd" title="撤回信号" width="420">
      <el-input v-model="reason" type="textarea" placeholder="撤回原因（必填）"/>
      <template #footer><el-button @click="wd=false">取消</el-button>
        <el-button type="danger" :loading="busy" :disabled="!reason" @click="doWithdraw">确认撤回</el-button></template>
    </el-dialog>
  </div>`,
};

const Paper = {
  setup() {
    const accounts = ref([]), aid = ref(""), tab = ref("positions");
    const pos = ref([]), orders = ref([]), eq = ref([]), recon = ref([]), led = ref([]);
    const dlg = ref(false), st = ref(false), rp = ref(false), busy = ref(false);
    const form = reactive({ name: "demo", start_date: "2016-01-04", initial_capital: 10000000 });
    const upto = ref(""); const from = ref("");
    async function loadAccounts() {
      const list = await api("/api/paper/accounts");
      // 默认选「最近创建」的账户：早期演示账户没有结算数据，直接选中会显示空表
      accounts.value = [...list].sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
      if (!aid.value && accounts.value.length) aid.value = accounts.value[0].account_id;
    }
    async function loadAll() {
      if (!aid.value) return;
      [pos.value, orders.value, eq.value, recon.value, led.value] = await Promise.all([
        api(`/api/paper/accounts/${aid.value}/positions`),
        api(`/api/paper/accounts/${aid.value}/orders`),
        api(`/api/paper/accounts/${aid.value}/equity`),
        api(`/api/paper/accounts/${aid.value}/reconciliation`),
        api(`/api/paper/accounts/${aid.value}/ledger`)]);
    }
    onMounted(async () => { await loadAccounts(); await loadAll();
      const s = await api("/api/status"); upto.value = s.latest_trade_date; from.value = s.latest_trade_date; });
    watch(aid, loadAll);
    async function create() { busy.value = true;
      try { const r = await api("/api/paper/accounts", { method: "POST", body: JSON.stringify(form) });
        aid.value = r.account_id; dlg.value = false; await loadAccounts(); await loadAll(); }
      catch (e) { ElementPlus.ElMessage.error(e.message); } finally { busy.value = false; } }
    async function settle() { busy.value = true;
      try { const r = await api(`/api/paper/accounts/${aid.value}/settle`, { method: "POST",
          body: JSON.stringify({ upto: upto.value }) });
        ElementPlus.ElMessage.success(`结算 ${r.days} 日，对账最大差额 ${r.recon_max_bp}bp`); await loadAll(); }
      catch (e) { ElementPlus.ElMessage.error(e.message); } finally { busy.value = false; } }
    async function replay() { busy.value = true;
      try { const r = await api(`/api/paper/accounts/${aid.value}/replay`, { method: "POST",
          body: JSON.stringify({ from_date: from.value }) });
        ElementPlus.ElMessage.success("重放副本 " + r.account_id + "（原账户零写入）");
        aid.value = r.account_id; rp.value = false; await loadAccounts(); await loadAll(); }
      catch (e) { ElementPlus.ElMessage.error(e.message); } finally { busy.value = false; } }
    return { accounts, aid, tab, pos, orders, eq, recon, led, dlg, st, rp, form, upto, from, busy,
             loadAccounts, loadAll, create, settle, replay, fmtPct, fmtNum };
  },
  template: `
  <div>
    <div class="filters">
      <el-select v-model="aid" style="width:260px" placeholder="选择账户">
        <el-option v-for="a in accounts" :key="a.account_id" :value="a.account_id" :label="a.name + ' (' + a.account_id + ')'"/>
      </el-select>
      <el-button @click="dlg=true">新建账户</el-button>
      <el-button type="primary" :loading="busy" @click="st=true">结算</el-button>
      <el-button :loading="busy" @click="rp=true">重放副本</el-button>
    </div>
    <el-tabs v-model="tab">
      <el-tab-pane label="持仓" name="positions">
        <el-table :data="pos" size="small" max-height="420">
          <el-table-column prop="ts" label="日期" width="110"/><el-table-column prop="symbol" label="标的" width="110"/>
          <el-table-column prop="qty" label="数量" width="100"/><el-table-column prop="sellable_qty" label="可售" width="90"/>
          <el-table-column label="市值" width="130"><template #default="s">{{fmtNum(s.row.mv)}}</template></el-table-column>
          <el-table-column label="权重" width="90"><template #default="s">{{fmtPct(s.row.weight)}}</template></el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane label="订单/拒单" name="orders">
        <el-table :data="orders" size="small" max-height="420">
          <el-table-column prop="exec_date" label="执行日" width="110"/><el-table-column prop="symbol" label="标的" width="110"/>
          <el-table-column prop="side" label="方向" width="70"/><el-table-column prop="filled_qty" label="成交" width="90"/>
          <el-table-column prop="status" label="状态" width="110"/><el-table-column prop="reject_reason" label="拒因"/>
        </el-table>
      </el-tab-pane>
      <el-tab-pane label="净值" name="equity">
        <el-table :data="eq" size="small" max-height="420">
          <el-table-column prop="ts" label="日期" width="110"/>
          <el-table-column label="净值" width="110"><template #default="s">{{fmtNum(s.row.nav,4)}}</template></el-table-column>
          <el-table-column label="现金" width="140"><template #default="s">{{fmtNum(s.row.cash)}}</template></el-table-column>
          <el-table-column label="市值" width="140"><template #default="s">{{fmtNum(s.row.mv)}}</template></el-table-column>
          <el-table-column label="暴露" width="90"><template #default="s">{{fmtPct(s.row.exposure)}}</template></el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane label="对账" name="recon">
        <el-alert type="info" :closable="false" title="对账从落库产物独立重算（流水+持仓+复权价），不读引擎内部账本；无手工调整入口"/>
        <el-table :data="recon" size="small" max-height="380" style="margin-top:12px">
          <el-table-column prop="ts" label="日期" width="110"/>
          <el-table-column label="重算净值" width="120"><template #default="s">{{fmtNum(s.row.expected,6)}}</template></el-table-column>
          <el-table-column label="落库净值" width="120"><template #default="s">{{fmtNum(s.row.actual,6)}}</template></el-table-column>
          <el-table-column label="差额(bp)" width="100"><template #default="s">
            <span :class="Math.abs(s.row.diff_bp)>1?'neg':''">{{fmtNum(s.row.diff_bp,3)}}</span></template></el-table-column>
          <el-table-column prop="status" label="状态" width="80"/>
        </el-table>
      </el-tab-pane>
      <el-tab-pane label="流水" name="ledger">
        <el-table :data="led" size="small" max-height="420">
          <el-table-column prop="ts" label="日期" width="110"/><el-table-column prop="kind" label="类型" width="90"/>
          <el-table-column prop="symbol" label="标的" width="110"/><el-table-column prop="qty" label="数量" width="90"/>
          <el-table-column label="金额" width="140"><template #default="s">{{fmtNum(s.row.amount)}}</template></el-table-column>
          <el-table-column prop="ref" label="来源(幂等键)"/>
        </el-table>
      </el-tab-pane>
    </el-tabs>
    <el-dialog v-model="dlg" title="新建模拟盘账户" width="440">
      <el-form label-width="90"><el-form-item label="名称"><el-input v-model="form.name"/></el-form-item>
        <el-form-item label="起点"><el-input v-model="form.start_date"/></el-form-item>
        <el-form-item label="初始资金"><el-input-number v-model="form.initial_capital" :step="1000000"/></el-form-item></el-form>
      <template #footer><el-button @click="dlg=false">取消</el-button>
        <el-button type="primary" :loading="busy" @click="create">创建</el-button></template>
    </el-dialog>
    <el-dialog v-model="st" title="结算到某日（幂等重跑）" width="420">
      <el-input v-model="upto"/>
      <template #footer><el-button @click="st=false">取消</el-button>
        <el-button type="primary" :loading="busy" @click="settle();st=false">结算</el-button></template>
    </el-dialog>
    <el-dialog v-model="rp" title="重放副本（原账户零写入）" width="420">
      <p class="sub">生成独立账户副本用于验证；原账户净值与流水不变。</p>
      <el-input v-model="from"/>
      <template #footer><el-button @click="rp=false">取消</el-button>
        <el-button type="danger" :loading="busy" @click="replay">生成副本</el-button></template>
    </el-dialog>
  </div>`,
};

const Risk = {
  setup() {
    const rules = ref([]), events = ref([]), breaker = ref(false);
    const dlg = ref(false), ack = ref(false), cur = ref(null), reason = ref(""), busy = ref(false);
    const form = reactive({ threshold: 0, enabled: true });
    async function load() {
      rules.value = await api("/api/risk/rules");
      events.value = await api("/api/risk/events");
      breaker.value = (await api("/api/risk/breaker")).open;
    }
    onMounted(load);
    function edit(r) { cur.value = r; form.threshold = r.threshold; form.enabled = r.enabled; reason.value = ""; dlg.value = true; }
    async function save() { busy.value = true;
      try { await api(`/api/risk/rules/${cur.value.rule_id}`, { method: "PUT",
          body: JSON.stringify({ threshold: form.threshold, enabled: form.enabled, reason: reason.value }) });
        ElementPlus.ElMessage.success("已更新并留痕"); dlg.value = false; await load(); }
      catch (e) { ElementPlus.ElMessage.error(e.message); } finally { busy.value = false; } }
    function openAck(e) { cur.value = e; reason.value = ""; ack.value = true; }
    async function doAck() { busy.value = true;
      try { await api(`/api/risk/events/${cur.value.id}/ack`, { method: "POST",
          body: JSON.stringify({ reason: reason.value }) });
        ElementPlus.ElMessage.success("已确认"); ack.value = false; await load(); }
      catch (e) { ElementPlus.ElMessage.error(e.message); } finally { busy.value = false; } }
    return { rules, events, breaker, dlg, ack, cur, form, reason, busy, load, edit, save, openAck, doAck };
  },
  template: `
  <div>
    <el-alert v-if="breaker" type="error" :closable="false" style="margin-bottom:16px"
      title="熔断进行中：仅拒绝新增买入；解除需 role:risk 确认事件"/>
    <el-card><div class="card-h"><h2>规则</h2><span class="sub">编辑需 role:risk，变更留痕</span></div>
      <el-table :data="rules" size="small">
        <el-table-column prop="rule_id" label="规则" width="170"/><el-table-column prop="name" label="名称"/>
        <el-table-column prop="metric" label="指标" width="220"/><el-table-column prop="op" label="比较" width="60"/>
        <el-table-column prop="threshold" label="阈值" width="80"/><el-table-column prop="action" label="动作" width="130"/>
        <el-table-column label="启用" width="70"><template #default="s">{{s.row.enabled?'是':'否'}}</template></el-table-column>
        <el-table-column label="操作" width="80"><template #default="s">
          <el-button size="small" @click="edit(s.row)">编辑</el-button></template></el-table-column>
      </el-table>
    </el-card>
    <el-card style="margin-top:16px"><div class="card-h"><h2>事件</h2></div>
      <el-table :data="events" size="small" max-height="360">
        <el-table-column prop="trade_date" label="日期" width="110"/><el-table-column prop="rule_id" label="规则" width="170"/>
        <el-table-column prop="symbol" label="标的" width="110"/><el-table-column prop="action" label="动作" width="130"/>
        <el-table-column prop="status" label="状态" width="80"/><el-table-column prop="acked_by" label="确认人" width="90"/>
        <el-table-column label="操作" width="80"><template #default="s">
          <el-button v-if="s.row.status==='open'" size="small" type="primary" @click="openAck(s.row)">确认</el-button>
        </template></el-table-column>
      </el-table>
    </el-card>
    <el-dialog v-model="dlg" title="编辑规则" width="440">
      <el-form label-width="90"><el-form-item label="阈值"><el-input-number v-model="form.threshold" :step="0.01"/></el-form-item>
        <el-form-item label="启用"><el-switch v-model="form.enabled"/></el-form-item>
        <el-form-item label="理由"><el-input v-model="reason" type="textarea"/></el-form-item></el-form>
      <template #footer><el-button @click="dlg=false">取消</el-button>
        <el-button type="primary" :loading="busy" :disabled="!reason" @click="save">保存</el-button></template>
    </el-dialog>
    <el-dialog v-model="ack" title="确认风控事件" width="420">
      <el-input v-model="reason" type="textarea" placeholder="复核结论（必填）"/>
      <template #footer><el-button @click="ack=false">取消</el-button>
        <el-button type="primary" :loading="busy" :disabled="!reason" @click="doAck">确认</el-button></template>
    </el-dialog>
  </div>`,
};

const System = {
  setup() {
    const st = ref(null), health = ref(null);
    onMounted(async () => { st.value = await api("/api/status");
      health.value = await (await fetch(API + "/healthz")).json(); });
    return { st, health };
  },
  template: `
  <el-card><div class="card-h"><h2>系统状态</h2></div>
    <pre class="mono-sm" style="white-space:pre-wrap">{{JSON.stringify({status:st,health},null,2)}}</pre>
    <p class="sub">密钥与令牌存于 ~/.config/quant-pro/（600），仓库仅 example；本页不回显任何口令。</p>
  </el-card>`,
};

/* ---------------------------------------------------------------- 根 */
const PAGES = { dashboard: Dashboard, data: DataPage, research: Research, backtest: Backtest,
                signals: Signals, paper: Paper, risk: Risk, system: System, login: Login };
const ICONS = {
  dashboard: "M3 13h8V3H3v10zm0 8h8v-6H3v6zm10 0h8V11h-8v10zm0-18v6h8V3h-8z",
  data: "M12 3C7 3 3 4.8 3 7v10c0 2.2 4 4 9 4s9-1.8 9-4V7c0-2.2-4-4-9-4zm0 2c4.4 0 7 1.6 7 2s-2.6 2-7 2-7-1.6-7-2 2.6-2 7-2z",
  research: "M4 20V10m6 10V4m6 16v-7m4 7H2",
  backtest: "M3 3v18h18M7 15l4-6 4 3 5-8",
  signals: "M4 4h16v4H4zM4 12h10v4H4zM4 20h6",
  paper: "M3 7h18v13H3zM3 7l2-4h14l2 4M9 11h6",
  risk: "M12 3l8 4v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V7l8-4zm0 6v4m0 3v.5",
  system: "M12 8a4 4 0 100 8 4 4 0 000-8zm9 4l-2.2-.6-.5-1.2 1.2-1.9-1.8-1.8-1.9 1.2-1.2-.5L14 3h-4l-.6 2.2-1.2.5-1.9-1.2-1.8 1.8 1.2 1.9-.5 1.2L3 12v4l2.2.6.5 1.2-1.2 1.9 1.8 1.8 1.9-1.2 1.2.5L10 23h4l.6-2.2 1.2-.5 1.9 1.2 1.8-1.8-1.2-1.9.5-1.2L21 16v-4z",
};
const NAV = [
  ["概览", [["dashboard", "总览驾驶舱"]]],
  ["数据", [["data", "质量 / 作业 / 修正"]]],
  ["研究", [["research", "因子库"]]],
  ["回测", [["backtest", "发起与结果"]]],
  ["信号", [["signals", "当日信号与发布"]]],
  ["模拟盘", [["paper", "账户 / 持仓 / 对账"]]],
  ["风控", [["risk", "规则 / 事件 / 熔断"]]],
  ["系统", [["system", "状态"]]],
];

const Root = {
  setup() {
    const page = ref(location.hash.replace("#/", "") || "dashboard");
    const st = ref(null);
    const idx = ref([]);
    const theme = ref(localStorage.getItem("qp_theme") || "dark");
    const clock = ref(new Date().toLocaleTimeString("zh-CN", { hour12: false }));
    function applyTheme(t) {
      theme.value = t;
      localStorage.setItem("qp_theme", t);
      document.documentElement.setAttribute("data-theme", t);
      document.documentElement.classList.toggle("dark", t === "dark");
    }
    function go(k) { location.hash = "#/" + k; }
    function onHash() { page.value = location.hash.replace("#/", "") || "dashboard"; }
    window.addEventListener("hashchange", onHash);
    async function refresh() {
      try { st.value = await api("/api/status"); } catch (e) { st.value = null; }
      try { idx.value = await api("/api/indices"); } catch (e) { idx.value = []; }
    }
    onMounted(async () => {
      if (token()) await refresh();
      setInterval(() => { clock.value = new Date().toLocaleTimeString("zh-CN", { hour12: false }); }, 1000);
    });
    watch(page, () => { if (token()) refresh(); });
    function logout() { localStorage.removeItem("qp_token"); st.value = null; go("login"); }
    const comp = computed(() => PAGES[page.value] || Dashboard);
    return { page, go, comp, st, idx, theme, clock, logout, NAV, icons: ICONS, applyTheme, refresh };
  },
  template: `
  <div v-if="page==='login'"><login/></div>
  <div v-else>
    <header class="qp-top">
      <span class="qp-brand">QUANT·PRO<small>量化终端</small></span>
      <span class="chip chip-err">LOCAL</span>
      <span class="chip chip-warn" v-if="st && st.breaker_open">熔断中 · 仅拒新增买入</span>
      <span class="chip" v-if="st"><span class="dot dot-ok"></span>{{st.latest_trade_date}}</span>
      <span class="spacer"></span>
      <input class="search" placeholder="搜索 标的 / 策略 / run_id" aria-label="搜索">
      <button class="btn" @click="applyTheme(theme === 'dark' ? 'light' : 'dark')"
              :title="'切换主题（当前 ' + theme + '）'">{{ theme === 'dark' ? '亮色' : '暗色' }}</button>
      <span class="mono-sm">{{clock}}</span>
      <span class="chip" v-if="st">{{st.user}} · {{st.roles.join('/')}}</span>
      <button class="btn" @click="logout">退出</button>
    </header>
    <div class="ticker" v-if="idx.length" role="group" aria-label="指数行情">
      <template v-for="(x, i) in idx" :key="x.index_code">
        <span class="ticker-item">
          <span class="nm">{{x.name}}</span>
          <span class="px" :class="x.chg >= 0 ? 'up' : 'down'">{{x.close.toLocaleString(undefined,{minimumFractionDigits:2})}}</span>
          <span class="cg" :class="x.chg >= 0 ? 'up' : 'down'">{{(x.chg >= 0 ? '+' : '') + (x.chg * 100).toFixed(2)}}%{{x.chg >= 0 ? '▲' : '▼'}}</span>
        </span>
        <span class="ticker-sep" v-if="i < idx.length - 1"></span>
      </template>
    </div>
    <div class="qp-shell">
      <nav class="qp-nav">
        <div v-for="g in NAV" :key="g[0]" class="nav-group">
          <div class="nav-title">{{g[0]}}</div>
          <a v-for="it in g[1]" :key="it[0]" :class="'nav-item'+(page===it[0]?' active':'')"
             href="javascript:void(0)" @click="go(it[0])">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path :d="icons[it[0]]"/></svg>
            <span>{{it[1]}}</span></a>
        </div>
      </nav>
      <main class="qp-main"><component :is="comp"/></main>
    </div>
    <footer class="qp-foot">
      <span v-if="st">数据水位 <b class="wm">{{st.latest_trade_date}}</b> · {{st.bars.toLocaleString()}} 行 · dv <b class="wm">{{st.data_version}}</b></span>
      <span v-if="st">· store {{st.store_mode || 'duckdb'}}</span>
      <span v-if="st">· 回测 {{st.runs}} · 信号 {{st.signals}} · 账户 {{st.accounts}}</span>
      <span class="spacer" style="flex:1"></span>
      <span>免责声明：输出为量化研究结论，不构成投资建议；系统不连接券商实盘通道</span>
    </footer>
  </div>`,
  components: { Login },
};

const app = createApp(Root);
app.use(ElementPlus, { locale: ElementPlusLocaleZhCn });
app.component("line-chart", LineChart);
app.mount("#app");
