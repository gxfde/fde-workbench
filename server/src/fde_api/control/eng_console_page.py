"""AF1-WP4：工程台自包含 HTML 面（docs/ai-fde/13 §5 一屏三区，L 版基调）。

纯常量模块：零外链（交付形态禁 CDN，硬条件同 TrustBoard）、零构建链——
JS 纯薄渲染（fetch 投影 API + 三钮提交），业务逻辑全部在服务端。视觉基调
直取 TrustBoard L 版（docs/v3.3/m6/mockups/trustboard-mock-light.html，
P1 2026-11-15 选定）：底 #f5f7fa / 主蓝 #2563eb / 唯一深色横幅 = 执行时间线 /
水印条。CSP 见 eng_routes（内联 style/script 是自包含形态的显式代价，登记于
规格 §10 视觉验收）。
"""

CONSOLE_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FDE 工程台</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family:"Segoe UI","Microsoft YaHei",system-ui,sans-serif; background:#f5f7fa; color:#1f2937; }
  .topbar { background:#fff; border-bottom:1px solid #e5e7eb; padding:14px 32px;
    display:flex; align-items:center; justify-content:space-between; }
  .brand { display:flex; align-items:center; gap:12px; }
  .logo { width:34px; height:34px; border-radius:8px; background:linear-gradient(135deg,#2563eb,#38bdf8);
    display:flex; align-items:center; justify-content:center; color:#fff; font-weight:700; font-size:15px; }
  .brand h1 { font-size:18px; font-weight:600; }
  .brand .sub { font-size:12px; color:#6b7280; margin-top:2px; }
  .badges { display:flex; gap:8px; align-items:center; }
  .badge { font-size:12px; padding:4px 12px; border-radius:999px; border:1px solid; }
  .badge.lvl { background:#eff6ff; color:#2563eb; border-color:#bfdbfe; }
  .badge.tok { background:#ecfdf5; color:#047857; border-color:#a7f3d0; }
  .cols { max-width:1460px; margin:14px auto 0; padding:0 20px 28px;
    display:grid; grid-template-columns:270px 1fr 420px; gap:12px; }
  .card { background:#fff; border:1px solid #e5e7eb; border-radius:12px; padding:14px 15px; margin-bottom:12px; }
  .card h3 { font-size:13px; color:#374151; margin-bottom:10px; }
  .runrow { padding:9px 10px; border:1px solid #e5e7eb; border-radius:10px; margin-bottom:8px; cursor:pointer; }
  .runrow.sel { border-color:#2563eb; background:#eff6ff; box-shadow:0 0 0 3px rgba(37,99,235,.12); }
  .runrow .t { font-size:13px; font-weight:600; color:#111827; }
  .runrow .m { font-size:11px; color:#6b7280; margin-top:3px; }
  .st { display:inline-block; font-size:10px; padding:1px 8px; border-radius:999px; margin-left:6px; vertical-align:1px; }
  .st.run,.st.queued,.st.host_running { background:#ecfdf5; color:#047857; border:1px solid #a7f3d0; }
  .st.done,.st.completed { background:#f3f4f6; color:#6b7280; border:1px solid #e5e7eb; }
  .st.fail,.st.cancelled,.st.timeout,.st.failed,.st.budget_exceeded { background:#fef2f2; color:#b91c1c; border:1px solid #fecaca; }
  .ctxline { display:flex; justify-content:space-between; font-size:12px; padding:5px 0; color:#4b5563; }
  .ctxline + .ctxline { border-top:1px dashed #f3f4f6; }
  .ctxline b { font-weight:600; color:#1f2937; max-width:60%; text-align:right;
    overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .tl-card { background:linear-gradient(160deg,#0d1530,#111c3d); border-radius:14px; padding:16px 18px;
    box-shadow:0 4px 18px rgba(13,21,48,.18); color:#e5eefb; min-height:200px; }
  .tl-card h3 { color:#e5eefb; }
  .tl-card .hint { font-size:11px; color:#8ea3c8; margin-bottom:12px; }
  .round { display:flex; gap:10px; padding:9px 0; border-top:1px dashed #2a3a63; align-items:flex-start; cursor:pointer; }
  .round.hit { background:rgba(37,99,235,.16); border-radius:10px; padding:9px 8px; margin:0 -8px; }
  .round .no { flex-shrink:0; width:26px; height:26px; border-radius:50%; border:2px solid #3d548c;
    color:#aebbdc; font-size:11px; display:flex; align-items:center; justify-content:center; }
  .round.v .no { border-color:#10b981; color:#6ee7b7; }
  .round.x .no { border-color:#f59e0b; color:#fcd34d; }
  .round .body { min-width:0; flex:1; }
  .round .tt { font-size:12.5px; font-weight:600; color:#dbe6f7; font-family:Consolas,monospace; }
  .round .dd { font-size:11.5px; color:#8ea3c8; margin-top:2px; word-break:break-all; }
  .vt { display:inline-block; font-size:10px; padding:1px 8px; border-radius:999px; margin-left:8px; vertical-align:1px; }
  .vt.pass { background:rgba(16,185,129,.18); color:#6ee7b7; border:1px solid rgba(16,185,129,.5); }
  .vt.viol { background:rgba(245,158,11,.16); color:#fcd34d; border:1px solid rgba(245,158,11,.5); }
  .vt.deny { background:rgba(239,68,68,.16); color:#fca5a5; border:1px solid rgba(239,68,68,.5); }
  .dcell { font-family:Consolas,monospace; font-size:11px; border-radius:8px; padding:7px 9px;
    border:1px solid #e5e7eb; background:#f9fafb; color:#374151; word-break:break-all; white-space:pre-wrap; }
  .dcell.old { border-color:#fecaca; background:#fef2f2; color:#b91c1c; }
  .dcell.new { border-color:#a7f3d0; background:#ecfdf5; color:#047857; }
  .dkey { font-size:11px; color:#6b7280; margin:6px 0 4px; }
  .viol { border-left:3px solid #f59e0b; background:#fffbeb; border-radius:0 8px 8px 0;
    padding:7px 10px; font-size:12px; color:#92400e; margin-bottom:7px; word-break:break-all; }
  .appr { display:flex; align-items:center; gap:8px; padding:6px 0; font-size:12.5px; flex-wrap:wrap; }
  .appr + .appr { border-top:1px dashed #f3f4f6; }
  .pill { font-size:10px; padding:1px 9px; border-radius:999px; }
  .pill.pending { background:#fffbeb; color:#b45309; border:1px solid #fde68a; }
  .pill.approved { background:#ecfdf5; color:#047857; border:1px solid #a7f3d0; }
  .pill.rejected { background:#fef2f2; color:#b91c1c; border:1px solid #fecaca; }
  .btns { display:flex; gap:8px; margin-top:10px; flex-wrap:wrap; }
  .btn { flex:1; min-width:110px; text-align:center; font-size:12.5px; padding:8px 0;
    border-radius:9px; border:1px solid; cursor:pointer; background:#fff; }
  .btn.warn { border-color:#fde68a; background:#fffbeb; color:#b45309; }
  .btn.info { border-color:#bfdbfe; background:#eff6ff; color:#2563eb; }
  .btn:disabled { opacity:.5; cursor:not-allowed; }
  .note { font-size:10.5px; color:#9ca3af; margin-top:6px; }
  .statusbar { background:#fff; border-top:1px solid #e5e7eb; padding:8px 32px; display:flex; gap:18px;
    align-items:center; font-size:11.5px; color:#6b7280; position:fixed; bottom:0; left:0; right:0; }
  .statusbar b { color:#374151; font-weight:600; }
  .watermark { margin-left:auto; background:rgba(17,24,39,.82); color:#e5e7eb; font-size:11px;
    padding:4px 12px; border-radius:999px; letter-spacing:.5px; }
  .empty { font-size:12px; color:#9ca3af; padding:10px 0; }
  dialog { border:none; border-radius:14px; padding:20px; width:340px; }
  dialog::backdrop { background:rgba(15,23,42,.45); }
  dialog h4 { font-size:14px; margin-bottom:10px; color:#1f2937; }
  dialog input, dialog select, dialog textarea { width:100%; font-size:13px; padding:8px; margin-bottom:8px;
    border:1px solid #d1d5db; border-radius:8px; font-family:inherit; }
  .err { color:#b91c1c; font-size:12px; margin-top:6px; min-height:14px; }
</style>
</head>
<body>
<div class="topbar">
  <div class="brand">
    <div class="logo">工</div>
    <div>
      <h1 id="org-title">工程台</h1>
      <div class="sub">独立工程入口 · 与 TrustBoard 平行 · 全部写操作走服务端既有闸</div>
    </div>
  </div>
  <div class="badges">
    <span class="badge lvl" id="lvl-badge">…</span>
    <span class="badge tok" id="tok-badge">…</span>
    <button class="btn" id="btn-logout" style="flex:0 0 auto;padding:4px 12px">登出并吊销会话</button>
  </div>
</div>

<div class="cols">
  <div>
    <div class="card"><h3>任务（Agent 运行）</h3><div id="runs"><div class="empty">加载中…</div></div></div>
    <div class="card"><h3>所选运行上下文</h3><div id="ctx"><div class="empty">未选择</div></div></div>
    <div class="card"><h3>待审停点</h3><div id="approvals"><div class="empty">加载中…</div></div></div>
  </div>
  <div>
    <div class="tl-card">
      <h3>执行时间线（计划=轮次序列，如实呈现）</h3>
      <div class="hint">点开任意工具调用查看载荷（候选 Diff / 校验违规）· 深色横幅为全页唯一深色块（L 版基调）</div>
      <div id="timeline"><div class="empty" style="color:#8ea3c8">左侧选择一次运行</div></div>
    </div>
  </div>
  <div>
    <div class="card"><h3>工具调用载荷</h3><div id="payload"><div class="empty">在时间线中选择一次调用</div></div></div>
    <div class="card">
      <h3>处置</h3>
      <div class="btns">
        <button class="btn warn" id="btn-cancel" disabled>取消运行</button>
        <button class="btn info" id="btn-handoff" disabled>转人工交接</button>
      </div>
      <div class="note">取消/转人工/审批决定全部经服务端既有闸与语义（本页零本地写逻辑）；403/409 原样呈现不吞。</div>
      <div class="err" id="action-err"></div>
    </div>
  </div>
</div>

<div class="statusbar">
  <span>会话 <b id="user-line">…</b></span>
  <span id="tool-line"></span>
  <span class="watermark">SYNTHETIC_PILOT · 内部工程入口</span>
</div>

<dialog id="decision-dialog">
  <h4>审批决定（复用任务中心语义）</h4>
  <div class="dkey" id="decision-subject"></div>
  <select id="decision-value">
    <option value="approve">批准</option>
    <option value="reject">驳回</option>
  </select>
  <input type="password" id="decision-password" placeholder="登录密码（确认，不落日志）" autocomplete="off">
  <textarea id="decision-reason" rows="2" placeholder="理由（可选）"></textarea>
  <div class="btns">
    <button class="btn info" id="decision-submit">提交</button>
    <button class="btn" id="decision-close" type="button">关闭</button>
  </div>
  <div class="err" id="decision-err"></div>
</dialog>

<script>
"use strict";
// 凭据交接（两段式，viewer 模式同构）：fragment 读 d= → 立即 replaceState 洗地址栏
// → 交接令牌只落 sessionStorage；首次 API 调用消费后服务端回 X-Eng-Session 会话令牌。
function clientId() {
  let id = sessionStorage.getItem("engClientId");
  if (!id) {
    // 非 secure context（纯 http 非 localhost）无 crypto.randomUUID——降级随机串
    id = (crypto.randomUUID ? crypto.randomUUID() : Date.now() + "-" + Math.random().toString(36).slice(2));
    sessionStorage.setItem("engClientId", id);
  }
  return id;
}
function handoverFromFragment() {
  const idx = location.hash.indexOf("?d=");
  if (idx < 0) return null;
  return location.hash.slice(idx + 3);
}
let HANDOVER = handoverFromFragment();
let SESSION = sessionStorage.getItem("engSessionToken") || "";
if (HANDOVER) {
  sessionStorage.setItem("engHandoverToken", HANDOVER);
  history.replaceState(null, "", location.pathname + location.search);
}
function headers() {
  const token = SESSION || sessionStorage.getItem("engHandoverToken") || "";
  return { "Authorization": "Bearer " + token, "X-Eng-Client": clientId() };
}
async function api(path, options) {
  const resp = await fetch(path, Object.assign({ headers: headers() }, options || {}));
  const issued = resp.headers.get("X-Eng-Session");
  if (issued) {
    SESSION = issued; sessionStorage.setItem("engSessionToken", issued);
    // 交接令牌一次性消费完成即废弃（评审 blind #15：过期一次性凭据不残留）
    sessionStorage.removeItem("engHandoverToken");
    HANDOVER = null;
  }
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const err = (body && body.error) || {};
    throw new Error(err.message || ("HTTP " + resp.status));
  }
  return body.data || body;
}
function esc(text) {
  const div = document.createElement("div");
  div.textContent = text == null ? "" : String(text);
  // 属性上下文加固：innerHTML 序列化不转义双引号，data-* 属性位必须补（评审 blind #12）
  return div.innerHTML.replace(/"/g, "&quot;");
}
const state = { runs: [], approvals: [], runId: null, calls: [], callId: null, detail: null };

async function loadOverview() {
  const data = await api("/api/v1/eng/overview");
  document.getElementById("user-line").textContent =
    data.user.display_name + " · " + data.user.role;
  document.getElementById("lvl-badge").textContent = data.user.role;
  document.getElementById("org-title").textContent =
    (data.org_name || "工程台") + " · 工程台";
  if (data.session_issued_at) {
    document.getElementById("tok-badge").textContent = "会话已激活";
  }
  state.runs = data.runs || [];
  state.approvals = data.approvals || [];
  renderRuns(); renderApprovals();
}
function renderRuns() {
  const host = document.getElementById("runs");
  if (!state.runs.length) { host.innerHTML = '<div class="empty">权限范围内暂无运行</div>'; return; }
  host.innerHTML = state.runs.map(r =>
    '<div class="runrow" data-id="' + esc(r.id) + '">' +
    '<div class="t">' + esc(r.agent_name || r.agent_id) + '<span class="st ' + esc(r.status) + '">' + esc(r.status) + '</span></div>' +
    '<div class="m">' + esc(r.project_name || "") + ' · ' + esc(r.created_at || "") + ' · ' + esc(r.token_cost || 0) + ' tok</div></div>'
  ).join("");
  host.querySelectorAll(".runrow").forEach(el =>
    el.addEventListener("click", () =>
      selectRun(el.getAttribute("data-id")).catch(e => {
        document.getElementById("action-err").textContent = e.message;
      })));
}
function renderApprovals() {
  const host = document.getElementById("approvals");
  if (!state.approvals.length) { host.innerHTML = '<div class="empty">无待审停点</div>'; return; }
  host.innerHTML = state.approvals.map(a =>
    '<div class="appr"><span class="pill ' + esc(a.status) + '">' + esc(a.status) + '</span>' +
    '<span>' + esc(a.task_name || a.id) + '</span>' +
    '<button class="btn info" data-approval="' + esc(a.id) + '" data-task="' + esc(a.task_name || "") + '" style="flex:0 0 auto;padding:4px 10px">决定</button></div>'
  ).join("");
  host.querySelectorAll("button[data-approval]").forEach(b =>
    b.addEventListener("click", () => openDecision(b.getAttribute("data-approval"), b.getAttribute("data-task"))));
}
async function selectRun(runId) {
  state.runId = runId;
  document.querySelectorAll(".runrow").forEach(el =>
    el.classList.toggle("sel", el.getAttribute("data-id") === runId));
  const data = await api("/api/v1/eng/runs/" + encodeURIComponent(runId));
  state.detail = data; state.calls = data.tool_calls || []; state.callId = null;
  const run = data.run || {};
  document.getElementById("ctx").innerHTML =
    '<div class="ctxline"><span>Agent</span><b>' + esc(run.agent_name || run.agent_id || "") + '</b></div>' +
    '<div class="ctxline"><span>项目</span><b>' + esc(run.project_name || "") + '</b></div>' +
    '<div class="ctxline"><span>状态</span><b>' + esc(run.status || "") + '</b></div>' +
    '<div class="ctxline"><span>能力</span><b>' + esc(run.capability_used || "") + '</b></div>' +
    '<div class="ctxline"><span>发起人</span><b>' + esc(run.initiated_by || "") + '</b></div>' +
    '<div class="ctxline"><span>降级</span><b>' + esc(run.degraded ? (run.degraded_reason || "true") : "无") + '</b></div>';
  renderTimeline();
  document.getElementById("btn-cancel").disabled = !["queued", "running", "host_running"].includes(run.status);
  document.getElementById("btn-handoff").disabled = run.status !== "completed";
}
function renderTimeline() {
  const host = document.getElementById("timeline");
  if (!state.calls.length) { host.innerHTML = '<div class="empty" style="color:#8ea3c8">该运行无工具调用留痕</div>'; return; }
  host.innerHTML = state.calls.map((c, i) => {
    const denied = c.decision !== "allowed";
    // verdict 判定走 dry_validate 三态真身（verdict 字段），不搞子串启发式
    // （评审 auditor #1："error" 子串误判 violations 为 pass / tool_failed 为 viol）
    const verdict = parseVerdict(c.response_json);
    const fail = !denied && verdict === null && hasErrorObject(c.response_json);
    const state2 = denied ? "deny" : (verdict === "violations" ? "viol" : (fail ? "deny" : "pass"));
    const label = denied ? "denied" : (verdict === "violations" ? "violations" : (fail ? "failed" : "pass"));
    return '<div class="round ' + (state2 === "pass" ? "v" : "x") + (c.id === state.callId ? ' hit' : '') + '" data-i="' + i + '">' +
      '<div class="no">' + (i + 1) + '</div>' +
      '<div class="body"><div class="tt">' + esc(c.tool_name) +
      '<span class="vt ' + state2 + '">' + label + '</span></div>' +
      '<div class="dd">' + esc(c.reason || (c.payload_truncated ? "载荷已截断" : "")) + '</div></div></div>';
  }).join("");
  host.querySelectorAll(".round").forEach(el =>
    el.addEventListener("click", () => { state.callId = state.calls[+el.getAttribute("data-i")].id; renderTimeline(); renderPayload(); }));
}
function renderPayload() {
  const host = document.getElementById("payload");
  const c = state.calls.find(x => x.id === state.callId);
  if (!c) { host.innerHTML = '<div class="empty">在时间线中选择一次调用</div>'; return; }
  let html = '<div class="dkey">工具 / 判定 / 耗时</div><div class="dcell">' +
    esc(c.tool_name) + ' · ' + esc(c.decision) + ' · ' + esc(c.duration_ms) + 'ms</div>';
  if (c.request_json) {
    html += '<div class="dkey">请求载荷' + (c.payload_truncated ? '（已截断）' : '') + '</div><div class="dcell old">' + esc(pretty(c.request_json)) + '</div>';
  }
  if (c.response_json) {
    html += '<div class="dkey">响应载荷</div><div class="dcell new">' + esc(pretty(c.response_json)) + '</div>';
    // §4-6 校验错误要素：violations 明细卡（check/item_index/message）
    const violList = parseViolations(c.response_json);
    if (violList.length) {
      html += '<div class="dkey">违规明细（服务端校验返回）</div>';
      violList.forEach(v => {
        html += '<div class="viol"><b>' + esc(v.check) + '</b> · item ' + esc(v.item_index) +
          ' · ' + esc(v.message) + '</div>';
      });
    }
  }
  if (!c.request_json && !c.response_json) {
    html += '<div class="empty">该调用无载荷留痕（存量路径）</div>';
  }
  host.innerHTML = html;
}
function parseVerdict(text) {
  try { const o = JSON.parse(text || "null"); return (o && typeof o.verdict === "string") ? o.verdict : null; }
  catch (e) { return null; }
}
function parseViolations(text) {
  try {
    const o = JSON.parse(text || "null");
    return (o && Array.isArray(o.violations)) ? o.violations : [];
  } catch (e) { return []; }
}
function hasErrorObject(text) {
  try { const o = JSON.parse(text || "null"); return !!(o && o.error); }
  catch (e) { return false; }
}
function pretty(text) {
  try { return JSON.stringify(JSON.parse(text), null, 2); } catch (e) { return text; }
}
async function doAction(path, body) {
  document.getElementById("action-err").textContent = "";
  try {
    await api(path, Object.assign({ method: "POST" }, body ? { headers: Object.assign(headers(), { "Content-Type": "application/json" }), body: JSON.stringify(body) } : {}));
    await refresh();
  } catch (e) { document.getElementById("action-err").textContent = e.message; }
}
function openDecision(approvalId, taskName) {
  const dlg = document.getElementById("decision-dialog");
  currentApprovalId = approvalId;
  document.getElementById("decision-subject").textContent = "待审项：" + (taskName || approvalId);
  document.getElementById("decision-err").textContent = "";
  dlg.showModal();
}
let currentApprovalId = null;
document.getElementById("decision-close").addEventListener("click", () =>
  document.getElementById("decision-dialog").close());
document.getElementById("decision-submit").addEventListener("click", async () => {
  const dlg = document.getElementById("decision-dialog");
  const id = currentApprovalId;
  if (!id) { document.getElementById("decision-err").textContent = "未选中待审项。"; return; }
  try {
    await api("/api/v1/eng/approvals/" + encodeURIComponent(id) + "/decision", {
      method: "POST",
      headers: Object.assign(headers(), { "Content-Type": "application/json" }),
      body: JSON.stringify({
        decision: document.getElementById("decision-value").value,
        password: document.getElementById("decision-password").value,
        reason: document.getElementById("decision-reason").value,
      }),
    });
    document.getElementById("decision-password").value = "";
    document.getElementById("decision-reason").value = "";
    dlg.close();
    await refresh();
  } catch (e) { document.getElementById("decision-err").textContent = e.message; }
});
document.getElementById("btn-cancel").addEventListener("click", () => {
  if (state.runId && confirm("确认取消该运行？（幂等；运行态将经服务端收口）"))
    doAction("/api/v1/eng/runs/" + encodeURIComponent(state.runId) + "/cancel");
});
document.getElementById("btn-handoff").addEventListener("click", () => {
  if (state.runId && confirm("确认转人工交接？（挂 pending signoff 终审检查点）"))
    doAction("/api/v1/eng/runs/" + encodeURIComponent(state.runId) + "/handoff", {});
});
async function refresh() {
  await loadOverview();
  if (state.runId) { try { await selectRun(state.runId); } catch (e) { state.runId = null; renderTimeline(); } }
}
document.getElementById("btn-logout").addEventListener("click", async () => {
  if (!confirm("确认登出？当前会话与其出链链接将同时吊销。")) return;
  try { await api("/api/v1/eng/logout", { method: "POST" }); } catch (e) { /* 吊销失败也不保留本地凭据 */ }
  sessionStorage.removeItem("engSessionToken");
  sessionStorage.removeItem("engHandoverToken");
  SESSION = ""; HANDOVER = null;
  location.reload();
});
async function boot() {
  try { await loadOverview(); }
  catch (e) {
    document.getElementById("runs").innerHTML =
      '<div class="empty">' + esc(e.message) + '</div>';
  }
}
boot();
</script>
</body>
</html>
"""
