// 小工具：POST 表单 → toast/刷新。所有写操作按钮均经此（人工点击 = 审批动作）。
async function post(url, data, opts = {}) {
  const body = new FormData();
  Object.entries(data || {}).forEach(([k, v]) => body.append(k, v));
  const btn = opts.btn;
  if (btn) { btn.disabled = true; btn.dataset.t = btn.textContent; btn.textContent = "…"; }
  try {
    const resp = await fetch(url, { method: "POST", body });
    const isJson = (resp.headers.get("content-type") || "").includes("json");
    const out = isJson ? await resp.json() : null;
    if (!resp.ok) throw new Error((out && out.error) || resp.statusText);
    if (out && out.task) {                 // 后台任务：托盘接管，完成才刷新（切页不丢）
      toast("⏳ " + (out.label || "任务") + " 进行中——右下角看进度");
      pollTasks();
      return out;
    }
    if (!opts.quiet) toast(opts.ok || "完成");
    if (opts.reload) setTimeout(() => location.reload(), 500);
    if (opts.then) opts.then(out);
    return out;
  } catch (e) {
    toast("失败：" + e.message);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = btn.dataset.t; }
  }
}
// 双层雷达（参谋部画像 / 公司页匹配共用）：items = [{name, market, self}]，0-5 分制
function drawRadar(svg, items) {
  const vb = svg.viewBox.baseVal, cx = vb.width / 2, cy = vb.height / 2 + 2;
  const R = Math.min(cx, cy) - 58, n = items.length;
  if (!n) return;
  // JD 要求强的轴排前、顶部起顺时针——形状更规整，最重要的轴在 12 点
  items = items.slice().sort((a, b) => (b.market || 0) - (a.market || 0) || (b.self || 0) - (a.self || 0));
  const css = k => getComputedStyle(document.documentElement).getPropertyValue(k).trim();
  const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
  const pt = (i, v) => { const a = -Math.PI / 2 + i * 2 * Math.PI / n;
    return [cx + Math.cos(a) * R * v / 5, cy + Math.sin(a) * R * v / 5]; };
  // 折行：CJK 记 2 单位、拉丁 1 单位，每行 ~22 单位，最多 2 行，溢出加 …
  const wrap = name => {
    const w = ch => (ch.codePointAt(0) > 0x2E7F ? 2 : 1);
    const words = /[⺀-鿿]/.test(name) ? [...name] : name.split(/\s+/);
    const sep = /[⺀-鿿]/.test(name) ? '' : ' ';
    const lines = ['']; let len = 0;
    for (const word of words) {
      const wl = [...word].reduce((s, c) => s + w(c), 0) + (len ? sep.length : 0);
      if (len + wl > 22 && len) {
        if (lines.length === 2) { lines[1] += '…'; return lines; }
        lines.push(word); len = wl;
      } else { lines[lines.length - 1] += (len ? sep : '') + word; len += wl; }
    }
    return lines;
  };
  let g = '';
  for (let ring = 1; ring <= 5; ring++)
    g += `<polygon points="${items.map((_, i) => pt(i, ring).join(',')).join(' ')}" fill="none" stroke="${css('--line')}" stroke-width="${ring === 5 ? 1.4 : 1}"/>`;
  items.forEach((_, i) => {
    const [x, y] = pt(i, 5);
    g += `<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" stroke="${css('--line')}"/>`;
  });
  const poly = (key, fill, stroke, dash) =>
    `<polygon points="${items.map((d, i) => pt(i, d[key] || 0).join(',')).join(' ')}" fill="${fill}" stroke="${stroke}" stroke-width="2" ${dash ? 'stroke-dasharray="5 4"' : ''}/>`;
  g += poly('market', 'none', css('--ink-3'), true);
  g += poly('self', css('--accent') + '33', css('--accent'), false);
  items.forEach((d, i) => {                 // 顶点：JD 要求 ○ 空心，我 ● 实心——两形贴近时仍可分
    const [mx, my] = pt(i, d.market || 0), [sx, sy] = pt(i, d.self || 0);
    g += `<circle cx="${mx}" cy="${my}" r="3" fill="${css('--surface')}" stroke="${css('--ink-3')}" stroke-width="1.4"/>`;
    g += `<circle cx="${sx}" cy="${sy}" r="3" fill="${css('--accent')}"/>`;
  });
  items.forEach((d, i) => {
    const a = -Math.PI / 2 + i * 2 * Math.PI / n;
    const [lx, ly] = pt(i, 5).map((v, k) => k ? v + Math.sin(a) * 12 : v + Math.cos(a) * 12);
    const anchor = Math.abs(Math.cos(a)) < .35 ? 'middle' : (Math.cos(a) > 0 ? 'start' : 'end');
    const lines = wrap(d.name);
    const gap = (d.market || 0) - (d.self || 0);
    const vcol = gap >= 2 ? css('--red') : gap === 1 ? css('--amber') : css('--accent-ink');
    const above = Math.sin(a) < -.35, rows = lines.length + 1;   // 值行也算一行
    const y0 = ly + (above ? -(rows - 1) * 12 : Math.abs(Math.sin(a)) < .35 ? -(rows - 1) * 6 : 0);
    let t = `<g><title>${esc(d.name)}${d.basis ? '\n' + esc(d.basis) : ''}</title>`;
    lines.forEach((s, r) => {
      t += `<text x="${lx}" y="${y0 + r * 12}" text-anchor="${anchor}" dominant-baseline="middle" font-size="10.5" fill="${css('--ink-2')}">${esc(s)}</text>`;
    });
    t += `<text x="${lx}" y="${y0 + lines.length * 12}" text-anchor="${anchor}" dominant-baseline="middle" font-size="10.5" font-weight="600" fill="${vcol}">${d.market || 0} → ${d.self || 0}</text></g>`;
    g += t;
  });
  svg.innerHTML = g;
}
function toast(msg) {
  let el = document.querySelector(".toast");
  if (!el) { el = document.createElement("div"); el.className = "toast"; document.body.appendChild(el); }
  el.textContent = msg; el.classList.add("on");
  setTimeout(() => el.classList.remove("on"), 2600);
}

// 后台任务托盘：长 LLM 作业（简历/brief/画像/扫描）跨页面可见，完成即提醒并刷新。
let _trayTimer = null;
const _seenRunning = new Set();
const _dismissed = new Set();        // 手动关掉的卡
const _doneSeen = new Map();         // 完成卡首次可见时刻 → 成功卡 8s 自动退场
const DONE_TTL = 8000;
function _fmtSecs(s){ return s >= 60 ? `${Math.floor(s/60)}m${String(s%60).padStart(2,'0')}s` : `${s}s`; }
function _dismissServer(id){
  const fd = new FormData(); fd.append('id', id);
  fetch('/api/tasks/dismiss', {method:'POST', body:fd});   // 服务端销单：切页不还魂
}
function dismissTask(id){
  _dismissed.add(id);                          // 本地即时消失
  _dismissServer(id);
  pollTasks();
}
async function pollTasks(){
  let ts = [];
  try { ts = await (await fetch('/api/tasks')).json(); } catch(e){ return; }
  const now = Date.now();
  const vis = ts.filter(t=>{
    if (_dismissed.has(t.id)) return false;
    if (t.status === 'running') return true;
    if (!_doneSeen.has(t.id)) _doneSeen.set(t.id, now);
    if (t.status === 'done' && now - _doneSeen.get(t.id) > DONE_TTL){
      _dismissed.add(t.id);            // 成功卡到点自动销单（服务端同删）；失败卡留驻手动关
      _dismissServer(t.id);
      return false;
    }
    return true;
  });
  const el = document.getElementById('tasktray');
  if (el) {
    const run = vis.filter(t=>t.status==='running');
    const done = vis.filter(t=>t.status!=='running').slice(0,3);
    el.innerHTML =
      run.map(t=>`<div class="task run"><span class="spin"></span><span class="tl">${t.label}</span><span class="ts">${_fmtSecs(t.secs)}</span><i class="bar"></i></div>`).join('') +
      done.map(t=>`<div class="task ${t.status==='done'?'fade':''}"><span class="${t.status==='done'?'okk':'errk'}">${t.status==='done'?'✓':'✗'}</span><span class="tl" ${t.error?`title="${t.error.replace(/"/g,'&quot;')}"`:''}>${t.label}${t.error?'：'+t.error.slice(0,60):''}</span><a class="tx" href="#" onclick="dismissTask('${t.id}');return false" title="关闭">✕</a></div>`).join('');
  }
  let hasRunning = false;
  ts.forEach(t=>{
    if (t.status === 'running'){ _seenRunning.add(t.id); hasRunning = true; }
    else if (_seenRunning.has(t.id)){
      _seenRunning.delete(t.id);
      if (t.status === 'done'){ toast('✓ ' + t.label + ' 完成'); setTimeout(()=>location.reload(), 700); }
      else toast('✗ ' + t.label + ' 失败：' + (t.error || '').slice(0, 120));
    }
  });
  clearTimeout(_trayTimer);
  if (hasRunning) _trayTimer = setTimeout(pollTasks, 2000);
  else if (vis.some(t=>t.status==='done')) _trayTimer = setTimeout(pollTasks, DONE_TTL + 500);
}
addEventListener('DOMContentLoaded', pollTasks);   // 切页回来自动恢复进行中状态
addEventListener('pageshow', e => {                // 后退命中 bfcache = 冻结的旧页面——强制取新
  if (e.persisted) location.reload();
});

function initBackTop(){
  const btn = document.getElementById('backtop');
  if (!btn) return;
  const onScroll = () => btn.classList.toggle('show', window.scrollY > 320);
  addEventListener('scroll', onScroll, {passive: true});
  onScroll();
  btn.addEventListener('click', () => {
    btn.classList.remove('land'); void btn.offsetWidth; btn.classList.add('land');
    window.scrollTo({top: 0, behavior: 'smooth'});
  });
}
addEventListener('DOMContentLoaded', initBackTop);
