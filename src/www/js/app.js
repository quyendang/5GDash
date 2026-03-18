'use strict';
/* ── 5GDash — vanilla JS, no dependencies ──────────────────────────────── */

const API = '';

// ── Helpers ────────────────────────────────────────────────────────────────

const $  = id  => document.getElementById(id);
const qs = sel => document.querySelector(sel);
const qsa= sel => document.querySelectorAll(sel);

function set(id, val) {
  const el = $(id);
  if (el && val != null) el.textContent = val;
}

function fmt(n, dec = 1) {
  if (n == null || isNaN(n)) return '--';
  return Number(n).toFixed(dec);
}

function fmtBytes(b) {
  if (b == null || b === 0) return '0 B';
  const u = ['B','KB','MB','GB','TB'];
  let i = 0;
  while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
  return `${b.toFixed(i ? 1 : 0)} ${u[i]}`;
}

function fmtSpeed(bps) {
  if (!bps || bps < 0) return { val: '0.0', unit: 'Kbps' };
  const k = bps / 1000;
  if (k < 1000)  return { val: k.toFixed(1),          unit: 'Kbps' };
  if (k < 1e6)   return { val: (k/1000).toFixed(2),   unit: 'Mbps' };
  return           { val: (k/1e6).toFixed(2),          unit: 'Gbps' };
}

function fmtUptime(s) {
  if (!s) return '--';
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600)  / 60);
  if (d > 0) return `${d}d ${h}h ${m}m`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function fmtConn(secs) {
  if (secs == null) return '';
  if (secs < 60)    return `${secs}s`;
  if (secs < 3600)  return `${Math.floor(secs/60)}m`;
  return `${Math.floor(secs/3600)}h ${Math.floor((secs%3600)/60)}m`;
}

function escHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function toast(msg, type = '') {
  const el = $('toast');
  el.textContent = msg;
  el.className = `toast show ${type}`;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.remove('show'), 3000);
}

async function post(path, body) {
  const r = await fetch(API + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return r.json();
}

// ── Signal quality ─────────────────────────────────────────────────────────
// Thresholds in real dBm (backend now returns correct values, no ÷10 issue)

const QUAL = {
  rsrp: [[-80,'Xuất sắc','excellent'],[-90,'Tốt','good'],[-100,'Khá','fair'],[-Infinity,'Yếu','poor']],
  rsrq: [[-10,'Xuất sắc','excellent'],[-15,'Tốt','good'],[-20,'Khá','fair'],[-Infinity,'Yếu','poor']],
  sinr: [[20,'Xuất sắc','excellent'],[10,'Tốt','good'],[0,'Khá','fair'],[-Infinity,'Yếu','poor']],
};

const CLASS_MAP = {
  excellent: 'q-excellent', good: 'q-good', fair: 'q-fair', poor: 'q-poor',
};

function getQual(val, levels) {
  if (val == null) return null;
  for (const [thr, label, key] of levels) {
    if (val >= thr) return { label, cls: CLASS_MAP[key] };
  }
  return null;
}

function setQualBadge(id, val, levels) {
  const el = $(id);
  if (!el) return;
  const q = getQual(val, levels);
  if (q) {
    el.textContent = q.label;
    el.className = `qual-badge ${q.cls}`;
  } else {
    el.textContent = '';
    el.className = 'qual-badge';
  }
}

// RSRP → 0-100% for bar
function rsrpPct(v) { return v == null ? 0 : Math.min(100, Math.max(0, (v - (-140)) / 96 * 100)); }
function rsrqPct(v) { return v == null ? 0 : Math.min(100, Math.max(0, (v - (-20)) / 17 * 100)); }
function sinrPct(v) { return v == null ? 0 : Math.min(100, Math.max(0, (v - (-20)) / 50 * 100)); }

function rsrpLevel(rsrp) {
  if (rsrp == null) return 0;
  if (rsrp >= -80)  return 5;
  if (rsrp >= -90)  return 4;
  if (rsrp >= -100) return 3;
  if (rsrp >= -110) return 2;
  return 1;
}

// ── Progress bar helper ────────────────────────────────────────────────────

function setBar(barId, pct) {
  const el = $(barId);
  if (el) el.style.width = Math.min(100, Math.max(0, pct)) + '%';
}

// ── Traffic chart (SVG) ────────────────────────────────────────────────────

const N = 60;
const dlHist = new Array(N).fill(0);
const ulHist = new Array(N).fill(0);

function pushSpeed(dl, ul) {
  dlHist.push(dl); dlHist.shift();
  ulHist.push(ul); ulHist.shift();
}

function buildLine(data, maxVal, W, H) {
  if (maxVal <= 0) return '';
  return data.map((v, i) => {
    const x = (i / (N - 1)) * W;
    const y = H - (v / maxVal) * H * 0.9 + 2;
    return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
}

function buildFill(data, maxVal, W, H) {
  if (maxVal <= 0) return '';
  const line = buildLine(data, maxVal, W, H);
  return `${line} L${W},${H} L0,${H} Z`;
}

function drawChart() {
  const W = 300, H = 70;
  const maxVal = Math.max(1, ...dlHist, ...ulHist);
  $('line-dl').setAttribute('d', buildLine(dlHist, maxVal, W, H));
  $('line-ul').setAttribute('d', buildLine(ulHist, maxVal, W, H));
  $('fill-dl').setAttribute('d', buildFill(dlHist, maxVal, W, H));
  $('fill-ul').setAttribute('d', buildFill(ulHist, maxVal, W, H));
}

// ── Band chips ─────────────────────────────────────────────────────────────

let LTE_LIST  = ['B1','B2','B3','B4','B5','B7','B8','B12','B13',
                 'B17','B18','B19','B20','B25','B26','B28','B38','B39','B40','B41','B42'];
let NR5G_LIST = ['N1','N2','N3','N5','N7','N8','N12','N20',
                 'N25','N28','N38','N40','N41','N48','N77','N78','N79'];

let selLTE  = new Set();
let selNR5G = new Set();
let curLTE  = new Set();
let curNR5G = new Set();

// Load band list from server (may include more bands than defaults)
fetch(API + '/api/bands').then(r => r.json()).then(d => {
  if (d.lte_bands  && d.lte_bands.length)  LTE_LIST  = d.lte_bands;
  if (d.nr5g_bands && d.nr5g_bands.length) NR5G_LIST = d.nr5g_bands;
  buildChips();
}).catch(() => buildChips());

function buildChips() {
  buildChipGroup('lte-chips',  LTE_LIST,  selLTE,  curLTE);
  buildChipGroup('nr5g-chips', NR5G_LIST, selNR5G, curNR5G);
}

function buildChipGroup(containerId, list, sel, cur) {
  const wrap = $(containerId);
  wrap.innerHTML = '';
  list.forEach(b => {
    const el = document.createElement('button');
    el.className   = 'chip';
    el.textContent = b;
    el.dataset.band = b;
    if (sel.has(b)) el.classList.add('selected');
    if (cur.has(b)) el.classList.add('current');
    el.onclick = () => {
      el.classList.toggle('selected');
      if (el.classList.contains('selected')) sel.add(b);
      else sel.delete(b);
    };
    wrap.appendChild(el);
  });
}

function syncCurrentChips() {
  qsa('#lte-chips .chip').forEach(el => {
    el.classList.toggle('current', curLTE.has(el.dataset.band));
  });
  qsa('#nr5g-chips .chip').forEach(el => {
    el.classList.toggle('current', curNR5G.has(el.dataset.band));
  });
}

buildChips();

// ── Band lock actions ──────────────────────────────────────────────────────

$('btn-apply-bands').onclick = async () => {
  const lte  = [...selLTE];
  const nr5g = [...selNR5G];
  if (!lte.length && !nr5g.length) {
    toast('Hãy chọn ít nhất 1 băng tần', 'error'); return;
  }
  toast('Đang áp dụng...');
  try {
    const r = await post('/api/band-lock', { lte, nr5g });
    if (r.ok) toast(`Đã khóa: ${[...lte,...nr5g].join(', ')}`, 'success');
    else toast('Lỗi khi khóa băng tần', 'error');
  } catch { toast('Không kết nối được server', 'error'); }
};

$('btn-unlock-bands').onclick = async () => {
  selLTE.clear(); selNR5G.clear();
  buildChips();
  try {
    const r = await post('/api/band-lock', { lte: [], nr5g: [] });
    if (r.ok) toast('Đã bỏ khóa tất cả băng tần', 'success');
  } catch { toast('Lỗi kết nối', 'error'); }
};

qsa('.mode-btn').forEach(btn => {
  btn.onclick = async () => {
    toast('Đang thay đổi chế độ...');
    try {
      const r = await post('/api/network-mode', { mode: btn.dataset.mode });
      if (r.ok) {
        qsa('.mode-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        toast('Đã cập nhật chế độ mạng', 'success');
      }
    } catch { toast('Lỗi kết nối', 'error'); }
  };
});

$('btn-reset-traffic').onclick = async () => {
  try {
    await post('/api/traffic-reset', {});
    toast('Đã reset bộ đếm traffic', 'success');
  } catch { toast('Lỗi kết nối', 'error'); }
};

$('btn-reconnect').onclick = async () => {
  toast('Đang kết nối lại...');
  try {
    const r = await post('/api/reconnect', {});
    if (r.ok) toast('Đã gửi lệnh kết nối lại', 'success');
  } catch { toast('Lỗi kết nối', 'error'); }
};

// ── Connected devices ──────────────────────────────────────────────────────

const DEVICE_ICON_WIFI = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
  <rect x="5" y="2" width="14" height="20" rx="2"/>
  <line x1="12" y1="18" x2="12" y2="18" stroke-width="3"/>
</svg>`;

const DEVICE_ICON_LAN = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
  <rect x="2" y="3" width="20" height="14" rx="2"/>
  <path d="M8 21h8M12 17v4"/>
</svg>`;

function signalCls(dbm) {
  if (dbm == null) return '';
  if (dbm >= -65)  return 'good';
  if (dbm >= -75)  return 'fair';
  return 'poor';
}

function renderClients(list) {
  const wrap = $('client-list');
  const total = list.length;
  set('client-count',  total);
  set('client-count2', total);

  if (!total) {
    wrap.innerHTML = '<div class="client-empty">Không có thiết bị nào</div>';
    return;
  }

  wrap.innerHTML = list.map(d => {
    const isWifi = d.type === 'wifi';
    const iconCls = isWifi ? 'wifi' : 'lan';
    const icon    = isWifi ? DEVICE_ICON_WIFI : DEVICE_ICON_LAN;

    const sigHtml = isWifi && d.signal != null
      ? `<span class="dot">•</span><span class="client-signal ${signalCls(d.signal)}">${escHtml(String(d.signal))} dBm</span>`
      : '';

    const traffic = (d.rx_bytes || d.tx_bytes)
      ? `↓ ${fmtBytes(d.rx_bytes)}  ↑ ${fmtBytes(d.tx_bytes)}`
      : '--';

    const connTime = d.connected_secs != null ? fmtConn(d.connected_secs) : '';

    return `
    <div class="client-item">
      <div class="client-main">
        <div class="client-avatar ${iconCls}">${icon}</div>
        <div class="client-info">
          <div class="client-name">${escHtml(d.hostname || 'Unknown')}</div>
          <div class="client-meta">
            <span>${escHtml(d.ip || '--')}</span>
            <span class="dot">•</span><span>${escHtml(d.band || '--')}</span>
            ${sigHtml}
          </div>
        </div>
      </div>
      <div class="client-footer">
        <span class="client-traffic">${traffic}</span>
        <span class="client-time">${connTime}</span>
      </div>
    </div>`;
  }).join('');
}

async function loadClients() {
  try {
    const list = await fetch(API + '/api/devices').then(r => r.json());
    renderClients(list);
  } catch {
    $('client-list').innerHTML = '<div class="client-empty">Không thể tải danh sách</div>';
  }
}

$('btn-refresh-clients').onclick = () => {
  $('client-list').innerHTML = '<div class="client-empty">Đang tải...</div>';
  loadClients();
};

$('btn-clients-toggle').onclick = () => {
  const card = $('card-clients');
  card.scrollIntoView({ behavior: 'smooth', block: 'start' });
  loadClients();
};

// Load clients initially and every 15s
loadClients();
setInterval(loadClients, 15000);

// ── Load device/modem info (once) ─────────────────────────────────────────

async function loadModemInfo() {
  try {
    const d = await fetch(API + '/api/device').then(r => r.json());
    if (d.model)    set('m-model', d.model);
    if (d.firmware) set('m-fw',    d.firmware);
    if (d.imei)     set('m-imei',  d.imei);
    if (d.iccid)    set('m-iccid', d.iccid);
  } catch {}
}
loadModemInfo();

// ── Main data update ───────────────────────────────────────────────────────

function applyData(data) {
  if (!data) return;

  $('conn-dot').className = 'status-dot live';

  // ── sysinfo
  const sys = data.sysinfo || {};
  set('sys-hostname', sys.hostname || '5G CPE');
  set('sys-uptime',   fmtUptime(sys.uptime_secs));
  set('cpu-pct',      sys.cpu_pct != null ? `${sys.cpu_pct}%` : '--%');
  setBar('cpu-bar',   sys.cpu_pct || 0);
  if (sys.ram_total) {
    set('ram-val', `${fmtBytes(sys.ram_used)} / ${fmtBytes(sys.ram_total)}`);
    setBar('ram-bar', sys.ram_pct || 0);
  }
  if (sys.rom_total) {
    set('rom-val', `${fmtBytes(sys.rom_used)} / ${fmtBytes(sys.rom_total)}`);
    setBar('rom-bar', sys.rom_pct || 0);
  }

  // ── temperature
  const temps = data.temps || {};
  const tempVals = Object.values(temps);
  if (tempVals.length) {
    const maxT = Math.max(...tempVals);
    set('sys-temp', `${maxT.toFixed(1)}°C`);
    set('m-temp',   `${maxT.toFixed(1)}°C`);
  }

  // ── traffic total
  const traffic = data.traffic || {};
  const totalBytes = (traffic.rx_bytes || 0) + (traffic.tx_bytes || 0);
  set('sys-data', fmtBytes(totalBytes));

  // ── signal & cell
  const cell   = data.cell   || {};
  const nr5g   = data.nr5g   || {};
  const sig    = data.signal || {};
  const op     = data.operator || {};
  const nm     = data.net_mode || {};

  const rsrp = sig.rsrp ?? cell.rsrp;
  const rsrq = sig.rsrq ?? cell.rsrq;
  const sinr = sig.sinr ?? cell.sinr;

  // Signal bars
  $('sig-bars').dataset.lv = rsrpLevel(rsrp);

  // Heading: band combo
  const mainBand = cell.band || '--';
  const nrBand   = nr5g.band || '';
  set('sig-heading', nrBand ? `${mainBand} + ${nrBand}` : mainBand);

  // Tags
  const modeText = cell.mode || '--';
  set('tag-mode', modeText);
  set('tag-band', nrBand ? `${mainBand} + ${nrBand}` : mainBand);
  set('tag-op',   op.operator || '--');

  // Badge in topbar card
  set('badge-netmode', nm.name || modeText);

  // RSRP bar + label
  set('val-rsrp', rsrp != null ? fmt(rsrp, 0) : '--');
  setBar('bar-rsrp', rsrpPct(rsrp));
  setQualBadge('qual-rsrp', rsrp, QUAL.rsrp);

  set('val-rsrq', rsrq != null ? fmt(rsrq, 1) : '--');
  setBar('bar-rsrq', rsrqPct(rsrq));
  setQualBadge('qual-rsrq', rsrq, QUAL.rsrq);

  set('val-sinr', sinr != null ? fmt(sinr, 1) : '--');
  setBar('bar-sinr', sinrPct(sinr));
  setQualBadge('qual-sinr', sinr, QUAL.sinr);

  // Detail info grid
  set('v-op',    op.operator || '--');
  set('v-cell',  cell.cell_id || '--');
  set('v-pci',   cell.pci || '--');
  set('v-arfcn', cell.dl_arfcn || '--');
  set('v-mcc',   (cell.mcc && cell.mnc) ? `${cell.mcc} / ${cell.mnc}` : '--');
  set('v-state', cell.state || '--');

  // CA chips
  const caRow = $('ca-row');
  caRow.innerHTML = '';
  if (data.ca && data.ca.length) {
    data.ca.forEach(c => {
      const chip = document.createElement('div');
      chip.className = `ca-chip ${c.role === 'PCC' ? 'pcc' : ''}`;
      chip.textContent = `${c.role}: ${c.band}`;
      caRow.appendChild(chip);
    });
  }

  // ── speed + chart
  const speed = data.speed || {};
  const dl = fmtSpeed(speed.rx_bps || 0);
  const ul = fmtSpeed(speed.tx_bps || 0);
  set('speed-dl', dl.val); set('unit-dl', dl.unit);
  set('speed-ul', ul.val); set('unit-ul', ul.unit);

  // DL speed color
  const sdl = $('speed-dl');
  if (sdl) sdl.style.color = '#3b7adb';
  const sul = $('speed-ul');
  if (sul) sul.style.color = '#7c3aed';

  set('total-dl', `↓ ${fmtBytes(traffic.rx_bytes)}`);
  set('total-ul', `↑ ${fmtBytes(traffic.tx_bytes)}`);

  pushSpeed(speed.rx_bps || 0, speed.tx_bps || 0);
  drawChart();

  // ── band lock state
  const bands = data.bands || {};
  curLTE  = new Set(bands.lte_locked  || []);
  curNR5G = new Set(bands.nr5g_locked || []);
  syncCurrentChips();

  const locked = curLTE.size > 0 || curNR5G.size > 0;
  const lb = $('lock-badge');
  if (lb) {
    lb.textContent = locked ? [...curLTE,...curNR5G].join(', ') : 'Auto';
    lb.classList.toggle('locked', locked);
  }
}

// ── SSE ───────────────────────────────────────────────────────────────────

let _reconnDelay = 1000;

function connectSSE() {
  const es = new EventSource(API + '/api/stream');

  es.onmessage = e => {
    _reconnDelay = 1000;
    try { applyData(JSON.parse(e.data)); } catch {}
  };

  es.onerror = () => {
    es.close();
    $('conn-dot').className = 'status-dot error';
    setTimeout(connectSSE, _reconnDelay);
    _reconnDelay = Math.min(_reconnDelay * 2, 30000);
  };
}

function startPolling() {
  (async function poll() {
    try {
      const d = await fetch(API + '/api/status').then(r => r.json());
      applyData(d);
      $('conn-dot').className = 'status-dot live';
    } catch {
      $('conn-dot').className = 'status-dot error';
    }
    setTimeout(poll, 5000);
  })();
}

if (typeof EventSource !== 'undefined') connectSSE();
else startPolling();
