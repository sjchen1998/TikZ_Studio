const $ = id => document.getElementById(id);
let pts = [], ports = [], W = 0, H = 0, cal = null, activeIdx = -1, multiSet = new Set(), lastGood = '', history = [];
let place = null, placeHover = null;

function insText() { startPlace('text'); }
function insComp(k) { startPlace(k); }
const LIB_STORE = 'tikzStudioLib', LIB_VER = 3;
let panel = 'circuit', libs = {};
function slot() { return libs[panel]; }
function installCustom(c, which) {
  const n = c.n === 0 ? 0 : (c.n === 1 ? 1 : 2);
  PLACE[c.id] = { name: c.name, btn: c.name, n, field: c.field || '', def: c.def || '', panel: which, custom: true, build: (p, a, rot) => fillTpl(c.tpl, p, a, rot) };
}
function defaultKeys(name) { return visibleCommon(name).concat(PANELS[name].lib); }
function saveLib() {
  const out = { v: LIB_VER };
  Object.keys(PANELS).forEach(name => { out[name] = { keys: libs[name].keys, custom: libs[name].custom }; });
  localStorage.setItem(LIB_STORE, JSON.stringify(out));
}
function loadLib() {
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(LIB_STORE) || 'null') || {}; } catch { saved = {}; }
  if (Array.isArray(saved.keys)) saved = { circuit: saved };
  const migrated = (saved.v || 0) < LIB_VER;
  Object.keys(PANELS).forEach(name => {
    const raw = saved[name] || {};
    const custom = Array.isArray(raw.custom) ? raw.custom.filter(c => c && c.id && c.tpl && c.name) : [];
    custom.forEach(c => installCustom(c, name));
    let keys = Array.isArray(raw.keys) ? raw.keys.filter(k => inPanel(k, name)) : defaultKeys(name);
    if (migrated && Array.isArray(raw.keys)) visibleCommon(name).slice().reverse().forEach(k => { if (!keys.includes(k)) keys.unshift(k); });
    libs[name] = { keys, custom };
  });
  if (migrated) saveLib();
}
function renderBar() {
  const bar = $('cbar'), specP = PANELS[panel]; bar.innerHTML = '';
  const tag = document.createElement('span'); tag.className = 'panel-tag'; tag.textContent = specP.title; bar.appendChild(tag);
  specP.core.concat(FIXED).forEach(k => {
    const spec = PLACE[k]; if (!spec) return;
    const b = document.createElement('button');
    b.className = 'comp'; b.type = 'button'; b.textContent = spec.btn || spec.name;
    b.onclick = () => insComp(k); bar.appendChild(b);
  });
  slot().keys.forEach(k => {
    const spec = PLACE[k]; if (!spec) return;
    const wrap = document.createElement('span'); wrap.className = 'libitem';
    const b = document.createElement('button');
    b.className = 'comp lib'; b.type = 'button'; b.textContent = spec.btn || spec.name;
    b.onclick = () => insComp(k);
    const x = document.createElement('button');
    x.className = 'libx'; x.type = 'button'; x.title = '从面板移除'; x.textContent = '×';
    x.onclick = e => { e.preventDefault(); e.stopPropagation(); removeLib(k); };
    wrap.appendChild(b); wrap.appendChild(x); bar.appendChild(wrap);
  });
  const add = document.createElement('button');
  add.className = 'comp lib add'; add.type = 'button'; add.textContent = '＋'; add.title = '添加本面板的元件';
  add.onclick = () => { const box = $('libbox'); box.style.display = box.style.display === 'block' ? 'none' : 'block'; if (box.style.display === 'block') fillLibPick(); };
  bar.appendChild(add);
}
function syncPanel(code) {
  const next = pictureKind(code);
  if (!next || next === panel) return;
  if (place) endPlace();
  $('libbox').style.display = 'none';
  panel = next; renderBar();
}
function fillLibPick() {
  const sel = $('lib-pick'), have = new Set(slot().keys);
  const keys = Object.keys(PLACE).filter(k => inPanel(k, panel) && !have.has(k));
  sel.innerHTML = keys.length ? keys.map(k => `<option value="${k}">${PLACE[k].btn || PLACE[k].name} · ${PLACE[k].n ? PLACE[k].n + '点' : '不取点'}</option>`).join('') : '<option value="">库中的都已在面板上</option>';
}
function addLibKey(k) {
  if (!inPanel(k, panel) || slot().keys.includes(k)) return;
  slot().keys.push(k); saveLib(); renderBar(); fillLibPick();
}
function removeLib(k) {
  if (place && place.key === k) endPlace();
  slot().keys = slot().keys.filter(x => x !== k);
  if (PLACE[k] && PLACE[k].custom) { delete PLACE[k]; slot().custom = slot().custom.filter(c => c.id !== k); }
  saveLib(); renderBar(); if ($('libbox').style.display === 'block') fillLibPick();
}
function addCustomLib() {
  const name = $('lib-name').value.trim(), tpl = $('lib-tpl').value.trim();
  const n = $('lib-n').value === '0' ? 0 : ($('lib-n').value === '1' ? 1 : 2), field = $('lib-field').value, def = $('lib-def').value;
  if (!name || !tpl || (n >= 1 && !tpl.includes('{{1}}')) || (n === 2 && !tpl.includes('{{2}}'))) { $('lib-msg').textContent = n ? '需要按钮名，以及模板里的 {{1}}' + (n === 2 ? ' 和 {{2}}' : '') : '需要按钮名和模板'; return; }
  const c = { id: 'c' + Date.now().toString(36), name, n, field, def, tpl };
  slot().custom.push(c); installCustom(c, panel); slot().keys.push(c.id); saveLib(); renderBar(); fillLibPick();
  $('lib-name').value = ''; $('lib-tpl').value = ''; $('lib-msg').textContent = '已添加到' + PANELS[panel].title;
}
function pointShown(p) {
  if (p.wx == null) return false;
  if (p.kind === 'abs' || p.kind === 'xyz') return $('sh-r').checked;
  if (p.kind === 'lerp' || p.kind === 'mid') return $('sh-p').checked;
  return $('sh-b').checked;
}
function mapVec(c, x, y, inv) {
  const ops = c.xf || [], seq = inv ? ops.slice().reverse() : ops;
  for (const op of seq) {
    if (op[0] === 'r') {
      const a = (inv ? -op[1] : op[1]) * Math.PI / 180, cs = Math.cos(a), sn = Math.sin(a);
      const nx = cs * x - sn * y, ny = sn * x + cs * y;
      x = nx; y = ny;
    } else if (op[0] === 's') {
      const sx = op[1] || 1, sy = op[2] || 1;
      if (inv) { x /= sx; y /= sy; } else { x *= sx; y *= sy; }
    }
  }
  return [x, y];
}
function fmtNum(n, u) { return `${+Number(n).toFixed(u ? 4 : 3)}${u || ''}`; }
function planDrag(c, dwx, dwy, sn) {
  const snap = v => sn > 0 ? Math.round(v / sn) * sn : v;
  const mouseWx = c.wx + dwx, mouseWy = c.wy + dwy;
  const [dlx, dly] = mapVec(c, dwx, dwy, true);
  if (c.kind === 'polar') {
    let [lx, ly] = mapVec(c, mouseWx - (c.bx || 0), mouseWy - (c.by || 0), true);
    if (sn > 0) { lx = snap(lx); ly = snap(ly); }
    const ang = Math.atan2(ly, lx) * 180 / Math.PI, rad = Math.hypot(lx, ly) / (c.ys || 1);
    const fx = +ang.toFixed(2), fy = +rad.toFixed(3);
    const [vx, vy] = mapVec(c, Math.cos(ang * Math.PI / 180) * fy * (c.ys || 1), Math.sin(ang * Math.PI / 180) * fy * (c.ys || 1), false);
    return { fx, fy, nwx: (c.bx || 0) + vx, nwy: (c.by || 0) + vy };
  }
  if (c.kind === 'arc' && c.cx != null) {
    let [lx, ly] = mapVec(c, mouseWx - c.cx, mouseWy - c.cy, true);
    let ang = Math.atan2(ly, lx) * 180 / Math.PI;
    if (sn > 0) ang = Math.round(ang);
    const fx = +ang.toFixed(2), fy = c.y, r = fy * (c.ys || 1);
    const [vx, vy] = mapVec(c, Math.cos(ang * Math.PI / 180) * r, Math.sin(ang * Math.PI / 180) * r, false);
    return { fx, fy, nwx: c.cx + vx, nwy: c.cy + vy };
  }
  if (c.kind === 'rad' && c.cx != null) {
    let [lx, ly] = mapVec(c, mouseWx - c.cx, mouseWy - c.cy, true);
    let dist = Math.hypot(lx, ly);
    if (sn > 0) dist = snap(dist);
    const fx = +(dist / (c.xs || 1)).toFixed(3);
    const [vx, vy] = mapVec(c, c.axis === 'y' ? 0 : dist, c.axis === 'y' ? dist : 0, false);
    return { fx, fy: 0, nwx: c.cx + vx, nwy: c.cy + vy };
  }
  if (c.kind === 'corner') {
    let fx = c.hx ? c.hx.v : c.x, fy = c.vy ? c.vy.v : c.y, mx = 0, my = 0;
    if (c.hx) { let lx = c.hx.v * (c.hx.xs || 1) + dlx; if (sn > 0) lx = snap(lx); fx = +(lx / (c.hx.xs || 1)).toFixed(3); mx = lx - c.hx.v * (c.hx.xs || 1); }
    if (c.vy) { let ly = c.vy.v * (c.vy.xs || 1) + dly; if (sn > 0) ly = snap(ly); fy = +(ly / (c.vy.xs || 1)).toFixed(3); my = ly - c.vy.v * (c.vy.xs || 1); }
    const [vx, vy] = mapVec(c, mx, my, false);
    return { fx, fy, nwx: c.wx + vx, nwy: c.wy + vy };
  }
  if (c.kind === 'mid') {
    if (!c.ends || !c.ends.length) return { fx: 0, fy: 0, nwx: c.wx, nwy: c.wy };
    let lx = dlx, ly = dly;
    if (sn > 0) { lx = snap(lx); ly = snap(ly); }
    const [vx, vy] = mapVec(c, lx, ly, false);
    return { fx: +lx.toFixed(3), fy: +ly.toFixed(3), nwx: c.wx + vx, nwy: c.wy + vy };
  }
  if (c.kind === 'xyz') {
    const zs = c.zs || 1;
    let visx = c.x * (c.xs || 1) + (c.z || 0) * zs * (c.uzx || 0) + dlx;
    let visy = c.y * (c.ys || 1) + (c.z || 0) * zs * (c.uzy || 0) + dly;
    if (sn > 0) { visx = snap(visx); visy = snap(visy); }
    const fx = +((visx - (c.z || 0) * zs * (c.uzx || 0)) / (c.xs || 1)).toFixed(3);
    const fy = +((visy - (c.z || 0) * zs * (c.uzy || 0)) / (c.ys || 1)).toFixed(3);
    const [vx, vy] = mapVec(c, (fx - c.x) * (c.xs || 1), (fy - c.y) * (c.ys || 1), false);
    return { fx, fy, nwx: c.wx + vx, nwy: c.wy + vy };
  }
  let lx = c.x * (c.xs || 1) + dlx, ly = c.y * (c.ys || 1) + dly;
  if (sn > 0) { lx = snap(lx); ly = snap(ly); }
  const fx = +(lx / (c.xs || 1)).toFixed(3), fy = +(ly / (c.ys || 1)).toFixed(3);
  const [vx, vy] = mapVec(c, (fx - c.x) * (c.xs || 1), (fy - c.y) * (c.ys || 1), false);
  return { fx, fy, nwx: c.wx + vx, nwy: c.wy + vy };
}
function pointText(c, fx, fy) {
  if (c.kind === 'anchor') return `($(${c.base})+(${fx},${fy})$)`;
  if (c.kind === 'lerp') return `!${fx}!`;
  if (c.kind === 'polar') return `(${+Number(fx).toFixed(2)}:${fmtNum(fy, c.uy)})`;
  if (c.kind === 'arc') return `(${c.a0}:${+Number(fx).toFixed(2)}:${fmtNum(fy, c.uy)})`;
  if (c.kind === 'rad') return fmtNum(fx, c.ux);
  if (c.kind === 'xyz') return `(${fmtNum(fx, c.ux)},${fmtNum(fy, c.uy)},${fmtNum(c.z, c.uz)})`;
  if (c.ux || c.uy) return `(${fmtNum(fx, c.ux)},${fmtNum(fy, c.uy)})`;
  return `(${fx},${fy})`;
}
function showFields(c) {
  const show = (lx, x, ly, y, hideY) => {
    $('lx').textContent = lx; $('ix').value = x;
    $('ly').style.display = hideY ? 'none' : 'inline'; $('iy').style.display = hideY ? 'none' : 'inline';
    if (!hideY) { $('ly').textContent = ly; $('iy').value = y; }
  };
  if (c.kind === 'lerp') show('比例:', c.x, '', 0, true);
  else if (c.kind === 'polar') show('角度:', c.x, '半径:', c.y, false);
  else if (c.kind === 'arc') show('终角:', c.x, '半径:', c.y, false);
  else if (c.kind === 'rad') show(c.label + ':', c.x, '', 0, true);
  else if (c.kind === 'mid') show('ΔX:', 0, 'ΔY:', 0, false);
  else if (c.kind === 'corner') show('拐X:', c.hx ? c.hx.v : c.x, '拐Y:', c.vy ? c.vy.v : c.y, !c.vy);
  else show(c.kind === 'abs' || c.kind === 'xyz' ? 'X:' : 'dX:', c.x, c.kind === 'abs' || c.kind === 'xyz' ? 'Y:' : 'dY:', c.y, false);
}
function tikzToPage(x, y) {
  return [cal.ox + x * cal.xx + y * cal.yx, cal.oy + x * cal.xy + y * cal.yy];
}
function pageToTikz(px, py) {
  const dx = px - cal.ox, dy = py - cal.oy, det = cal.xx * cal.yy - cal.yx * cal.xy;
  if (!det) return [0, 0];
  return [(cal.yy * dx - cal.yx * dy) / det, (-cal.xy * dx + cal.xx * dy) / det];
}
function pageDeltaToTikz(dx, dy) {
  const det = cal.xx * cal.yy - cal.yx * cal.xy;
  if (!det) return [0, 0];
  return [(cal.yy * dx - cal.yx * dy) / det, (-cal.xy * dx + cal.xx * dy) / det];
}
function worldScreen(wx, wy) {
  const ov = $('ov').getBoundingClientRect(), z = +$('zm').value, [px, py] = tikzToPage(wx, wy);
  return [ov.left + px * z, ov.top + py * z];
}
function refForPoint(p) {
  if (!p) return '';
  if (p.kind === 'anchor' && p.base && /^[A-Za-z]/.test(p.base)) return p.base;
  const hit = pts.find(o => o.kind === 'anchor' && o.base && /^[A-Za-z]/.test(o.base) && o.wx != null && Math.abs(o.wx - p.wx) < 0.02 && Math.abs(o.wy - p.wy) < 0.02);
  return hit ? hit.base : '';
}
function projectSeg(px, py, ax, ay, bx, by) {
  const dx = bx - ax, dy = by - ay, len2 = dx * dx + dy * dy;
  if (len2 < 1) return null;
  const t = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len2));
  const x = ax + dx * t, y = ay + dy * t;
  return { t, x, y, dist: Math.hypot(px - x, py - y) };
}
function borderSnap(clientX, clientY) {
  const groups = {};
  ports.forEach(p => { if (p.wx == null) return; (groups[p.name] || (groups[p.name] = {}))[p.anchor] = p; });
  let best = null;
  Object.keys(groups).forEach(name => {
    const g = groups[name];
    const nw = g['north west'], ne = g['north east'], se = g['south east'], sw = g['south west'];
    if (!nw || !ne || !se || !sw) return;
    const c = g.center && g.center.wx != null ? g.center : { wx: (nw.wx + se.wx) / 2, wy: (nw.wy + se.wy) / 2 };
    [[nw, ne], [ne, se], [se, sw], [sw, nw]].forEach(([a, b]) => {
      const [ax, ay] = worldScreen(a.wx, a.wy), [bx, by] = worldScreen(b.wx, b.wy);
      const hit = projectSeg(clientX, clientY, ax, ay, bx, by);
      if (!hit || hit.dist > 16 || (best && hit.dist >= best.dist)) return;
      const wx = +(a.wx + (b.wx - a.wx) * hit.t).toFixed(3), wy = +(a.wy + (b.wy - a.wy) * hit.t).toFixed(3);
      let port = null, portD = 10;
      ports.forEach(p => {
        if (p.name !== name || p.anchor === 'center' || p.wx == null) return;
        const [sx, sy] = worldScreen(p.wx, p.wy);
        const d = Math.hypot(hit.x - sx, hit.y - sy);
        if (d < portD) { portD = d; port = p; }
      });
      let ref = port ? port.ref : '';
      if (!ref) {
        let deg = Math.round((Math.atan2(wy - c.wy, wx - c.wx) * 180 / Math.PI + 360) % 360);
        if (deg === 360) deg = 0;
        ref = name + '.' + deg;
      }
      best = { dist: hit.dist, x: port ? +port.wx.toFixed(3) : wx, y: port ? +port.wy.toFixed(3) : wy, ref };
    });
  });
  return best;
}
function pickWorld(clientX, clientY) {
  const cands = [];
  pts.forEach(p => {
    if (!pointShown(p)) return;
    const [sx, sy] = worldScreen(p.wx, p.wy), dist = Math.hypot(clientX - sx, clientY - sy);
    if (dist <= 14) cands.push({ dist, x: +p.wx.toFixed(3), y: +p.wy.toFixed(3), ref: refForPoint(p) });
  });
  ports.forEach(p => {
    if (p.wx == null || p.anchor === 'center') return;
    const [sx, sy] = worldScreen(p.wx, p.wy), dist = Math.hypot(clientX - sx, clientY - sy);
    if (dist <= 14) cands.push({ dist, x: +p.wx.toFixed(3), y: +p.wy.toFixed(3), ref: p.ref });
  });
  const edge = borderSnap(clientX, clientY);
  if (edge) cands.push(edge);
  if (cands.length) { cands.sort((a, b) => a.dist - b.dist); return cands[0]; }
  const ov = $('ov').getBoundingClientRect(), z = +$('zm').value;
  let [x, y] = pageToTikz((clientX - ov.left) / z, (clientY - ov.top) / z);
  const sn = +$('sn').value;
  if (sn > 0) { x = Math.round(x / sn) * sn; y = Math.round(y / sn) * sn; }
  return { x: +x.toFixed(3), y: +y.toFixed(3), ref: '' };
}
function paintPlace() {
  $('ov').querySelectorAll('.ghost,.ghost-line,.port').forEach(el => el.remove());
  if (!place || !cal) return;
  const z = +$('zm').value, pos = (x, y) => { const [px, py] = tikzToPage(x, y); return { x: px * z, y: py * z }; };
  const spots = place.pts.map(p => p ? pos(p[0], p[1]) : null);
  if (place.n === 2 && spots[0] && !spots[1] && placeHover) spots[1] = pos(placeHover.x, placeHover.y);
  if (place.n >= 1) ports.forEach(p => {
    if (p.wx == null || p.anchor === 'center') return;
    const d = document.createElement('div'); d.className = 'port'; d.title = '(' + p.ref + ')';
    const s = pos(p.wx, p.wy); d.style.left = s.x + 'px'; d.style.top = s.y + 'px';
    d.onmousedown = e => { e.preventDefault(); e.stopPropagation(); putPlace(p.wx, p.wy, p.ref); };
    $('ov').appendChild(d);
  });
  if (spots[0] && spots[1]) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'ghost-line');
    const ln = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    ln.setAttribute('x1', spots[0].x); ln.setAttribute('y1', spots[0].y);
    ln.setAttribute('x2', spots[1].x); ln.setAttribute('y2', spots[1].y);
    svg.appendChild(ln); $('ov').appendChild(svg);
  }
  place.pts.forEach((p, i) => {
    if (!p || !spots[i]) return;
    const d = document.createElement('div');
    d.className = 'ghost'; d.textContent = String(i + 1);
    d.style.left = spots[i].x + 'px'; d.style.top = spots[i].y + 'px';
    $('ov').appendChild(d);
  });
  if (place.n === 1 && spots[0] && $('prot')) {
    const ang = (parseFloat($('prot').value) || 0) * Math.PI / 180;
    const ux = Math.cos(ang) * cal.xx + Math.sin(ang) * cal.yx, uy = Math.cos(ang) * cal.xy + Math.sin(ang) * cal.yy, nlen = Math.hypot(ux, uy) || 1;
    const dx = ux / nlen, dy = uy / nlen, len = 36;
    const x2 = spots[0].x + dx * len, y2 = spots[0].y + dy * len;
    const bx = x2 - dx * 9, by = y2 - dy * 9, px = -dy * 5, py = dx * 5;
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'ghost-line');
    [[spots[0].x, spots[0].y, x2, y2], [x2, y2, bx + px, by + py], [x2, y2, bx - px, by - py]].forEach(seg => {
      const ln = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      ln.setAttribute('x1', seg[0]); ln.setAttribute('y1', seg[1]);
      ln.setAttribute('x2', seg[2]); ln.setAttribute('y2', seg[3]);
      svg.appendChild(ln);
    });
    $('ov').appendChild(svg);
  }
}
function placeTitle() {
  const spec = PLACE[place.key], got = place.pts.filter(Boolean).length;
  const refs = place.pts.map(p => p && p.ref ? `(${p.ref})` : '').filter(Boolean).join(' → ');
  if (!spec.n) { $('place-title').textContent = `添加${spec.name}：填好后点确认`; return; }
  $('place-title').textContent = got >= spec.n ? `添加${spec.name}：${refs || '改好坐标后点确认'}` : `添加${spec.name}：在画布上点击 ${got}/${spec.n} 个点${refs ? ' ' + refs : ''}`;
}
function putPlace(x, y, ref) {
  if (!place || !place.n) return;
  if (x && typeof x === 'object') { ref = x.ref; y = x.y; x = x.x; }
  let idx = place.pts.findIndex(p => p == null);
  if (idx < 0) idx = place.n - 1;
  const p = [+Number(x).toFixed(3), +Number(y).toFixed(3)];
  if (ref) p.ref = ref;
  place.pts[idx] = p;
  $('px' + idx).value = p[0]; $('py' + idx).value = p[1];
  const tag = $('pr' + idx); if (tag) tag.textContent = ref ? `(${ref})` : '';
  placeHover = null; placeTitle(); paintPlace();
}
function readPlaceInputs() {
  if (!place) return;
  for (let i = 0; i < place.n; i++) {
    const x = parseFloat($('px' + i).value), y = parseFloat($('py' + i).value);
    const prev = place.pts[i];
    if (!Number.isFinite(x) || !Number.isFinite(y)) { place.pts[i] = null; if ($('pr' + i)) $('pr' + i).textContent = ''; continue; }
    if (prev && prev.ref && Math.abs(prev[0] - x) < 1e-6 && Math.abs(prev[1] - y) < 1e-6) continue;
    place.pts[i] = [x, y];
    if ($('pr' + i)) $('pr' + i).textContent = '';
  }
  placeTitle(); paintPlace();
}
function startPlace(key) {
  const spec = PLACE[key]; if (!spec) return;
  place = { key, n: spec.n, pts: Array(spec.n).fill(null) }; placeHover = null;
  $('inputs').style.display = 'none'; activeIdx = -1; idleSel();
  const box = $('place-fields'); box.innerHTML = '';
  const attr = s => String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;');
  if (spec.field) box.insertAdjacentHTML('beforeend', `<span>${spec.field}</span><input id="plab" class="wide" value="${attr(spec.def || '')}">`);
  (spec.inputs || []).forEach(inp => {
    const cls = inp.wide ? (inp.wide === true ? 'wide' : 'wide ' + inp.wide) : '';
    box.insertAdjacentHTML('beforeend', `<span>${inp.label}</span><input id="pf-${inp.id}" class="${cls}" value="${attr(inp.def || '')}">`);
    $('pf-' + inp.id).onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); confirmPlace(); } };
  });
  if (spec.n === 1 && spec.rot !== false) box.insertAdjacentHTML('beforeend', `<span>角度</span><input id="prot" type="number" step="15" value="0">`);
  for (let i = 0; i < spec.n; i++) {
    box.insertAdjacentHTML('beforeend', `<span>点${i + 1} X</span><input id="px${i}" type="number" step="0.05"><span>Y</span><input id="py${i}" type="number" step="0.05"><b id="pr${i}" class="pref"></b>`);
    $('px' + i).oninput = $('py' + i).oninput = readPlaceInputs;
    $('px' + i).onkeydown = $('py' + i).onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); confirmPlace(); } };
  }
  if ($('plab')) $('plab').onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); confirmPlace(); } };
  if ($('prot')) { $('prot').oninput = paintPlace; $('prot').onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); confirmPlace(); } }; }
  $('place').style.display = 'inline-flex'; $('wrap').classList.toggle('placing', spec.n > 0); placeTitle(); paintPlace();
}
function endPlace() {
  place = null; placeHover = null;
  $('place').style.display = 'none'; $('wrap').classList.remove('placing');
  paintPlace();
}
function confirmPlace() {
  if (!place) return;
  readPlaceInputs();
  const spec = PLACE[place.key];
  if (spec.n && place.pts.some(p => !p)) { $('st').textContent = '请先在画布上取点，或把坐标填完整'; return; }
  const extra = spec.field ? $('plab').value : '';
  const rot = $('prot') ? (parseFloat($('prot').value) || 0) : 0;
  const vals = {}; (spec.inputs || []).forEach(inp => { const el = $('pf-' + inp.id); vals[inp.id] = el ? el.value : ''; });
  const snip = '\n  ' + spec.build(place.pts, extra, rot, vals);
  endPlace(); appendSnip(snip, spec);
}
function appendSnip(s, spec) {
  const ta = $('code'); let v = ta.value || "\\begin{circuitikz}[european]\n\\end{circuitikz}";
  let i = spec && spec.panel === 'plot' ? v.lastIndexOf('\\end{axis}') : -1;
  if (i < 0) i = Math.max(v.lastIndexOf('\\end{circuitikz}'), v.lastIndexOf('\\end{tikzpicture}'));
  ta.value = i !== -1 ? v.slice(0, i).trimEnd() + s + "\n" + v.slice(i) : v + s; go(true);
}
function delSel() {
  if (activeIdx < 0) return; const c = pts.at(activeIdx), t = $('code').value;
  let st = t.lastIndexOf('\n', c.s); st = st === -1 ? 0 : st + 1;
  let ed = t.indexOf(';', c.e); ed = ed === -1 ? t.length : ed + 1;
  if (t.at(ed) === '\r') ed++; if (t.at(ed) === '\n') ed++;
  $('code').value = t.slice(0, st) + t.slice(ed); go(true);
}
function stmtOf(text, s) {
  let st = text.lastIndexOf('\n', s); st = st === -1 ? 0 : st + 1;
  let ed = text.indexOf(';', s); ed = ed === -1 ? text.length : ed + 1;
  return [st, ed];
}
function xformPoint(x, y, cx, cy, sc, cosA, sinA) {
  const dx = (x - cx) * sc, dy = (y - cy) * sc;
  return [cx + dx * cosA - dy * sinA, cy + dx * sinA + dy * cosA];
}
function xformSel() {
  const sc = parseFloat($('isc').value), rot = parseFloat($('irot').value);
  if (isNaN(sc) || sc <= 0 || isNaN(rot)) return;
  if (multiSet.size > 0) { xformMulti(sc, rot); return; }
  if (activeIdx < 0) return;
  const c = pts.at(activeIdx), t = $('code').value, [st, ed] = stmtOf(t, c.s);
  const stmt = t.slice(st, ed), ms = [...stmt.matchAll(/\(\s*([-+]?\d*\.?\d+)\s*,\s*([-+]?\d*\.?\d+)\s*\)/g)];
  if (!ms.length) return;
  const xs = ms.map(m => parseFloat(m.at(1))), ys = ms.map(m => parseFloat(m.at(2)));
  const cx = (Math.min(...xs) + Math.max(...xs)) / 2, cy = (Math.min(...ys) + Math.max(...ys)) / 2;
  const rad = rot * Math.PI / 180, cosA = Math.cos(rad), sinA = Math.sin(rad); let out = stmt;
  for (let i = ms.length - 1; i >= 0; i--) {
    const m = ms.at(i), [nx, ny] = xformPoint(parseFloat(m.at(1)), parseFloat(m.at(2)), cx, cy, sc, cosA, sinA);
    out = out.slice(0, m.index) + `(${+nx.toFixed(3)},${+ny.toFixed(3)})` + out.slice(m.index + m.at(0).length);
  }
  $('code').value = t.slice(0, st) + out + t.slice(ed); $('isc').value = '1.0'; $('irot').value = '0'; go(true);
}
function num3(n) { return +Number(n).toFixed(3); }
function allMovableSelected() {
  let n = 0;
  for (let i = 0; i < pts.length; i++) {
    if (!movablePoint(pts[i])) continue;
    n++;
    if (!multiSet.has(i)) return false;
  }
  return n > 0;
}
function scaleWhole(sc, rot) {
  const picked = pts.filter(movablePoint);
  const xs = picked.map(c => c.x), ys = picked.map(c => c.y);
  const zs = picked.filter(c => c.kind === 'xyz').map(c => Number(c.z) || 0);
  const cx = (Math.min(...xs) + Math.max(...xs)) / 2, cy = (Math.min(...ys) + Math.max(...ys)) / 2;
  const cz = zs.length ? (Math.min(...zs) + Math.max(...zs)) / 2 : 0;
  const ang = rot ? `, rotate=${num3(rot)}` : '';
  const open = `\\begin{scope}[shift={(${num3(cx)},${num3(cy)},${num3(cz)})}, scale=${num3(sc)}${ang}, shift={(${num3(-cx)},${num3(-cy)},${num3(-cz)})}]\n`;
  const close = '\\end{scope}\n';
  let t = $('code').value, m, spans = [];
  const re = /\\begin\s*\{(tikzpicture|circuitikz)\}(?:\[[^\]]*\])?/g;
  while ((m = re.exec(t))) {
    const end = t.indexOf('\\end{' + m[1] + '}', m.index + m[0].length);
    if (end >= 0) spans.push([m.index + m[0].length, end]);
  }
  if (!spans.length) { $('st').textContent = '没有可缩放的图形'; return; }
  for (let i = spans.length - 1; i >= 0; i--) {
    const [a, b] = spans[i];
    t = t.slice(0, b) + close + t.slice(b);
    t = t.slice(0, a) + '\n' + open + t.slice(a);
  }
  $('code').value = t; $('isc').value = '1.0'; $('irot').value = '0'; go(true);
}
function xformMulti(sc, rot) {
  if (sc === 1 && rot === 0) return;
  if (allMovableSelected()) { scaleWhole(sc, rot); return; }
  const t0 = $('code').value, seen = new Set(), spans = [];
  multiSet.forEach(i => {
    const c = pts.at(i); if (!c || (c.kind !== 'abs' && c.kind !== 'xyz')) return;
    const [st, ed] = stmtOf(t0, c.s); if (seen.has(st)) return; seen.add(st); spans.push([st, ed]);
  });
  if (!spans.length) { $('st').textContent = '选中的点不能缩放'; return; }
  const re = /\(\s*([-+]?\d*\.?\d+)\s*(cm|mm|pt|in|em|ex)?\s*,\s*([-+]?\d*\.?\d+)\s*(cm|mm|pt|in|em|ex)?\s*(?:,\s*([-+]?\d*\.?\d+)\s*(cm|mm|pt|in|em|ex)?)?\s*\)/g;
  const hitMap = new Map();
  spans.forEach(([st, ed]) => { for (const m of t0.slice(st, ed).matchAll(re)) hitMap.set(st + m.index, m); });
  const hits = [...hitMap.entries()].map(([at, m]) => ({ at, m }));
  if (!hits.length) return;
  const xs = hits.map(h => parseFloat(h.m[1])), ys = hits.map(h => parseFloat(h.m[3]));
  const cx = (Math.min(...xs) + Math.max(...xs)) / 2, cy = (Math.min(...ys) + Math.max(...ys)) / 2;
  const zs = hits.filter(h => h.m[5] != null).map(h => parseFloat(h.m[5]));
  const cz = zs.length ? (Math.min(...zs) + Math.max(...zs)) / 2 : 0;
  const rad = rot * Math.PI / 180, cosA = Math.cos(rad), sinA = Math.sin(rad);
  const edits = hits.map(h => {
    const [nx, ny] = xformPoint(parseFloat(h.m[1]), parseFloat(h.m[3]), cx, cy, sc, cosA, sinA);
    const txt = h.m[5] == null
      ? `(${fmtNum(nx, h.m[2])},${fmtNum(ny, h.m[4])})`
      : `(${fmtNum(nx, h.m[2])},${fmtNum(ny, h.m[4])},${fmtNum((parseFloat(h.m[5]) - cz) * sc + cz, h.m[6])})`;
    return { s: h.at, e: h.at + h.m[0].length, txt };
  });
  let t = t0;
  edits.sort((a, b) => b.s - a.s).forEach(ed => { t = t.slice(0, ed.s) + ed.txt + t.slice(ed.e); });
  $('code').value = t; $('isc').value = '1.0'; $('irot').value = '0'; go(true);
}
function dl(b, n) {
  const u = URL.createObjectURL(b), a = document.createElement('a');
  a.href = u; a.download = n; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(u), 1000);
}
async function exportFile(fmt) {
  $('st').textContent = '⏳ 导出中...';
  const r = await fetch('/api/export', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({code:$('code').value, compiler:$('comp').value, fmt})});
  if (!r.ok) { $('toast').style.display='block'; $('toast').textContent=await r.text(); return; }
  const fn = fmt === 'png' ? 'tikz_600dpi.png' : `tikz.${fmt}`; dl(await r.blob(), fn); $('st').textContent = `✅ 已导出 ${fn}`;
}
function lineSpan(text, s) {
  let st = text.lastIndexOf('\n', Math.max(0, s - 1)); st = st < 0 ? 0 : st + 1;
  let ed = text.indexOf('\n', s); if (ed < 0) ed = text.length; if (text.at(ed - 1) === '\r') ed--;
  return [st, ed];
}
function hideLine() { const hl = $('hl'); if (!hl) return; hl.style.display = 'none'; hl.dataset.line = ''; }
function idleSel() { $('sel-info').textContent = '拖拽框选或点全选，然后平移、缩放、旋转'; hideLine(); }
function editorBox(ta) {
  const cs = getComputedStyle(ta), font = cs.font, width = ta.clientWidth;
  if (ta._ebox && ta._ebox.font === font && ta._ebox.width === width) return ta._ebox;
  const prev = ta.value, top = ta.scrollTop, ss = ta.selectionStart, se = ta.selectionEnd, oninput = ta.oninput;
  ta.oninput = null;
  ta.value = 'x\n'.repeat(300); const h1 = ta.scrollHeight;
  ta.value = 'x\n'.repeat(600); const h2 = ta.scrollHeight;
  ta.value = prev; ta.scrollTop = top;
  try { ta.setSelectionRange(ss, se); } catch {}
  ta.oninput = oninput;
  const lh = (h2 - h1) / 300;
  ta._ebox = { lh: lh > 0 ? lh : 20, pad: parseFloat(cs.paddingTop) || 0, font, width };
  return ta._ebox;
}
function lineIndexAt(text, s) {
  let n = 1;
  for (let i = 0; i < s && i < text.length; i++) if (text.charCodeAt(i) === 10) n++;
  return n;
}
function placeLine() {
  const hl = $('hl'); if (!hl || hl.style.display === 'none' || !hl.dataset.line) return;
  const lh = +hl.dataset.lh || 20, pad = +hl.dataset.pad || 0;
  hl.style.height = lh + 'px';
  hl.style.top = (pad + (+hl.dataset.line - 1) * lh - $('code').scrollTop) + 'px';
}
function showLine(c, selectText = false) {
  const ta = $('code'), text = ta.value, [st, ed] = lineSpan(text, c.s);
  const line = lineIndexAt(text, c.s);
  const { lh, pad } = editorBox(ta);
  if (selectText) { ta.focus(); ta.setSelectionRange(st, ed); }
  const lineTop = pad + (line - 1) * lh;
  if (lineTop < ta.scrollTop || lineTop + lh > ta.scrollTop + ta.clientHeight) ta.scrollTop = Math.max(0, lineTop - ta.clientHeight / 2);
  const hl = $('hl');
  hl.dataset.line = String(line); hl.dataset.lh = String(lh); hl.dataset.pad = String(pad);
  hl.style.display = 'block'; placeLine();
}
function selectPt(idx, fi = false) {
  activeIdx = idx; const c = pts.at(idx); if (!c) return;
  showLine(c, true);
  $('sel-info').textContent = `L${c.l} (${c.wx ?? c.x}, ${c.wy ?? c.y})`; $('inputs').style.display = 'inline-flex';
  showFields(c);
  draw(); if (fi) { $('ix').focus(); $('ix').select(); }
}
function applyEdit(idx, fx, fy, moveStmt = false) {
  const c = pts.at(idx); let t = $('code').value;
  if (c.kind === 'mid') {
    if (!c.ends || !c.ends.length || (!fx && !fy)) return;
    const edits = c.ends.map(en => ({s: en.s, e: en.e, txt: `(${fmtNum(en.x + fx / (en.xs || 1), en.ux)},${fmtNum(en.y + fy / (en.ys || 1), en.uy)})`}));
    edits.sort((a, b) => b.s - a.s).forEach(ed => { t = t.slice(0, ed.s) + ed.txt + t.slice(ed.e); });
    $('code').value = t; go(true); return;
  }
  if (c.kind === 'corner') {
    const edits = [];
    if (c.hx) edits.push({s: c.hx.s, e: c.hx.e, txt: fmtNum(fx, c.hx.u)});
    if (c.vy) edits.push({s: c.vy.s, e: c.vy.e, txt: fmtNum(fy, c.vy.u)});
    if (!edits.length) return;
    edits.sort((a, b) => b.s - a.s).forEach(ed => { t = t.slice(0, ed.s) + ed.txt + t.slice(ed.e); });
    $('code').value = t; go(true); return;
  }
  if (moveStmt && (c.kind === 'abs' || c.kind === 'xyz')) {
    const dx = (fx - c.x) * (c.xs || 1), dy = (fy - c.y) * (c.ys || 1);
    let st = t.lastIndexOf('\n', c.s); st = st === -1 ? 0 : st + 1; let ed = t.indexOf(';', c.e); ed = ed === -1 ? t.length : ed + 1;
    const stmt = t.slice(st, ed), ms = [...stmt.matchAll(/\(\s*([-+]?\d*\.?\d+)\s*(cm|mm|pt|in|em|ex)?\s*,\s*([-+]?\d*\.?\d+)\s*(cm|mm|pt|in|em|ex)?\s*\)/g)]; let out = stmt;
    const sc = u => ({cm:1, mm:0.1, pt:2.54/72.27, in:2.54, em:0.3515, ex:0.151}[u] || 1);
    for (let i = ms.length - 1; i >= 0; i--) { const m = ms.at(i); out = out.slice(0, m.index) + `(${fmtNum(parseFloat(m.at(1)) + dx / sc(m.at(2)), m.at(2) || '')},${fmtNum(parseFloat(m.at(3)) + dy / sc(m.at(4)), m.at(4) || '')})` + out.slice(m.index + m.at(0).length); }
    $('code').value = t.slice(0, st) + out + t.slice(ed); go(true); return;
  }
  const rep = pointText(c, fx, fy);
  const edits = [{s: c.s, e: c.e, txt: rep}];
  if ($('lk').checked && c.kind === 'abs') pts.forEach((o, j) => { if (j !== idx && o.kind === 'abs' && (o.ux || '') === (c.ux || '') && (o.uy || '') === (c.uy || '') && Math.abs(o.x - c.x) < 1e-4 && Math.abs(o.y - c.y) < 1e-4) edits.push({s: o.s, e: o.e, txt: rep}); });
  edits.sort((a, b) => b.s - a.s).forEach(ed => { t = t.slice(0, ed.s) + ed.txt + t.slice(ed.e); }); $('code').value = t; go(true);
}
function movablePoint(c) { return !!(c && (c.kind === 'abs' || c.kind === 'xyz')); }
function showMulti(focus) {
  activeIdx = -1;
  if (!multiSet.size) { $('inputs').style.display = 'none'; $('sel-info').textContent = '没有可变换的坐标点'; hideLine(); draw(); return; }
  $('sel-info').textContent = `已多选 ${multiSet.size} 点，可平移；缩放和旋转后点变换`;
  $('inputs').style.display = 'inline-flex';
  $('lx').textContent = 'ΔX:'; $('ix').value = '0';
  $('ly').style.display = 'inline'; $('iy').style.display = 'inline'; $('ly').textContent = 'ΔY:'; $('iy').value = '0';
  draw();
  if (focus) { $('ix').focus(); $('ix').select(); }
}
function selectAllPoints() {
  multiSet.clear();
  pts.forEach((c, i) => { if (movablePoint(c)) multiSet.add(i); });
  showMulti(false);
}
function pointClient(c) {
  const z = +$('zm').value, [px, py] = tikzToPage(c.wx, c.wy), r = $('stage').getBoundingClientRect();
  return [r.left + px * z, r.top + py * z];
}
function beginMarquee(e) {
  const x0 = e.clientX, y0 = e.clientY, box = document.createElement('div');
  box.id = 'marquee'; document.body.appendChild(box);
  const paint = (x1, y1) => {
    box.style.left = Math.min(x0, x1) + 'px'; box.style.top = Math.min(y0, y1) + 'px';
    box.style.width = Math.abs(x1 - x0) + 'px'; box.style.height = Math.abs(y1 - y0) + 'px';
  };
  let moved = false;
  const mv = ev => { if (Math.abs(ev.clientX - x0) + Math.abs(ev.clientY - y0) < 4) return; moved = true; paint(ev.clientX, ev.clientY); };
  const up = ev => {
    window.removeEventListener('mousemove', mv); window.removeEventListener('mouseup', up); box.remove();
    if (!moved) { multiSet.clear(); activeIdx = -1; $('inputs').style.display = 'none'; idleSel(); draw(); return; }
    const l = Math.min(x0, ev.clientX), rgt = Math.max(x0, ev.clientX), t = Math.min(y0, ev.clientY), b = Math.max(y0, ev.clientY);
    if (!(e.shiftKey || e.ctrlKey || e.metaKey)) multiSet.clear();
    pts.forEach((c, i) => {
      if (!movablePoint(c) || c.wx == null || !pointShown(c)) return;
      const [px, py] = pointClient(c);
      if (px >= l && px <= rgt && py >= t && py <= b) multiSet.add(i);
    });
    showMulti(false);
  };
  window.addEventListener('mousemove', mv); window.addEventListener('mouseup', up);
}
function applyMultiMove(dx, dy) {
  let t = $('code').value; const edits = [], seen = new Set(), add = (s, e, x, y) => edits.push({s, e, txt: `(${+(x+dx).toFixed(3)},${+(y+dy).toFixed(3)})`});
  multiSet.forEach(idx => {
    const c = pts.at(idx); if (!movablePoint(c)) return;
    if (c.kind === 'xyz') { edits.push({ s: c.s, e: c.e, txt: pointText(c, c.x + dx, c.y + dy) }); return; }
    if ($('mv-all').checked) { let st = t.lastIndexOf('\n', c.s); st = st === -1 ? 0 : st + 1; let ed = t.indexOf(';', c.e); ed = ed === -1 ? t.length : ed + 1; if (seen.has(st)) return; seen.add(st); for (const m of t.slice(st, ed).matchAll(/\(\s*([-+]?\d*\.?\d+)\s*,\s*([-+]?\d*\.?\d+)\s*\)/g)) add(st + m.index, st + m.index + m.at(0).length, parseFloat(m.at(1)), parseFloat(m.at(2))); }
    else { add(c.s, c.e, c.x, c.y); if ($('lk').checked) pts.forEach((o, j) => { if (!multiSet.has(j) && o.kind === 'abs' && Math.abs(o.x-c.x)<1e-4 && Math.abs(o.y-c.y)<1e-4) add(o.s, o.e, o.x, o.y); }); }
  });
  const uniq = new Map(); edits.forEach(ed => uniq.set(ed.s, ed)); [...uniq.values()].sort((a, b) => b.s - a.s).forEach(ed => { t = t.slice(0, ed.s) + ed.txt + t.slice(ed.e); }); $('code').value = t; go(true);
}
async function go(rb = false) {
  const cur = $('code').value; syncPanel(cur); $('st').textContent = '⏳ 编译中...';
  const r = await fetch('/api/compile', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({code:cur, compiler:$('comp').value})});
  const d = await r.json();
  if (!d.ok) { $('toast').style.display = 'block'; if (rb && lastGood && lastGood !== cur) { $('code').value = lastGood; $('toast').textContent = '⚠️ 已回退：\n' + d.err; $('st').textContent = '↩ 已回退'; draw(); } else { $('toast').textContent = '❌ 编译错误：\n' + d.err; $('st').textContent = '❌ 失败'; } return; }
  $('toast').style.display = 'none'; if (cur !== lastGood) { lastGood = cur; history.push(cur); if (history.length > 30) history.shift(); }
  $('svg').innerHTML = d.svg; W = d.w; H = d.h; pts = d.coords; ports = d.ports || []; cal = d.cal; activeIdx = -1; multiSet.clear(); $('inputs').style.display = 'none'; idleSel(); draw(); $('st').textContent = '✅ 成功 (' + pts.length + '点)';
}
function draw() {
  const z = +$('zm').value, s = $('svg').querySelector('svg'); if (s && W) { s.style.width = (W * z) + 'px'; s.style.height = (H * z) + 'px'; }
  $('ov').innerHTML = ''; if (!cal) return;
  const order = pts.map((_, n) => n).sort((a, b) => (pts[a].kind === 'abs' || pts[a].kind === 'xyz') - (pts[b].kind === 'abs' || pts[b].kind === 'xyz'));
  order.forEach(i0 => {
    const c0 = pts[i0];
    if (!pointShown(c0)) return;
    const d = document.createElement('div'); d.dataset.idx = i0;
    const red = c0.kind === 'abs' || c0.kind === 'xyz', purple = c0.kind === 'lerp' || c0.kind === 'mid';
    d.className = 'dot' + (purple ? ' lerp' : (red ? '' : ' rel')) + (multiSet.has(i0) ? ' msel' : (i0 === activeIdx ? ' sel' : ''));
    const [cpx, cpy] = tikzToPage(c0.wx, c0.wy);
    d.style.left = (cpx * z) + 'px'; d.style.top = (cpy * z) + 'px';
    d.onmousedown = e => {
      if (place) { e.preventDefault(); e.stopPropagation(); putPlace(c0.wx, c0.wy, refForPoint(c0)); return; }
      let i = i0, c = c0;
      if (c.kind === 'anchor' && c.wx != null) {
        const j = pts.findIndex(o => o.kind === 'abs' && o.wx != null && Math.abs(o.wx - c.wx) < 0.01 && Math.abs(o.wy - c.wy) < 0.01);
        if (j >= 0) { i = j; c = pts[j]; }
      }
      e.preventDefault(); e.stopPropagation(); document.body.style.cursor = 'grabbing'; const isMod = e.ctrlKey || e.shiftKey;
      const mark = i === i0 ? d : ($('ov').querySelector('.dot[data-idx="' + i + '"]') || d);
      const movers = mark === d ? [d] : [d, mark];
      if (!isMod && !multiSet.has(i)) { multiSet.clear(); activeIdx = i; $('ov').querySelectorAll('.dot').forEach(el => el.classList.remove('sel', 'msel')); mark.classList.add('sel'); }
      showLine(c);
      const sx = e.clientX, sy = e.clientY, sn = +$('sn').value; let fx = c.x, fy = c.y, mv0 = false;
      const mv = v => {
        if (Math.abs(v.clientX - sx) < 2 && Math.abs(v.clientY - sy) < 2) return; mv0 = true;
        const [dwx, dwy] = pageDeltaToTikz((v.clientX - sx) / z, (v.clientY - sy) / z);
        if (c.kind === 'lerp') { fx = +Math.max(0.05, Math.min(0.95, Math.round((c.x + dwx * 0.4) / 0.05) * 0.05)).toFixed(2); $('ix').value = fx; return; }
        const plan = planDrag(c, dwx, dwy, sn);
        fx = plan.fx; fy = plan.fy; const nwx = +plan.nwx.toFixed(3), nwy = +plan.nwy.toFixed(3), dx = nwx - c.wx, dy = nwy - c.wy;
        const placeDot = (el, x, y) => { const [px, py] = tikzToPage(x, y); el.style.left = (px * z) + 'px'; el.style.top = (py * z) + 'px'; };
        movers.forEach(el => placeDot(el, nwx, nwy));
        if (multiSet.has(i) && multiSet.size > 1) $('ov').querySelectorAll('.dot').forEach(el => { const j = +el.dataset.idx, o = pts.at(j); if (multiSet.has(j) && o) placeDot(el, o.wx + dx, o.wy + dy); });
        else if ($('mv-all').checked && c.kind === 'abs') { const t = $('code').value; let st = t.lastIndexOf('\n', c.s); st = st === -1 ? 0 : st + 1; let ed = t.indexOf(';', c.e); ed = ed === -1 ? t.length : ed + 1; $('ov').querySelectorAll('.dot').forEach(el => { const j = +el.dataset.idx, o = pts.at(j); if (o && o.s >= st && o.e <= ed) placeDot(el, o.wx + dx, o.wy + dy); }); }
        $('ix').value = fx; $('iy').value = fy; $('tip').style.display = 'block'; $('tip').style.left = (v.clientX + 14) + 'px'; $('tip').style.top = (v.clientY + 14) + 'px'; $('tip').textContent = `位置:(${nwx},${nwy}) 参数:(${fx},${fy})`;
      };
      const up = () => {
        window.removeEventListener('mousemove', mv); window.removeEventListener('mouseup', up); document.body.style.cursor = ''; $('tip').style.display = 'none';
        if (!mv0) { if (isMod) { if (multiSet.has(i)) multiSet.delete(i); else multiSet.add(i); showMulti(multiSet.size > 0); } else selectPt(i, true); }
        else if (fx !== c.x || fy !== c.y) { if (multiSet.has(i) && multiSet.size > 1) applyMultiMove(fx - c.x, fy - c.y); else applyEdit(i, fx, fy, $('mv-all').checked); }
      };
      window.addEventListener('mousemove', mv); window.addEventListener('mouseup', up);
    };
    $('ov').appendChild(d);
  });
  paintPlace();
}
window.onload = () => {
  $('del-btn').onclick = delSel; $('xform-btn').onclick = xformSel; $('sel-all').onclick = selectAllPoints;
  $('tpl-sel').onchange = e => { if (e.target.value) { endPlace(); $('code').value = TPLS[e.target.value]; syncPanel($('code').value); e.target.value = ""; go(false); } };
  $('open-tex').onclick = () => $('file-in').click();
  $('file-in').onchange = e => { const f = e.target.files.item(0); if (!f) return; const rd = new FileReader(); rd.onload = ev => { $('code').value = ev.target.result; go(false); }; rd.readAsText(f, 'UTF-8'); e.target.value = ''; };
  $('save-tex').onclick = () => dl(new Blob([$('code').value], {type:'text/plain'}), 'tikz.tex');
  $('place-ok').onclick = confirmPlace; $('place-cancel').onclick = endPlace;
  $('lib-close').onclick = () => { $('libbox').style.display = 'none'; };
  $('lib-add-pick').onclick = () => addLibKey($('lib-pick').value);
  $('lib-add-custom').onclick = addCustomLib;
  loadLib(); renderBar();
  window.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && (e.key === 'a' || e.key === 'A')) {
      const tag = (e.target && e.target.tagName) || '';
      if (tag !== 'TEXTAREA' && tag !== 'INPUT' && tag !== 'SELECT') { e.preventDefault(); selectAllPoints(); }
      return;
    }
    if (e.key !== 'Escape') return;
    if (place) { e.preventDefault(); endPlace(); return; }
    if ($('libbox').style.display === 'block') { e.preventDefault(); $('libbox').style.display = 'none'; }
  });
  $('wrap').onmousemove = e => {
    if (!place || !cal || place.n < 2 || place.pts[0] == null || place.pts[1] != null) { if (placeHover) { placeHover = null; paintPlace(); } return; }
    const w = pickWorld(e.clientX, e.clientY);
    if (placeHover && w.x === placeHover.x && w.y === placeHover.y && w.ref === placeHover.ref) return;
    placeHover = w; paintPlace();
  };
  $('wrap').onmousedown = e => {
    if (e.target.closest && e.target.closest('.dot')) return;
    const onCanvas = e.target === $('wrap') || ($('stage') && $('stage').contains(e.target));
    if (place && place.n > 0 && onCanvas && cal) { e.preventDefault(); putPlace(pickWorld(e.clientX, e.clientY)); return; }
    if (e.target === $('wrap') || e.target === $('stage') || ($('svg') && $('svg').contains(e.target))) { e.preventDefault(); beginMarquee(e); }
  };
  $('code').onscroll = placeLine; $('code').oninput = hideLine;
  $('apply').onclick = () => { const fx = parseFloat($('ix').value), fy = parseFloat($('iy').value); if (isNaN(fx)) return; const yv = isNaN(fy) ? 0 : fy; if (multiSet.size > 0) { if (fx !== 0 || yv !== 0) applyMultiMove(fx, yv); } else if (activeIdx >= 0) applyEdit(activeIdx, fx, yv, $('mv-all').checked); };
  $('ix').onkeydown = $('iy').onkeydown = e => { if (e.key === 'Enter') $('apply').click(); };
  $('undo').onclick = () => { if (history.length > 1) { history.pop(); $('code').value = history.at(-1); go(false); } };
  $('run').onclick = () => go(false); $('zm').oninput = draw; $('sh-r').onchange = $('sh-b').onchange = $('sh-p').onchange = draw;
  $('code').onkeydown = e => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); go(false); } };
  $('code').value = INIT_CODE; go(false);
};

