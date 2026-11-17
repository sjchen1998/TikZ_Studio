const $ = id => document.getElementById(id);
let pts = [], ports = [], W = 0, H = 0, cal = null, activeIdx = -1, multiSet = new Set(), lastGood = '', history = [];
let place = null, placeHover = null, dimKeep = '';
let shapeDrag = null;
let statusNow = { kind: 'ready', n: 0, note: '', path: '' };
let tabPad = '    ';
async function loadEditorConfig() {
  try {
    const d = await (await fetch('/api/editorconfig')).json();
    if (!d || !d.ok) return;
    const n = Math.max(1, Math.min(8, +(d.tab_width || d.indent_size || 4) || 4));
    tabPad = ' '.repeat(n);
    const ta = $('code');
    if (ta) ta.style.tabSize = String(n);
  } catch (_) {}
}
function paintStatus() {
  const n = statusNow.n, note = statusNow.note;
  const count = tf(n + '点', n + (n === 1 ? ' point' : ' points'));
  $('st').title = statusNow.kind === 'exported' ? (statusNow.path || '') : '';
  if (statusNow.kind === 'ok') $('st').textContent = tf('✅ 成功', '✅ OK') + ' (' + count + ')';
  else if (statusNow.kind === 'note') $('st').textContent = '✅ ' + note;
  else if (statusNow.kind === 'compiling') $('st').textContent = t('⏳ 编译中...');
  else if (statusNow.kind === 'exporting') $('st').textContent = t('⏳ 导出中...');
  else if (statusNow.kind === 'exported') $('st').textContent = tf('✅ 已导出 ' + note, '✅ Exported ' + note);
  else if (statusNow.kind === 'importing') $('st').textContent = t('⏳ 导入 DXF...');
  else if (statusNow.kind === 'fail') $('st').textContent = t('❌ 失败');
  else if (statusNow.kind === 'revert') $('st').textContent = t('↩ 已回退');
  else if (statusNow.kind === 'needpts') $('st').textContent = t('请先在画布上取点，或把坐标填完整');
  else if (statusNow.kind === 'noscale') $('st').textContent = t('没有可缩放的图形');
  else if (statusNow.kind === 'noselect') $('st').textContent = t('选中的点不能缩放');
  else if (statusNow.kind === 'angpar') $('st').textContent = t('这两条直线平行或共线，不能标角度');
  else if (statusNow.kind === 'angskew') $('st').textContent = t('这两条直线不在同一个平面上，不能标角度');
  else if (statusNow.kind === 'dupname') $('st').textContent = t('代号已存在');
  else if (statusNow.kind === 'badname') $('st').textContent = t('代号需以字母开头，仅含字母数字下划线');
  else $('st').textContent = t('就绪');
}
function usedNodeNames(code) {
  const set = new Set();
  const re = /\\(?:node|coordinate)\s*(?:\[[^\]]*\])?\s*\(\s*([A-Za-z][A-Za-z0-9_]*)\s*\)/g;
  let m;
  while ((m = re.exec(String(code || '')))) set.add(m[1]);
  ports.forEach(p => { if (p && p.name) set.add(p.name); });
  return set;
}
function nextBlockId(code) {
  const used = usedNodeNames(code);
  for (let i = 0; i < 26; i++) {
    const c = String.fromCharCode(97 + i);
    if (!used.has(c)) return c;
  }
  let n = 1;
  while (used.has('n' + n)) n++;
  return 'n' + n;
}
function blockIdOk(name) { return /^[A-Za-z][A-Za-z0-9_]*$/.test(String(name || '').trim()); }
function blockIdTaken(name, code) {
  const id = String(name || '').trim();
  if (!id) return false;
  return usedNodeNames(code).has(id);
}
function syncBlockIdMsg() {
  const el = $('pf-id'), msg = $('pid-msg');
  if (!el || !msg || !place || !PLACE[place.key] || !PLACE[place.key].idField) return true;
  const id = el.value.trim();
  if (!id) { msg.textContent = t('请填写代号'); msg.className = 'pid-msg bad'; return false; }
  if (!blockIdOk(id)) { msg.textContent = t('代号需以字母开头，仅含字母数字下划线'); msg.className = 'pid-msg bad'; return false; }
  if (blockIdTaken(id, $('code').value)) { msg.textContent = t('代号已存在'); msg.className = 'pid-msg bad'; return false; }
  msg.textContent = ''; msg.className = 'pid-msg'; return true;
}
function setStatus(kind, extra) {
  statusNow.kind = kind;
  if (extra && extra.n != null) statusNow.n = extra.n;
  if (extra && extra.note != null) statusNow.note = extra.note;
  statusNow.path = extra && extra.path ? extra.path : '';
  paintStatus();
}

function insText() { startPlace('text'); }
function insComp(k) { startPlace(k); }
const LIB_STORE = 'tikzStudioLib', LIB_VER = 7;
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
    let keys = Array.isArray(raw.keys) ? raw.keys.filter(k => inPanel(k, name) && k !== 'xticks') : defaultKeys(name);
    if (migrated && Array.isArray(raw.keys)) {
      visibleCommon(name).slice().reverse().forEach(k => { if (!keys.includes(k)) keys.unshift(k); });
      PANELS[name].lib.forEach(k => { if (!keys.includes(k) && inPanel(k, name)) keys.push(k); });
      keys = keys.filter(k => k !== 'xticks');
      if (name === 'block') keys = keys.filter(k => !BLOCK_OPT_OFF.includes(k));
    }
    libs[name] = { keys, custom };
  });
  if (migrated) saveLib();
}
function renderBar() {
  const bar = $('cbar'), specP = PANELS[panel]; bar.innerHTML = '';
  const tag = document.createElement('span'); tag.className = 'panel-tag'; tag.textContent = t(specP.title); bar.appendChild(tag);
  const pinned = fixedKeys(panel);
  specP.core.concat(pinned).forEach(k => {
    const spec = PLACE[k]; if (!spec) return;
    const b = document.createElement('button');
    b.className = 'comp'; b.type = 'button'; b.textContent = t(spec.btn || spec.name);
    b.onclick = () => insComp(k); bar.appendChild(b);
  });
  slot().keys.forEach(k => {
    if (specP.core.includes(k) || pinned.includes(k)) return;
    const spec = PLACE[k]; if (!spec) return;
    const wrap = document.createElement('span'); wrap.className = 'libitem';
    const b = document.createElement('button');
    b.className = 'comp lib'; b.type = 'button'; b.textContent = t(spec.btn || spec.name);
    b.onclick = () => insComp(k);
    const x = document.createElement('button');
    x.className = 'libx'; x.type = 'button'; x.title = t('从面板移除'); x.textContent = '×';
    x.onclick = e => { e.preventDefault(); e.stopPropagation(); removeLib(k); };
    wrap.appendChild(b); wrap.appendChild(x); bar.appendChild(wrap);
  });
  const add = document.createElement('button');
  add.className = 'comp lib add'; add.type = 'button'; add.textContent = '＋'; add.title = t('添加本面板的元件');
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
  sel.innerHTML = keys.length ? keys.map(k => {
    const spec = PLACE[k];
    const how = spec.n ? tf(spec.n + '点', spec.n + (spec.n === 1 ? ' point' : ' points')) : t('不取点');
    return `<option value="${k}">${t(spec.btn || spec.name)} · ${how}</option>`;
  }).join('') : `<option value="">${t('库中的都已在面板上')}</option>`;
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
  if (!name || !tpl || (n >= 1 && !tpl.includes('{{1}}')) || (n === 2 && !tpl.includes('{{2}}'))) {
    $('lib-msg').textContent = n
      ? tf('需要按钮名，以及模板里的 {{1}}' + (n === 2 ? ' 和 {{2}}' : ''), 'Need a button name, and {{1}}' + (n === 2 ? ' and {{2}}' : '') + ' in the template')
      : t('需要按钮名和模板');
    return;
  }
  const c = { id: 'c' + Date.now().toString(36), name, n, field, def, tpl };
  slot().custom.push(c); installCustom(c, panel); slot().keys.push(c.id); saveLib(); renderBar(); fillLibPick();
  $('lib-name').value = ''; $('lib-tpl').value = ''; $('lib-msg').textContent = tf('已添加到' + PANELS[panel].title, 'Added to ' + t(PANELS[panel].title));
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
    let dx = mouseWx - c.cx, dy = mouseWy - c.cy;
    let dist = Math.hypot(dx, dy);
    if (sn > 0) dist = snap(dist);
    dist = Math.max(0.02, dist);
    const fx = +(dist / (c.xs || 1)).toFixed(3);
    if (c.label === 'X半径' || c.label === 'Y半径') {
      const ang = Math.atan2(dy, dx) * 180 / Math.PI;
      const rot = c.axis === 'y' ? ang - 90 : ang;
      const axes = ellAxes(rot);
      const dir = c.axis === 'y' ? [axes.vx, axes.vy] : [axes.ux, axes.uy];
      const side = dx * dir[0] + dy * dir[1] < 0 ? -1 : 1;
      return { fx, fy: 0, nwx: c.cx + dir[0] * dist * side, nwy: c.cy + dir[1] * dist * side, ellRot: rot, ellLen: dist };
    }
    const L0 = Math.hypot(mouseWx - c.cx, mouseWy - c.cy);
    if (L0 > 1e-9) { dx = (mouseWx - c.cx) / L0 * dist; dy = (mouseWy - c.cy) / L0 * dist; }
    else { dx = dist; dy = 0; }
    return { fx, fy: 0, nwx: c.cx + dx, nwy: c.cy + dy };
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
function coordIdx(text, name) {
  const marker = '\\coordinate (' + name + ')';
  return pts.findIndex(p => text.slice(text.lastIndexOf('\n', p.s) + 1, p.s).includes(marker));
}
function dimXY(p) {
  if (!p) return null;
  if ((p.kind === 'abs' || p.kind === 'xyz') && Number.isFinite(p.x) && Number.isFinite(p.y)) return [p.x, p.y];
  if (Number.isFinite(p.wx) && Number.isFinite(p.wy)) return [p.wx, p.wy];
  return null;
}
function dimLineLayout(idx, fx, fy, also) {
  const c = pts[idx];
  if (!c || (c.kind !== 'abs' && c.kind !== 'xyz') || !Number.isFinite(+fx) || !Number.isFinite(+fy)) return null;
  const text = $('code').value;
  const le = text.indexOf('\n', c.s);
  const line = text.slice(text.lastIndexOf('\n', c.s) + 1, le < 0 ? text.length : le);
  const m = line.match(/\\coordinate \((d\d+)([abcd])\)/);
  if (!m) return null;
  const span = udimScopeSpan(text, c.s);
  const info = span && readUdim(text, span);
  if (!info || ('d' + info.id) !== m[1]) return null;
  const ia = coordIdx(text, m[1] + 'a'), ib = coordIdx(text, m[1] + 'b');
  const ic = coordIdx(text, m[1] + 'c'), id = coordIdx(text, m[1] + 'd'), it = coordIdx(text, m[1] + 't');
  if (ia < 0 || ib < 0 || ic < 0 || id < 0) return null;
  const r = n => +Number(n).toFixed(4);
  const at = (i, fallback) => (also && also[i]) || fallback;
  if (m[2] === 'a' || m[2] === 'b') {
    const A0 = dimXY(pts[ia]), B0 = dimXY(pts[ib]);
    const T0 = it >= 0 ? dimXY(pts[it]) : null;
    if (!A0 || !B0 || !T0) return null;
    const A = m[2] === 'a' ? [+fx, +fy] : at(ia, A0);
    const B = m[2] === 'b' ? [+fx, +fy] : at(ib, B0);
    const [nC, nD] = dimFeet(A, B, at(it, T0), info.mode);
    return [
      { i: idx, x: r(fx), y: r(fy) },
      { i: ic, x: r(nC[0]), y: r(nC[1]) },
      { i: id, x: r(nD[0]), y: r(nD[1]) }
    ];
  }
  const A = at(ia, dimXY(pts[ia])), B = at(ib, dimXY(pts[ib])), oldC = dimXY(pts[ic]);
  if (!A || !B || !oldC) return null;
  const [nC, nD] = dimFeet(A, B, [+fx, +fy], info.mode);
  const dx = nC[0] - oldC[0], dy = nC[1] - oldC[1];
  const edits = [{ i: ic, x: r(nC[0]), y: r(nC[1]) }, { i: id, x: r(nD[0]), y: r(nD[1]) }];
  const T = it >= 0 ? pts[it] : null;
  if (T && (T.kind === 'abs' || T.kind === 'xyz')) edits.push({ i: it, x: r(T.x + dx), y: r(T.y + dy) });
  return edits;
}
function writeDimLayout(idx, fx, fy) {
  const layout = dimLineLayout(idx, fx, fy);
  if (!layout) return false;
  let t = $('code').value;
  const edits = layout.map(ed => { const o = pts[ed.i]; return { s: o.s, e: o.e, txt: pointText(o, ed.x, ed.y) }; });
  edits.sort((a, b) => b.s - a.s).forEach(ed => { t = t.slice(0, ed.s) + ed.txt + t.slice(ed.e); });
  $('code').value = t; go(true); return true;
}
function showFields(c) {
  const show = (lx, x, ly, y, hideY) => {
    $('lx').style.display = 'inline'; $('ix').style.display = 'inline';
    $('lx').textContent = lx; $('ix').value = x;
    $('ly').style.display = hideY ? 'none' : 'inline'; $('iy').style.display = hideY ? 'none' : 'inline';
    if (!hideY) { $('ly').textContent = ly; $('iy').value = y; }
  };
  const ellBox = $('ell-extra'), paBox = $('planeaxes-extra'), xform = $('xform-wrap');
  if (ellBox) ellBox.style.display = 'none';
  if (paBox) paBox.style.display = 'none';
  if (xform) xform.style.display = '';
  const pa = findPlaneAxesAt(pts.indexOf(c));
  if (pa) {
    $('lx').style.display = 'none'; $('ix').style.display = 'none';
    $('ly').style.display = 'none'; $('iy').style.display = 'none';
    if (xform) xform.style.display = 'none';
    if (paBox) {
      paBox.style.display = 'inline-flex';
      $('pa-x0').value = pa.x0; $('pa-x1').value = pa.x1;
      $('pa-y0').value = pa.y0; $('pa-y1').value = pa.y1;
      $('pa-tx0').value = pa.tx0; $('pa-tx1').value = pa.tx1;
      $('pa-ty0').value = pa.ty0; $('pa-ty1').value = pa.ty1;
    }
    return;
  }
  const ell = findEllAt(pts.indexOf(c));
  if (ell && ell.role === 'c') {
    show('X:', ell.cx, 'Y:', ell.cy, false);
    if (ellBox) {
      ellBox.style.display = 'inline-flex';
      $('ell-rx').value = radNum(ell.rx);
      $('ell-ry').value = radNum(ell.ry);
      $('ell-rot').value = radNum(ell.rot);
    }
    return;
  }
  if (c.kind === 'lerp') show(t('比例:'), c.x, '', 0, true);
  else if (c.kind === 'polar') show(t('角度:'), c.x, t('半径:'), c.y, false);
  else if (c.kind === 'arc') show(t('终角:'), c.x, t('半径:'), c.y, false);
  else if (c.kind === 'rad') show(t(c.label) + ':', c.x, '', 0, true);
  else if (c.kind === 'mid') show('ΔX:', 0, 'ΔY:', 0, false);
  else if (c.kind === 'corner') show(t('拐X:'), c.hx ? c.hx.v : c.x, t('拐Y:'), c.vy ? c.vy.v : c.y, !c.vy);
  else show(c.kind === 'abs' || c.kind === 'xyz' ? 'X:' : 'dX:', c.x, c.kind === 'abs' || c.kind === 'xyz' ? 'Y:' : 'dY:', c.y, false);
}
function planeAxesScopeSpan(text, pos) { return markedScopeSpan(text, pos, 'planeaxes'); }
function readPlaneAxes(raw) {
  const ax = raw.match(/\\draw\[[^\]]*\]\s*\(\s*([-+]?\d*\.?\d+)\s*,\s*0\s*\)\s*--\s*\(\s*([-+]?\d*\.?\d+)\s*,\s*0\s*\)/);
  const ay = raw.match(/\\draw\[[^\]]*\]\s*\(\s*0\s*,\s*([-+]?\d*\.?\d+)\s*\)\s*--\s*\(\s*0\s*,\s*([-+]?\d*\.?\d+)\s*\)/);
  const tx = raw.match(/\\foreach\s*\\x\s*in\s*\{([^}]+)\}/);
  const ty = raw.match(/\\foreach\s*\\y\s*in\s*\{([^}]+)\}/);
  const listRange = s => {
    const nums = String(s || '').split(',').map(x => parseInt(x.trim(), 10)).filter(Number.isFinite);
    if (!nums.length) return { a: -3, b: 4 };
    return { a: Math.min(...nums), b: Math.max(...nums) };
  };
  const xl = listRange(tx && tx[1]), yl = listRange(ty && ty[1]);
  return {
    x0: ax ? +ax[1] : -4, x1: ax ? +ax[2] : 5,
    y0: ay ? +ay[1] : -3, y1: ay ? +ay[2] : 5,
    tx0: xl.a, tx1: xl.b, ty0: yl.a, ty1: yl.b
  };
}
function findPlaneAxesAt(idx) {
  const c = pts[idx];
  if (!c || c.s == null) return null;
  const span = planeAxesScopeSpan($('code').value, c.s);
  if (!span) return null;
  const raw = $('code').value.slice(span[0], span[1]);
  return { span, raw, indent: (raw.match(/^[ \t]*/) || [''])[0], ...readPlaneAxes(raw), idx };
}
function planeAxesLocked(idx) { return !!findPlaneAxesAt(idx); }
function gridStmtAt(pos) {
  const text = $('code').value;
  let st = text.lastIndexOf('\n', Math.max(0, pos - 1));
  st = st < 0 ? 0 : st + 1;
  let ed = text.indexOf(';', pos);
  if (ed < 0) ed = text.length; else ed++;
  const raw = text.slice(st, ed);
  if (!/\bgrid\b/i.test(raw)) return null;
  return { st, ed, raw };
}
function gridLocked(idx) {
  const c = pts[idx];
  if (!c || c.s == null || (c.kind !== 'abs' && c.kind !== 'xyz')) return false;
  return !!gridStmtAt(c.s);
}
function noMultiSelect(idx) {
  return radLocked(idx) || planeAxesLocked(idx) || gridLocked(idx);
}
function writePlaneAxes(info, vals) {
  const body = planeAxesCode(vals);
  const lines = body.split('\n');
  const indent = info.indent || '';
  const text = $('code').value;
  const out = indent + lines[0] + '\n' + lines.slice(1).map(ln => (/^\s/.test(ln) ? ln : indent + ln)).join('\n') + (info.raw.endsWith('\n') ? '\n' : '');
  $('code').value = text.slice(0, info.span[0]) + out + text.slice(info.span[1]);
  go(true);
}
function planeAxesValsFromInputs() {
  return {
    x0: $('pa-x0').value, x1: $('pa-x1').value,
    y0: $('pa-y0').value, y1: $('pa-y1').value,
    tx0: $('pa-tx0').value, tx1: $('pa-tx1').value,
    ty0: $('pa-ty0').value, ty1: $('pa-ty1').value
  };
}
function ellStmtAt(pos) {
  const text = $('code').value;
  let st = text.lastIndexOf('\n', Math.max(0, pos - 1));
  st = st < 0 ? 0 : st + 1;
  let ed = text.indexOf(';', pos);
  if (ed < 0) ed = text.length; else ed++;
  const raw = text.slice(st, ed);
  if (!/ellipse\b/.test(raw)) return null;
  return { st, ed, raw };
}
function parseEllRaw(raw) {
  const br = raw.match(/ellipse\s*\[\s*x\s+radius\s*=\s*([-+]?\d*\.?\d+)\s*(cm|mm|pt|in)?\s*,\s*y\s+radius\s*=\s*([-+]?\d*\.?\d+)\s*(cm|mm|pt|in)?(?:\s*,\s*rotate\s*=\s*([-+]?\d*\.?\d+))?\s*\]/i);
  if (br) return { rx: +br[1], ry: +br[3], rot: +(br[5] || 0), form: 'br', m: br };
  const cl = raw.match(/ellipse\s*\(\s*([-+]?\d*\.?\d+)\s*(cm|mm|pt|in)?\s+and\s+([-+]?\d*\.?\d+)\s*(cm|mm|pt|in)?\s*\)/i);
  if (!cl) return null;
  const rotM = raw.match(/rotate\s*(?:around\s*=\s*\{\s*([-+]?\d*\.?\d+)\s*:|=\s*([-+]?\d*\.?\d+))/i);
  return { rx: +cl[1], ry: +cl[3], rot: rotM ? +(rotM[1] || rotM[2] || 0) : 0, form: 'cl', m: cl };
}
function findEllAt(idx) {
  const c = pts[idx];
  if (!c || c.s == null) return null;
  if (c.kind === 'rad' && (c.label === 'X半径' || c.label === 'Y半径')) {
    const span = ellStmtAt(c.s);
    if (!span) return null;
    const parsed = parseEllRaw(span.raw);
    if (!parsed) return null;
    const rads = pts.filter(p => p.kind === 'rad' && (p.label === 'X半径' || p.label === 'Y半径') && p.s >= span.st && p.s < span.ed);
    const xr = rads.find(p => p.axis === 'x'), yr = rads.find(p => p.axis === 'y');
    return {
      role: c.axis === 'y' ? 'y' : 'x', span, parsed, idx, xr, yr,
      rx: xr ? xr.x : parsed.rx,
      ry: yr ? yr.x : parsed.ry,
      rot: c.rot != null ? c.rot : parsed.rot,
      cx: c.cx, cy: c.cy
    };
  }
  if (c.kind !== 'abs' && c.kind !== 'xyz') return null;
  const span = ellStmtAt(c.s);
  if (!span) return null;
  const parsed = parseEllRaw(span.raw);
  if (!parsed) return null;
  const rads = pts.filter(p => p.kind === 'rad' && (p.label === 'X半径' || p.label === 'Y半径') && p.s >= span.st && p.s < span.ed);
  const xr = rads.find(p => p.axis === 'x'), yr = rads.find(p => p.axis === 'y');
  return {
    role: 'c', span, parsed,
    cx: c.x, cy: c.y,
    rx: xr ? xr.x : parsed.rx,
    ry: yr ? yr.x : parsed.ry,
    rot: (xr && xr.rot != null) ? xr.rot : parsed.rot,
    idx, xr, yr
  };
}
function writeEllStmt(info, cx, cy, rx, ry, rot) {
  const a = radNum(Math.max(0.02, +rx)), b = radNum(Math.max(0.02, +ry)), th = radNum(+rot || 0);
  const cen = `(${radNum(cx)},${radNum(cy)})`;
  const body = Math.abs(th) < 1e-6
    ? `\\draw ${cen} ellipse (${a} and ${b});`
    : `\\draw ${cen} ellipse [x radius=${a}, y radius=${b}, rotate=${th}];`;
  const indent = (info.span.raw.match(/^[ \t]*/) || [''])[0];
  const text = $('code').value;
  $('code').value = text.slice(0, info.span.st) + indent + body + (info.span.raw.endsWith('\n') ? '\n' : '') + text.slice(info.span.ed);
  go(true);
}
function circStmtAt(pos) {
  const text = $('code').value;
  let st = text.lastIndexOf('\n', Math.max(0, pos - 1));
  st = st < 0 ? 0 : st + 1;
  let ed = text.indexOf(';', pos);
  if (ed < 0) ed = text.length; else ed++;
  const raw = text.slice(st, ed);
  if (!/\bcircle\b/.test(raw) || /\bellipse\b/.test(raw)) return null;
  return { st, ed, raw };
}
function findCircAt(idx) {
  const c = pts[idx];
  if (!c || c.s == null) return null;
  if (c.kind === 'rad' && c.label === '半径' && c.cx != null) {
    const span = circStmtAt(c.s);
    if (!span) return null;
    return { role: 'r', span, cx: c.cx, cy: c.cy, R: c.x * (c.xs || 1), idx, rad: c };
  }
  if (c.kind !== 'abs' && c.kind !== 'xyz') return null;
  if (findEllAt(idx)) return null;
  const span = circStmtAt(c.s);
  if (!span) return null;
  const rad = pts.find(p => p.kind === 'rad' && p.label === '半径' && p.s >= span.st && p.s < span.ed);
  if (!rad) return null;
  return { role: 'c', span, cx: c.x, cy: c.y, R: rad.x * (rad.xs || 1), idx, rad };
}
function ellHandleEnds(cx, cy, rx, ry, rot, xSign, ySign) {
  const axes = ellAxes(rot);
  return {
    xEnd: [cx + axes.ux * rx * (xSign < 0 ? -1 : 1), cy + axes.uy * rx * (xSign < 0 ? -1 : 1)],
    yEnd: [cx + axes.vx * ry * (ySign < 0 ? -1 : 1), cy + axes.vy * ry * (ySign < 0 ? -1 : 1)]
  };
}
function shapeGhostSvg() {
  let g = $('ov').querySelector('.shape-ghost');
  if (!g) {
    g = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    g.setAttribute('class', 'ghost-line shape-ghost');
    $('ov').appendChild(g);
  }
  g.replaceChildren();
  return g;
}
function paintEllGhost(cx, cy, rx, ry, rot, xSign, ySign) {
  if (!cal) return;
  const z = +$('zm').value;
  const pos = (x, y) => { const [px, py] = tikzToPage(x, y); return { x: px * z, y: py * z }; };
  const ends = ellHandleEnds(cx, cy, rx, ry, rot, xSign, ySign);
  const C = pos(cx, cy), X = pos(ends.xEnd[0], ends.xEnd[1]), Y = pos(ends.yEnd[0], ends.yEnd[1]);
  const svg = shapeGhostSvg();
  const ns = 'http://www.w3.org/2000/svg';
  [[C, X], [C, Y]].forEach(([a, b]) => {
    const ln = document.createElementNS(ns, 'line');
    ln.setAttribute('x1', a.x); ln.setAttribute('y1', a.y); ln.setAttribute('x2', b.x); ln.setAttribute('y2', b.y);
    svg.appendChild(ln);
  });
  const srx = Math.hypot(X.x - C.x, X.y - C.y), sry = Math.hypot(Y.x - C.x, Y.y - C.y);
  if (srx > 1 && sry > 1) {
    const ell = document.createElementNS(ns, 'ellipse');
    ell.setAttribute('class', 'rim');
    ell.setAttribute('cx', C.x); ell.setAttribute('cy', C.y);
    ell.setAttribute('rx', srx); ell.setAttribute('ry', sry);
    ell.setAttribute('transform', `rotate(${Math.atan2(X.y - C.y, X.x - C.x) * 180 / Math.PI} ${C.x} ${C.y})`);
    svg.appendChild(ell);
  }
  return ends;
}
function paintCircGhost(cx, cy, R) {
  if (!cal || !(R > 0.02)) return;
  const z = +$('zm').value;
  const pos = (x, y) => { const [px, py] = tikzToPage(x, y); return { x: px * z, y: py * z }; };
  const C = pos(cx, cy), E = pos(cx + R, cy);
  const svg = shapeGhostSvg();
  const ns = 'http://www.w3.org/2000/svg';
  const rim = document.createElementNS(ns, 'circle');
  rim.setAttribute('class', 'rim');
  rim.setAttribute('cx', C.x); rim.setAttribute('cy', C.y);
  rim.setAttribute('r', Math.max(1, Math.hypot(E.x - C.x, E.y - C.y)));
  svg.appendChild(rim);
  const ln = document.createElementNS(ns, 'line');
  ln.setAttribute('x1', C.x); ln.setAttribute('y1', C.y); ln.setAttribute('x2', E.x); ln.setAttribute('y2', E.y);
  svg.appendChild(ln);
}
function arcStmtAt(pos) {
  const text = $('code').value;
  let st = text.lastIndexOf('\n', Math.max(0, pos - 1));
  st = st < 0 ? 0 : st + 1;
  let ed = text.indexOf(';', pos);
  if (ed < 0) ed = text.length; else ed++;
  const raw = text.slice(st, ed);
  if (!/\barc\s*\(/.test(raw)) return null;
  return { st, ed, raw };
}
function parseArcRaw(raw) {
  const m = raw.match(/arc\s*\(\s*([-+]?\d*\.?\d+)\s*:\s*([-+]?\d*\.?\d+)\s*:\s*([-+]?\d*\.?\d+)/i);
  if (!m) return null;
  const polar = raw.match(/\+\+\s*\(\s*([-+]?\d*\.?\d+)\s*:\s*([-+]?\d*\.?\d+)/);
  return { a0: +m[1], a1: +m[2], r: +m[3], hasPolar: !!polar };
}
function arcEnds(cx, cy, a0, a1, r) {
  const toRad = d => d * Math.PI / 180;
  return {
    start: [cx + r * Math.cos(toRad(a0)), cy + r * Math.sin(toRad(a0))],
    end: [cx + r * Math.cos(toRad(a1)), cy + r * Math.sin(toRad(a1))]
  };
}
function findArcAt(idx) {
  const c = pts[idx];
  if (!c || c.s == null) return null;
  const span = arcStmtAt(c.s);
  if (!span) return null;
  const parsed = parseArcRaw(span.raw);
  if (!parsed) return null;
  const arcPt = pts.find(p => p.kind === 'arc' && p.s >= span.st && p.s < span.ed);
  const polarPt = pts.find(p => p.kind === 'polar' && p.s >= span.st && p.s < span.ed);
  const absPts = pts.filter(p => (p.kind === 'abs' || p.kind === 'xyz') && p.s >= span.st && p.e <= span.ed).sort((a, b) => a.s - b.s);
  let cx = null, cy = null, a0 = parsed.a0, a1 = parsed.a1, r = Math.max(0.02, parsed.r);
  if (arcPt) {
    if (arcPt.cx != null) { cx = arcPt.cx; cy = arcPt.cy; }
    if (arcPt.a0 != null) a0 = arcPt.a0;
    a1 = arcPt.x;
    r = Math.max(0.02, arcPt.y * (arcPt.ys || 1));
  }
  if (polarPt) {
    if (cx == null && polarPt.bx != null) { cx = polarPt.bx; cy = polarPt.by; }
    a0 = polarPt.x;
    r = Math.max(0.02, polarPt.y * (polarPt.ys || 1));
  }
  if (cx == null && parsed.hasPolar && absPts[0]) { cx = absPts[0].x; cy = absPts[0].y; }
  while (a1 <= a0 + 1e-6) a1 += 360;
  if (c.kind === 'arc') {
    return { role: 'end', span, parsed, a0, a1, r, cx, cy, idx, arcPt, polarPt };
  }
  if (c.kind === 'polar' && polarPt && pts.indexOf(polarPt) === idx) {
    return { role: 'start', span, parsed, a0, a1, r, cx: c.bx != null ? c.bx : cx, cy: c.by != null ? c.by : cy, idx, arcPt, polarPt };
  }
  if ((c.kind === 'abs' || c.kind === 'xyz') && parsed.hasPolar && absPts[0] && pts.indexOf(absPts[0]) === idx) {
    return { role: 'c', span, parsed, a0, a1, r, cx: c.x, cy: c.y, idx, arcPt, polarPt };
  }
  if ((c.kind === 'abs' || c.kind === 'xyz') && !parsed.hasPolar && absPts[0] && pts.indexOf(absPts[0]) === idx) {
    return { role: 'start', span, parsed, a0, a1, r, cx, cy, idx, arcPt, polarPt, classic: true };
  }
  return null;
}
function writeArcStmt(info, cx, cy, a0, a1, r) {
  const indent = (info.span.raw.match(/^[ \t]*/) || [''])[0];
  const body = arcDimCode([cx, cy], a0, a1, r);
  const text = $('code').value;
  $('code').value = text.slice(0, info.span.st) + indent + body + (info.span.raw.endsWith('\n') ? '\n' : '') + text.slice(info.span.ed);
  go(true);
}
function paintArcGhost(cx, cy, a0, a1, r) {
  if (!cal || cx == null || !(r > 0.02)) return null;
  let aa = a0, bb = a1;
  while (bb <= aa + 1e-6) bb += 360;
  const ends = arcEnds(cx, cy, aa, bb, r);
  const z = +$('zm').value;
  const pos = (x, y) => { const [px, py] = tikzToPage(x, y); return { x: px * z, y: py * z }; };
  const C = pos(cx, cy), S = pos(ends.start[0], ends.start[1]), E = pos(ends.end[0], ends.end[1]);
  const svg = shapeGhostSvg();
  const ns = 'http://www.w3.org/2000/svg';
  [[C, S], [C, E]].forEach(([a, b]) => {
    const ln = document.createElementNS(ns, 'line');
    ln.setAttribute('x1', a.x); ln.setAttribute('y1', a.y); ln.setAttribute('x2', b.x); ln.setAttribute('y2', b.y);
    svg.appendChild(ln);
  });
  const steps = Math.max(8, Math.ceil((bb - aa) / 5));
  const toRad = d => d * Math.PI / 180;
  for (let i = 0; i < steps; i++) {
    const t0 = aa + (bb - aa) * i / steps, t1 = aa + (bb - aa) * (i + 1) / steps;
    const A = pos(cx + r * Math.cos(toRad(t0)), cy + r * Math.sin(toRad(t0)));
    const B = pos(cx + r * Math.cos(toRad(t1)), cy + r * Math.sin(toRad(t1)));
    const ln = document.createElementNS(ns, 'line');
    ln.setAttribute('class', 'rim');
    ln.setAttribute('x1', A.x); ln.setAttribute('y1', A.y); ln.setAttribute('x2', B.x); ln.setAttribute('y2', B.y);
    svg.appendChild(ln);
  }
  return { ...ends, a0: aa, a1: bb, r };
}
function rectStmtAt(pos) {
  const text = $('code').value;
  let st = text.lastIndexOf('\n', Math.max(0, pos - 1));
  st = st < 0 ? 0 : st + 1;
  let ed = text.indexOf(';', pos);
  if (ed < 0) ed = text.length; else ed++;
  const raw = text.slice(st, ed);
  if (!/\brectangle\b/i.test(raw)) return null;
  return { st, ed, raw };
}
function findRectAt(idx) {
  const c = pts[idx];
  if (!c || c.s == null || (c.kind !== 'abs' && c.kind !== 'xyz')) return null;
  const span = rectStmtAt(c.s);
  if (!span) return null;
  const rel = span.raw.search(/\brectangle\b/i);
  if (rel < 0) return null;
  const rectPos = span.st + rel;
  const corners = pts.filter(p => (p.kind === 'abs' || p.kind === 'xyz') && p.s >= span.st && p.e <= span.ed && p.wx != null)
    .sort((a, b) => a.s - b.s);
  const a = corners.filter(p => p.e <= rectPos).pop();
  const b = corners.find(p => p.s >= rectPos + 9);
  if (!a || !b) return null;
  const aIdx = pts.indexOf(a), bIdx = pts.indexOf(b);
  if (idx !== aIdx && idx !== bIdx) return null;
  return { span, idx, role: idx === aIdx ? 'a' : 'b', aIdx, bIdx, a, b };
}
function paintRectGhost(x1, y1, x2, y2) {
  if (!cal) return;
  const z = +$('zm').value;
  const pos = (x, y) => { const [px, py] = tikzToPage(x, y); return { x: px * z, y: py * z }; };
  const corners = [pos(x1, y1), pos(x2, y1), pos(x2, y2), pos(x1, y2)];
  const svg = shapeGhostSvg();
  const poly = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
  poly.setAttribute('class', 'rim');
  poly.setAttribute('points', corners.map(p => p.x + ',' + p.y).join(' '));
  svg.appendChild(poly);
}
function findLineAt(idx) {
  const c = pts[idx];
  if (!c || c.s == null || (c.kind !== 'abs' && c.kind !== 'xyz') || c.wx == null) return null;
  const segs = straightSegs().filter(s => s.i0 === idx || s.i1 === idx);
  if (!segs.length) return null;
  return { idx, segs };
}
function drawOrthoStmtAt(pos) {
  const text = $('code').value;
  let st = text.lastIndexOf('\n', Math.max(0, pos - 1));
  st = st < 0 ? 0 : st + 1;
  let ed = text.indexOf(';', pos);
  if (ed < 0) ed = text.length; else ed++;
  const raw = text.slice(st, ed);
  if (!/\\draw\b/.test(raw) || !/--/.test(raw)) return null;
  return { st, ed, raw };
}
function findOrthoPolyAt(idx) {
  const c = pts[idx];
  if (!c || c.s == null || c.wx == null || (c.kind !== 'abs' && c.kind !== 'xyz')) return null;
  const span = drawOrthoStmtAt(c.s);
  if (!span) return null;
  const segs = straightSegs().filter(s => {
    if (s.i0 !== idx && s.i1 !== idx) return false;
    const o = pts[s.i0 === idx ? s.i1 : s.i0];
    return o && o.wx != null && o.s >= span.st && o.s < span.ed;
  });
  if (!segs.length) return null;
  const neighbors = segs.map(s => {
    const j = s.i0 === idx ? s.i1 : s.i0, o = pts[j];
    return { i: j, wx: o.wx, wy: o.wy };
  });
  return { span, segs, neighbors, idx };
}
function findPolyArrowAt(idx) { return findOrthoPolyAt(idx); }
function orthoSnapEnabled() {
  const el = $('ortho-sn');
  return !el || !!el.checked;
}
function orthoSnapPoly(wx, wy, neighbors, degTol) {
  if (!orthoSnapEnabled()) return { x: wx, y: wy };
  const tol = degTol == null ? 12 : degTol;
  let hx = null, hy = null, hScore = Infinity, vScore = Infinity;
  (neighbors || []).forEach(n => {
    const dx = wx - n.wx, dy = wy - n.wy;
    const ang = Math.abs(Math.atan2(dy, dx) * 180 / Math.PI);
    const aH = Math.min(ang, 180 - ang), aV = Math.abs(90 - ang);
    if (aH <= tol && aH <= aV) {
      const sc = Math.abs(dy);
      if (sc < hScore) { hScore = sc; hy = n.wy; }
    } else if (aV <= tol) {
      const sc = Math.abs(dx);
      if (sc < vScore) { vScore = sc; hx = n.wx; }
    }
  });
  return { x: hx != null ? hx : wx, y: hy != null ? hy : wy };
}
function snapPolyPlacePoint(x, y, ref) {
  if (!place || !place.poly || ref || !orthoSnapEnabled()) return { x: +Number(x).toFixed(3), y: +Number(y).toFixed(3), ref: ref || '' };
  const prev = [...place.pts].reverse().find(Boolean);
  if (!prev) return { x: +Number(x).toFixed(3), y: +Number(y).toFixed(3), ref: '' };
  const sn = orthoSnapPoly(+x, +y, [{ wx: prev[0], wy: prev[1] }]);
  return { x: +sn.x.toFixed(3), y: +sn.y.toFixed(3), ref: '' };
}
function paintLineGhost(segs) {
  if (!cal || !segs || !segs.length) return;
  const z = +$('zm').value;
  const pos = (x, y) => { const [px, py] = tikzToPage(x, y); return { x: px * z, y: py * z }; };
  const svg = shapeGhostSvg();
  const ns = 'http://www.w3.org/2000/svg';
  segs.forEach(([a, b]) => {
    const A = pos(a[0], a[1]), B = pos(b[0], b[1]);
    const ln = document.createElementNS(ns, 'line');
    ln.setAttribute('x1', A.x); ln.setAttribute('y1', A.y);
    ln.setAttribute('x2', B.x); ln.setAttribute('y2', B.y);
    svg.appendChild(ln);
  });
}
function axesScopeSpan(text, pos) {
  return markedScopeSpan(text, pos, 'ax2') || markedScopeSpan(text, pos, 'ax3');
}
function ax2ScopeSpan(text, pos) { return axesScopeSpan(text, pos); }
function parseAxesRaw(raw) {
  const hm = raw.match(/\\begin\{scope\}\s*\[([^\]]*)\]/);
  if (!hm) return null;
  const opt = hm[1];
  const kindM = raw.match(/%\s*(ax2|ax3)\b/);
  const kind = kindM ? kindM[1] : 'ax2';
  const sh = opt.match(/shift\s*=\s*\{\s*\(\s*([-+]?\d*\.?\d+)\s*,\s*([-+]?\d*\.?\d+)\s*(?:,\s*([-+]?\d*\.?\d+)\s*)?\)\s*\}/);
  const rotM = opt.match(/rotate\s*=\s*([-+]?\d*\.?\d+)/);
  const scM = opt.match(/(?:^|,\s*)scale\s*=\s*([-+]?\d*\.?\d+)/);
  const lxM = raw.match(/--\+\+\s*\(\s*([-+]?\d*\.?\d+)\s*,\s*0(?:\s*,\s*0)?\s*\)/);
  const lyM = raw.match(/--\+\+\s*\(\s*0\s*,\s*([-+]?\d*\.?\d+)(?:\s*,\s*0)?\s*\)/);
  const lzM = raw.match(/--\+\+\s*\(\s*0\s*,\s*0\s*,\s*([-+]?\d*\.?\d+)\s*\)/);
  return {
    header: hm[0],
    kind,
    shift: [sh ? +sh[1] : 0, sh ? +sh[2] : 0],
    rot: rotM ? +rotM[1] : 0,
    scale: scM ? +scM[1] : 1,
    lx: lxM ? Math.max(0.05, +lxM[1]) : (kind === 'ax3' ? 1.2 : 1.35),
    ly: lyM ? Math.max(0.05, +lyM[1]) : (kind === 'ax3' ? 1.25 : 1.35),
    lz: lzM ? Math.max(0.05, +lzM[1]) : (kind === 'ax3' ? 1.35 : 0)
  };
}
function axesTipOffsets(members) {
  if (!members.length) return { ow: 0, oh: 0, tips: [] };
  const origins = members.filter(({ p }) =>
    (p.kind === 'abs' || p.kind === 'xyz') &&
    Math.abs(p.x) < 1e-6 && Math.abs(p.y) < 1e-6 && (p.z == null || Math.abs(p.z) < 1e-6));
  const o = (origins[0] || members[0]).p;
  const tips = [], seen = new Set([(+o.wx).toFixed(3) + ',' + (+o.wy).toFixed(3)]);
  members.forEach(({ p }) => {
    const k = (+p.wx).toFixed(3) + ',' + (+p.wy).toFixed(3);
    if (seen.has(k)) return;
    seen.add(k);
    tips.push([p.wx - o.wx, p.wy - o.wy]);
  });
  return { ow: o.wx, oh: o.wy, tips };
}
function findAxesAt(idx) {
  const c = pts[idx];
  if (!c || c.s == null) return null;
  const span = axesScopeSpan($('code').value, c.s);
  if (!span) return null;
  const raw = $('code').value.slice(span[0], span[1]);
  const parsed = parseAxesRaw(raw);
  if (!parsed) return null;
  const members = pts.map((p, i) => ({ p, i })).filter(({ p }) => p.wx != null && p.s != null && p.s >= span[0] && p.s < span[1]);
  return { span, raw, idx, members, tips: axesTipOffsets(members), ...parsed };
}
function findAx2At(idx) { return findAxesAt(idx); }
function axesHeader(kind, shift, rot, scale) {
  const parts = [`shift={(${radNum(shift[0])},${radNum(shift[1])})}`];
  if (Math.abs(rot) > 1e-6) parts.push(`rotate=${radNum(rot)}`);
  if (Math.abs((scale || 1) - 1) > 1e-6) parts.push(`scale=${radNum(scale)}`);
  return `\\begin{scope}[${parts.join(', ')}] % ${kind === 'ax3' ? 'ax3' : 'ax2'}`;
}
function writeAxesScope(info, shift, rot, scale) {
  const text = $('code').value;
  const raw = text.slice(info.span[0], info.span[1]);
  const beginAt = raw.indexOf('\\begin{scope}');
  if (beginAt < 0) return;
  const hm = raw.slice(beginAt).match(/\\begin\{scope\}\s*\[[^\]]*\](?:\s*%[^\n]*)?/);
  if (!hm) return;
  const next = raw.slice(0, beginAt) + axesHeader(info.kind || 'ax2', shift, rot, scale) + raw.slice(beginAt + hm[0].length);
  $('code').value = text.slice(0, info.span[0]) + next + text.slice(info.span[1]);
  go(true);
}
function writeAx2Scope(info, shift, rot, scale) { writeAxesScope(info, shift, rot, scale); }
function paintAxesGhost(ox, oy, tipOffsets) {
  if (!cal || !tipOffsets || !tipOffsets.length) return;
  const z = +$('zm').value;
  const pos = (x, y) => { const [px, py] = tikzToPage(x, y); return { x: px * z, y: py * z }; };
  const O = pos(ox, oy);
  const svg = shapeGhostSvg();
  const ns = 'http://www.w3.org/2000/svg';
  tipOffsets.forEach(([dx, dy]) => {
    const T = pos(ox + dx, oy + dy);
    const ln = document.createElementNS(ns, 'line');
    ln.setAttribute('x1', O.x); ln.setAttribute('y1', O.y);
    ln.setAttribute('x2', T.x); ln.setAttribute('y2', T.y);
    svg.appendChild(ln);
  });
}
function paintAx2Ghost(ox, oy, lx, ly, rot, scale) {
  const th = (rot || 0) * Math.PI / 180, s = scale > 0 ? scale : 1;
  const cs = Math.cos(th), sn = Math.sin(th);
  paintAxesGhost(ox, oy, [
    [cs * lx * s, sn * lx * s],
    [-sn * ly * s, cs * ly * s]
  ]);
}
function clearShapeGhost() {
  shapeDrag = null;
  const g = $('ov').querySelector('.shape-ghost');
  if (g) g.remove();
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
function dimModeNow() {
  if (!place || !place.dim || place.dim.mode !== 'auto') return place && place.dim ? place.dim.mode : 'h';
  const p1 = place.pts[0], p2 = place.pts[1];
  const t = place.pts[2] || (placeHover ? [placeHover.x, placeHover.y] : null);
  if (!p1 || !p2 || !t) return 'h';
  const mx = (p1[0] + p2[0]) / 2, my = (p1[1] + p2[1]) / 2;
  return Math.abs(t[1] - my) >= Math.abs(t[0] - mx) ? 'h' : 'v';
}
function dimLength(p1, p2, mode) {
  const dx = p2[0] - p1[0], dy = p2[1] - p1[1];
  const n = mode === 'v' ? Math.abs(dy) : mode === 'a' ? Math.hypot(dx, dy) : Math.abs(dx);
  return String(Math.round(n * 1000) / 1000);
}
function setDimLabel(text) {
  const el = $('plab');
  if (!el || !place || !place.dim || place.dim.labelEdited) return;
  place.dim.filling = true; el.value = text; place.dim.filling = false;
}
function setDimMode(mode) {
  if (!place || !place.dim) return;
  place.dim.mode = mode;
  if (place.pts[0] && place.pts[1] && place.pts[2]) setDimLabel(dimLength(place.pts[0], place.pts[1], mode));
  placeTitle(); paintPlace();
}
function setDimArrow(arrow) {
  if (!place || !place.dim) return;
  place.dim.arrow = arrow; placeTitle(); paintPlace();
}
function syncDimButtons() {
  if (!place || !place.dim) return;
  const mode = dimModeNow();
  ['h', 'v', 'a'].forEach(k => { const b = $('dim-' + k); if (b) b.classList.toggle('dimon', k === mode); });
  const inn = $('dim-in'), out = $('dim-out');
  if (inn) inn.classList.toggle('dimon', place.dim.arrow !== 'out');
  if (out) out.classList.toggle('dimon', place.dim.arrow === 'out');
  const hide = place.dim.hide || '';
  const s1 = $('dim-s1'), s2 = $('dim-s2');
  if (s1) s1.classList.toggle('dimon', hide.includes('1'));
  if (s2) s2.classList.toggle('dimon', hide.includes('2'));
}
function toggleDimSide(side) {
  if (!place || !place.dim) return;
  const hide = place.dim.hide || '';
  place.dim.hide = (hide.includes(side) ? hide.replace(side, '') : hide + side).split('').sort().join('');
  placeTitle(); paintPlace();
}
function pointerTikz(clientX, clientY) {
  const ov = $('ov').getBoundingClientRect(), z = +$('zm').value;
  return pageToTikz((clientX - ov.left) / z, (clientY - ov.top) / z);
}
function tikzTol(px) {
  const z = +$('zm').value;
  const [dx, dy] = pageDeltaToTikz(px / z, 0);
  return Math.max(Math.hypot(dx, dy), 0.04);
}
function polyDist(x, y, poly) {
  let best = Infinity;
  for (let i = 1; i < poly.length; i++) {
    const ax = poly[i - 1][0], ay = poly[i - 1][1], bx = poly[i][0], by = poly[i][1];
    const dx = bx - ax, dy = by - ay, L2 = dx * dx + dy * dy || 1;
    let u = ((x - ax) * dx + (y - ay) * dy) / L2;
    u = Math.max(0, Math.min(1, u));
    best = Math.min(best, Math.hypot(x - (ax + dx * u), y - (ay + dy * u)));
  }
  return best;
}
function curvePolyline(p) {
  const arc = p.kind === 'arc';
  const r = (arc ? p.y : p.x) * ((arc ? p.ys : p.xs) || 1);
  const a0 = arc ? +p.a0 : 0;
  const a1 = arc ? +p.x : a0 + 360;
  const sweep = a1 - a0;
  const n = Math.max(16, Math.ceil(Math.abs(sweep) / 6));
  const out = [];
  for (let i = 0; i <= n; i++) {
    const a = (a0 + sweep * i / n) * Math.PI / 180;
    const [vx, vy] = mapVec(p, r * Math.cos(a), r * Math.sin(a), false);
    out.push([p.cx + vx, p.cy + vy]);
  }
  return out;
}
function parseAt(expr) {
  const m = String(expr || '').match(/^\(\s*([+-]?\d*\.?\d+)\s*,\s*([+-]?\d*\.?\d+)\s*(?:,\s*([+-]?\d*\.?\d+))?\s*\)$/);
  if (!m) return null;
  return { x: +m[1], y: +m[2], z: m[3] == null ? null : +m[3] };
}
function curveRecord(p, idx) {
  const got = parseAt(p.cen);
  const full = p.kind !== 'arc' || Math.abs((+p.x) - (+p.a0)) >= 359.9;
  return {
    idx, cen: p.cen, rr: +p.rr,
    a0: full ? null : +p.a0, a1: full ? null : +p.x,
    ox: got ? got.x : p.cx, oy: got ? got.y : p.cy, oz: got ? got.z : null,
    wx: p.cx, wy: p.cy, rVis: Math.hypot(p.wx - p.cx, p.wy - p.cy)
  };
}
function solve33(M, b) {
  const a = M[0], c = M[1], d = M[2];
  const det = a[0] * (c[1] * d[2] - c[2] * d[1]) - a[1] * (c[0] * d[2] - c[2] * d[0]) + a[2] * (c[0] * d[1] - c[1] * d[0]);
  if (Math.abs(det) < 1e-12) return null;
  const dx = b[0] * (c[1] * d[2] - c[2] * d[1]) - a[1] * (b[1] * d[2] - c[2] * b[2]) + a[2] * (b[1] * d[1] - c[1] * b[2]);
  const dy = a[0] * (b[1] * d[2] - c[2] * b[2]) - b[0] * (c[0] * d[2] - c[2] * d[0]) + a[2] * (c[0] * b[2] - b[1] * d[0]);
  const dz = a[0] * (c[1] * b[2] - b[1] * d[1]) - a[1] * (c[0] * b[2] - b[1] * d[0]) + b[0] * (c[0] * d[1] - c[1] * d[0]);
  return [dx / det, dy / det, dz / det];
}
function fitAxis(rows, rhs) {
  const A = [[0, 0, 0], [0, 0, 0], [0, 0, 0]], b = [0, 0, 0];
  rows.forEach((r, i) => { for (let j = 0; j < 3; j++) { b[j] += r[j] * rhs[i]; for (let k = 0; k < 3; k++) A[j][k] += r[j] * r[k]; } });
  return solve33(A, b);
}
function angBasis(segs, meet) {
  const e1 = vunit(vsub(segs[0].s1, segs[0].s0));
  const n = vunit(meet.n), e2 = e1 && n ? vunit(vcross(n, e1)) : null;
  return e1 && e2 ? { e1, e2 } : null;
}
function angFit(segs, meet) {
  const basis = angBasis(segs, meet);
  if (!basis) return null;
  const planeOf = src => { const d = vsub(src, meet.o); return [vdot(d, basis.e1), vdot(d, basis.e2)]; };
  const rows = [], xs = [], ys = [];
  segs.forEach(s => [[s.s0, s.w0], [s.s1, s.w1]].forEach(([src, w]) => {
    if (!w || w[0] == null) return;
    const [px, py] = planeOf(src);
    rows.push([px, py, 1]); xs.push(w[0]); ys.push(w[1]);
  }));
  if (rows.length < 3) return null;
  const X = fitAxis(rows, xs), Y = fitAxis(rows, ys);
  if (!X || !Y) return null;
  const det = X[0] * Y[1] - X[1] * Y[0];
  return {
    toView: src => { const [px, py] = planeOf(src); return [X[0] * px + X[1] * py + X[2], Y[0] * px + Y[1] * py + Y[2]]; },
    invert: view => {
      if (Math.abs(det) < 1e-8) return null;
      const rx = view[0] - X[2], ry = view[1] - Y[2];
      const px = (rx * Y[1] - X[1] * ry) / det, py = (X[0] * ry - rx * Y[0]) / det;
      return vadd(meet.o, vadd(vmul(basis.e1, px), vmul(basis.e2, py)));
    }
  };
}
function commentedAt(code, pos) {
  const line = code.slice(code.lastIndexOf('\n', pos) + 1, pos);
  for (let i = 0; i < line.length; i++) if (line[i] === '%' && (i === 0 || line[i - 1] !== '\\')) return true;
  return false;
}
function inDimScope(code, pos) {
  return udimScopeSpan(code, pos) || markedScopeSpan(code, pos, 'rdim') || markedScopeSpan(code, pos, 'ddim') || markedScopeSpan(code, pos, 'adim');
}
function segSrc(p) {
  if (!p) return null;
  if (p.kind === 'xyz') return [p.x, p.y, p.z || 0];
  if (p.kind === 'abs') return [p.x + (p.sx || 0), p.y + (p.sy || 0), 0];
  if (p.kind === 'anchor' && p.base) {
    const code = $('code').value;
    const m = code.match(new RegExp('\\\\coordinate \\(' + p.base.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\) at (\\([^;]*\\))'));
    const at = m && parseAt(m[1]);
    if (at) return [at.x, at.y, at.z || 0];
  }
  if (p.wx != null) return [p.wx, p.wy, 0];
  return null;
}
function pointCovering(pos) {
  let best = null;
  pts.forEach((p, i) => {
    if (p.s == null || pos < p.s || pos >= p.e) return;
    if ((p.kind !== 'abs' && p.kind !== 'xyz' && p.kind !== 'anchor') || p.wx == null) return;
    if (!best || p.e - p.s < best.p.e - best.p.s) best = { p, i };
  });
  return best;
}
function straightSegs() {
  const code = $('code').value, out = [], re = /\(([^()]+)\)\s*--\s*\(([^()]+)\)/g;
  let m;
  while ((m = re.exec(code))) {
    if (commentedAt(code, m.index) || inDimScope(code, m.index)) continue;
    const a = pointCovering(m.index), b = pointCovering(m.index + m[0].lastIndexOf('('));
    if (!a || !b || a.i === b.i) continue;
    const s0 = segSrc(a.p), s1 = segSrc(b.p);
    if (!s0 || !s1 || vlen(vsub(s1, s0)) < 1e-4 || a.p.wx == null || b.p.wx == null) continue;
    out.push({ i0: a.i, i1: b.i, s0, s1, w0: [a.p.wx, a.p.wy], w1: [b.p.wx, b.p.wy] });
  }
  return out;
}
function sameSeg(a, b) { return !!a && !!b && ((a.i0 === b.i0 && a.i1 === b.i1) || (a.i0 === b.i1 && a.i1 === b.i0)); }
function pickSeg(clientX, clientY) {
  if (!cal) return null;
  const [x, y] = pointerTikz(clientX, clientY), tol = tikzTol(12);
  let best = null, bestD = tol;
  straightSegs().forEach(seg => {
    const dx = seg.w1[0] - seg.w0[0], dy = seg.w1[1] - seg.w0[1], L2 = dx * dx + dy * dy || 1;
    let u = ((x - seg.w0[0]) * dx + (y - seg.w0[1]) * dy) / L2;
    u = Math.max(0, Math.min(1, u));
    const d = Math.hypot(x - (seg.w0[0] + dx * u), y - (seg.w0[1] + dy * u));
    if (d < bestD) { bestD = d; best = Object.assign({}, seg, { t: u, snap: vadd(seg.s0, vmul(vsub(seg.s1, seg.s0), u)) }); }
  });
  return best;
}
function angDir(seg, o) { const d = vsub(seg.snap, o); return vlen(d) > 1e-5 ? d : vsub(seg.s1, seg.s0); }
function angGeom(segs, meet, view) {
  const fit = angFit(segs, meet);
  const text = (fit && fit.invert(view)) || [view[0], view[1], 0];
  const wedge = angWedge(meet.o, angDir(segs[0], meet.o), angDir(segs[1], meet.o), text);
  if (!wedge || !wedge.e2) return null;
  const useZ = segs.some(s => Math.abs(s.s0[2]) > 1e-9 || Math.abs(s.s1[2]) > 1e-9) || Math.abs(meet.o[2]) > 1e-9;
  return { o: meet.o, a: segs[0].snap, b: segs[1].snap, u: vadd(meet.o, vmul(wedge.r1, wedge.R)), v: vadd(meet.o, vmul(wedge.r2, wedge.R)), t: wedge.text, e1: wedge.e1, e2: wedge.e2, ang: wedge.ang, R: wedge.R, useZ, fit };
}
function acceptSeg(hit) {
  const segs = place.ang.segs;
  if (segs.some(s => sameSeg(s, hit))) return;
  if (segs.length === 1) {
    const meet = angMeet(segs[0].s0, vsub(segs[0].s1, segs[0].s0), hit.s0, vsub(hit.s1, hit.s0));
    if (!meet.ok) { setStatus(meet.why === 'par' ? 'angpar' : 'angskew'); paintPlace(); return; }
    place.ang.meet = meet;
  }
  segs.push(hit);
  place.hoverSeg = null;
  if (segs.length >= 2) paintPlaceForm();
  else { placeTitle(); paintPlace(); }
}
function setAngArrow(arrow) {
  if (!place || !place.ang) return;
  place.ang.arrow = arrow;
  const inn = $('ang-in'), out = $('ang-out');
  if (inn) inn.classList.toggle('dimon', arrow !== 'out');
  if (out) out.classList.toggle('dimon', arrow === 'out');
  paintPlace();
}
function paintAngPlace(pos) {
  const drawLine = (a, b) => {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'ghost-line ghost-dim');
    const ln = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    const A = pos(a[0], a[1]), B = pos(b[0], b[1]);
    ln.setAttribute('x1', A.x); ln.setAttribute('y1', A.y); ln.setAttribute('x2', B.x); ln.setAttribute('y2', B.y);
    svg.appendChild(ln); $('ov').appendChild(svg);
  };
  const show = seg => { if (seg && seg.w0) drawLine(seg.w0, seg.w1); };
  place.ang.segs.forEach(show);
  if (place.hoverSeg && !place.ang.segs.some(s => sameSeg(s, place.hoverSeg))) show(place.hoverSeg);
  const text = place.pts[0] || (place.ang.segs.length === 2 && placeHover ? [placeHover.x, placeHover.y] : null);
  if (place.ang.segs.length < 2 || !place.ang.meet || !text) return;
  const g = angGeom(place.ang.segs, place.ang.meet, text);
  if (!g || !g.fit) return;
  const samples = [];
  for (let i = 0; i <= 28; i++) {
    const th = g.ang * i / 28;
    samples.push(g.fit.toView(vadd(g.o, vadd(vmul(g.e1, Math.cos(th) * g.R), vmul(g.e2, Math.sin(th) * g.R)))));
  }
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', 'ghost-line ghost-dim');
  for (let i = 1; i < samples.length; i++) {
    const A = pos(samples[i - 1][0], samples[i - 1][1]), B = pos(samples[i][0], samples[i][1]);
    const ln = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    ln.setAttribute('x1', A.x); ln.setAttribute('y1', A.y); ln.setAttribute('x2', B.x); ln.setAttribute('y2', B.y);
    svg.appendChild(ln);
  }
  const start = samples[0], end = samples[samples.length - 1], prev = samples[samples.length - 2], nxt = samples[1];
  if (place.ang.arrow === 'out') {
    const away = (tip, inner) => { const dx = tip[0] - inner[0], dy = tip[1] - inner[1], L = Math.hypot(dx, dy) || 1; return [tip[0] + dx / L * 0.35, tip[1] + dy / L * 0.35]; };
    const sOut = away(start, nxt), eOut = away(end, prev);
    paintArrow(svg, pos(sOut[0], sOut[1]), pos(start[0], start[1]));
    paintArrow(svg, pos(eOut[0], eOut[1]), pos(end[0], end[1]));
  } else {
    paintArrow(svg, pos(nxt[0], nxt[1]), pos(start[0], start[1]));
    paintArrow(svg, pos(prev[0], prev[1]), pos(end[0], end[1]));
  }
  $('ov').appendChild(svg);
  drawLine(g.fit.toView(g.a), g.fit.toView(g.u));
  drawLine(g.fit.toView(g.b), g.fit.toView(g.v));
  const lab = document.createElement('div'); lab.className = 'ghost-lab';
  const typed = $('plab') && $('plab').value;
  lab.textContent = !typed || typed === angLabel(g.ang) ? (radNum(g.ang * 180 / Math.PI) + '°') : typed;
  const tp = pos(text[0], text[1]);
  lab.style.left = tp.x + 'px'; lab.style.top = tp.y + 'px'; $('ov').appendChild(lab);
  if (place.pts[0]) {
    const mark = document.createElement('div'); mark.className = 'ghost'; mark.textContent = 'T';
    mark.style.left = tp.x + 'px'; mark.style.top = tp.y + 'px'; $('ov').appendChild(mark);
  }
}
function circTouch(cx, cy, ox, oy, r) {
  const dx = ox - cx, dy = oy - cy, d = Math.hypot(dx, dy);
  if (d < 1e-4 || !(r > 1e-4)) return null;
  const R = Math.abs(d - r);
  if (R < 0.02) return null;
  const s = d >= r ? R / d : -R / d;
  return { R, tx: cx + dx * s, ty: cy + dy * s };
}
function lineTouch(cx, cy, ax, ay, bx, by) {
  const dx = bx - ax, dy = by - ay, L2 = dx * dx + dy * dy;
  if (L2 < 1e-8) return null;
  const u = ((cx - ax) * dx + (cy - ay) * dy) / L2;
  const tx = ax + dx * u, ty = ay + dy * u, R = Math.hypot(cx - tx, cy - ty);
  if (R < 0.02) return null;
  return { R, tx, ty };
}
function drawCurve(p) {
  return (p.kind === 'arc' && p.cx != null) || (p.kind === 'rad' && p.label === '半径' && p.cx != null);
}
function circSnap(clientX, clientY) {
  const c = place && place.pts[0];
  if (!c || !cal) return null;
  const [mx, my] = pointerTikz(clientX, clientY);
  const ptTol = tikzTol(14), edgeTol = tikzTol(12);
  let best = null;
  pts.forEach(p => {
    if (!pointShown(p) || p.wx == null || p.kind === 'rad') return;
    const d = Math.hypot(mx - p.wx, my - p.wy);
    if (d > ptTol) return;
    const R = Math.hypot(p.wx - c[0], p.wy - c[1]);
    if (R < 0.02) return;
    if (!best || d < best.d) best = { d, R, tx: p.wx, ty: p.wy, kind: 'pt' };
  });
  ports.forEach(p => {
    if (p.wx == null || p.anchor === 'center') return;
    const d = Math.hypot(mx - p.wx, my - p.wy);
    if (d > ptTol) return;
    const R = Math.hypot(p.wx - c[0], p.wy - c[1]);
    if (R < 0.02) return;
    if (!best || d < best.d) best = { d, R, tx: p.wx, ty: p.wy, kind: 'pt' };
  });
  if (best) return best;
  const code = $('code').value;
  straightSegs().forEach(seg => {
    const dx = seg.w1[0] - seg.w0[0], dy = seg.w1[1] - seg.w0[1], L2 = dx * dx + dy * dy || 1;
    let u = ((mx - seg.w0[0]) * dx + (my - seg.w0[1]) * dy) / L2;
    u = Math.max(0, Math.min(1, u));
    const d = Math.hypot(mx - (seg.w0[0] + dx * u), my - (seg.w0[1] + dy * u));
    if (d > edgeTol) return;
    const hit = lineTouch(c[0], c[1], seg.w0[0], seg.w0[1], seg.w1[0], seg.w1[1]);
    if (!hit || (best && d >= best.d)) return;
    best = Object.assign({ d, kind: 'line', seg }, hit);
  });
  pts.forEach((p, idx) => {
    if (!drawCurve(p) || p.s == null || inDimScope(code, p.s)) return;
    const poly = curvePolyline(p), d = polyDist(mx, my, poly);
    if (d > edgeTol) return;
    const hit = circTouch(c[0], c[1], p.cx, p.cy, Math.hypot(p.wx - p.cx, p.wy - p.cy) || +p.rr);
    if (!hit) return;
    if (p.kind === 'arc' && Math.abs((+p.x) - (+p.a0)) < 359.9 && polyDist(hit.tx, hit.ty, poly) > Math.max(0.05, (+p.rr || 0) * 0.04)) return;
    if (best && d >= best.d) return;
    best = Object.assign({ d, kind: 'curve', idx }, hit);
  });
  if (best) return best;
  const w = pickWorld(clientX, clientY);
  const R = Math.hypot(w.x - c[0], w.y - c[1]);
  if (R < 0.02) return null;
  return { d: Infinity, R, tx: w.x, ty: w.y, kind: 'free' };
}
function pickCurve(clientX, clientY) {
  if (!cal) return null;
  const [x, y] = pointerTikz(clientX, clientY), tol = tikzTol(12);
  let best = null, bestD = tol;
  pts.forEach((p, idx) => {
    const curve = (p.kind === 'arc' && p.cx != null) || (p.kind === 'rad' && p.label === '半径' && p.cx != null);
    if (!curve || p.rr == null || !p.cen) return;
    const d = polyDist(x, y, curvePolyline(p));
    if (d < bestD) { bestD = d; best = curveRecord(p, idx); }
  });
  return best;
}
function paintArrow(svg, a, b) {
  const ns = 'http://www.w3.org/2000/svg';
  const ln = document.createElementNS(ns, 'line');
  ln.setAttribute('x1', a.x); ln.setAttribute('y1', a.y); ln.setAttribute('x2', b.x); ln.setAttribute('y2', b.y);
  svg.appendChild(ln);
  const dx = b.x - a.x, dy = b.y - a.y, L = Math.hypot(dx, dy) || 1;
  const ux = dx / L, uy = dy / L, back = { x: b.x - ux * 11, y: b.y - uy * 11 };
  [[back.x - uy * 4, back.y + ux * 4], [back.x + uy * 4, back.y - ux * 4]].forEach(pt => {
    const head = document.createElementNS(ns, 'line');
    head.setAttribute('x1', b.x); head.setAttribute('y1', b.y); head.setAttribute('x2', pt[0]); head.setAttribute('y2', pt[1]);
    svg.appendChild(head);
  });
}
function paintRdimPlace(pos) {
  const src = place.curve ? pts[place.curve.idx] : null;
  const hover = place.hoverCurve ? pts[place.hoverCurve.idx] : null;
  const show = p => {
    if (!p || p.cx == null) return;
    const poly = curvePolyline(p);
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'ghost-line ghost-dim');
    for (let i = 1; i < poly.length; i++) {
      const a = pos(poly[i - 1][0], poly[i - 1][1]), b = pos(poly[i][0], poly[i][1]);
      const ln = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      ln.setAttribute('x1', a.x); ln.setAttribute('y1', a.y); ln.setAttribute('x2', b.x); ln.setAttribute('y2', b.y);
      svg.appendChild(ln);
    }
    $('ov').appendChild(svg);
  };
  if (hover && (!src || hover !== src)) show(hover);
  if (src) show(src);
  const text = place.pts[0] || (place.curve && placeHover ? [placeHover.x, placeHover.y] : null);
  if (place.curve && text) {
    const [rx, ry] = radRim(place.curve.wx, place.curve.wy, place.curve.rVis || place.curve.rr, text[0], text[1], place.curve.a0, place.curve.a1);
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'ghost-line ghost-dim');
    paintArrow(svg, pos(text[0], text[1]), pos(rx, ry));
    $('ov').appendChild(svg);
    const lab = document.createElement('div'); lab.className = 'ghost-lab';
    lab.textContent = ($('plab') && $('plab').value) || String(radNum(place.curve.rr));
    const tp = pos(text[0], text[1]);
    lab.style.left = tp.x + 'px'; lab.style.top = tp.y + 'px'; $('ov').appendChild(lab);
  }
  if (place.pts[0]) {
    const g = document.createElement('div'); g.className = 'ghost'; g.textContent = 'T';
    const tp = pos(place.pts[0][0], place.pts[0][1]);
    g.style.left = tp.x + 'px'; g.style.top = tp.y + 'px'; $('ov').appendChild(g);
  }
}
function paintDiaAt(svg, pos, cx, cy, R, tx, ty) {
  const ends = diaEnds(cx, cy, R, tx, ty);
  paintArrow(svg, pos(cx, cy), pos(ends.near[0], ends.near[1]));
  paintArrow(svg, pos(cx, cy), pos(ends.far[0], ends.far[1]));
  if (!ends.outside) return;
  const a = pos(ends.near[0], ends.near[1]), b = pos(tx, ty);
  const ln = document.createElementNS('http://www.w3.org/2000/svg', 'line');
  ln.setAttribute('x1', a.x); ln.setAttribute('y1', a.y); ln.setAttribute('x2', b.x); ln.setAttribute('y2', b.y);
  svg.appendChild(ln);
}
function paintDdimPlace(pos) {
  const src = place.curve ? pts[place.curve.idx] : null;
  const hover = place.hoverCurve ? pts[place.hoverCurve.idx] : null;
  const show = p => {
    if (!p || p.cx == null) return;
    const poly = curvePolyline(p);
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'ghost-line ghost-dim');
    for (let i = 1; i < poly.length; i++) {
      const a = pos(poly[i - 1][0], poly[i - 1][1]), b = pos(poly[i][0], poly[i][1]);
      const ln = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      ln.setAttribute('x1', a.x); ln.setAttribute('y1', a.y); ln.setAttribute('x2', b.x); ln.setAttribute('y2', b.y);
      svg.appendChild(ln);
    }
    $('ov').appendChild(svg);
  };
  if (hover && (!src || hover !== src)) show(hover);
  if (src) show(src);
  const text = place.pts[0] || (place.curve && placeHover ? [placeHover.x, placeHover.y] : null);
  if (place.curve && text) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'ghost-line ghost-dim');
    paintDiaAt(svg, pos, place.curve.wx, place.curve.wy, place.curve.rVis || place.curve.rr, text[0], text[1]);
    $('ov').appendChild(svg);
    const lab = document.createElement('div'); lab.className = 'ghost-lab';
    const typed = $('plab') && $('plab').value;
    lab.textContent = !typed || typed === diaLabel(place.curve.rr) ? ('⌀' + radNum(2 * place.curve.rr)) : typed;
    const tp = pos(text[0], text[1]);
    lab.style.left = tp.x + 'px'; lab.style.top = tp.y + 'px'; $('ov').appendChild(lab);
  }
  if (place.pts[0]) {
    const g = document.createElement('div'); g.className = 'ghost'; g.textContent = 'T';
    const tp = pos(place.pts[0][0], place.pts[0][1]);
    g.style.left = tp.x + 'px'; g.style.top = tp.y + 'px'; $('ov').appendChild(g);
  }
}
function paintCircPlace(pos) {
  const c = place.pts[0];
  const ns = 'http://www.w3.org/2000/svg';
  if (c) {
    const g = document.createElement('div');
    g.className = 'ghost'; g.textContent = '1';
    const s = pos(c[0], c[1]);
    g.style.left = s.x + 'px'; g.style.top = s.y + 'px';
    $('ov').appendChild(g);
  }
  const hit = place.circHit;
  const typing = document.activeElement && document.activeElement.id === 'pf-r';
  const typed = parseFloat($('pf-r') && $('pf-r').value);
  const R = typing ? typed : (hit ? hit.R : typed);
  if (hit && !typing && hit.kind === 'line' && hit.seg) {
    const svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('class', 'ghost-line ghost-dim');
    const a = pos(hit.seg.w0[0], hit.seg.w0[1]), b = pos(hit.seg.w1[0], hit.seg.w1[1]);
    const ln = document.createElementNS(ns, 'line');
    ln.setAttribute('x1', a.x); ln.setAttribute('y1', a.y); ln.setAttribute('x2', b.x); ln.setAttribute('y2', b.y);
    svg.appendChild(ln); $('ov').appendChild(svg);
  }
  if (hit && !typing && hit.kind === 'curve' && pts[hit.idx]) {
    const poly = curvePolyline(pts[hit.idx]);
    const svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('class', 'ghost-line ghost-dim');
    for (let i = 1; i < poly.length; i++) {
      const a = pos(poly[i - 1][0], poly[i - 1][1]), b = pos(poly[i][0], poly[i][1]);
      const ln = document.createElementNS(ns, 'line');
      ln.setAttribute('x1', a.x); ln.setAttribute('y1', a.y); ln.setAttribute('x2', b.x); ln.setAttribute('y2', b.y);
      svg.appendChild(ln);
    }
    $('ov').appendChild(svg);
  }
  if (!c || !(R > 0.02)) return;
  const C = pos(c[0], c[1]), E = pos(c[0] + R, c[1]);
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('class', 'ghost-line');
  const rim = document.createElementNS(ns, 'circle');
  rim.setAttribute('class', 'rim');
  rim.setAttribute('cx', C.x); rim.setAttribute('cy', C.y); rim.setAttribute('r', Math.max(1, Math.hypot(E.x - C.x, E.y - C.y)));
  svg.appendChild(rim);
  if (hit && !typing && hit.tx != null) {
    const T = pos(hit.tx, hit.ty);
    const ln = document.createElementNS(ns, 'line');
    ln.setAttribute('x1', C.x); ln.setAttribute('y1', C.y); ln.setAttribute('x2', T.x); ln.setAttribute('y2', T.y);
    svg.appendChild(ln);
    const tip = document.createElementNS(ns, 'circle');
    tip.setAttribute('class', 'tip');
    tip.setAttribute('cx', T.x); tip.setAttribute('cy', T.y); tip.setAttribute('r', '3.5');
    svg.appendChild(tip);
  }
  $('ov').appendChild(svg);
}
function paintEllPlace(pos) {
  const c = place.pts[0], xpt = place.pts[1];
  const live = place.pts[2] || (c && xpt && placeHover ? [placeHover.x, placeHover.y] : null);
  const g = c && xpt ? ellGeom(c, xpt, live) : (c && placeHover ? ellGeom(c, [placeHover.x, placeHover.y], null) : null);
  const ns = 'http://www.w3.org/2000/svg';
  const mark = (p, lab) => {
    if (!p) return;
    const d = document.createElement('div');
    d.className = 'ghost'; d.textContent = lab;
    const s = pos(p[0], p[1]);
    d.style.left = s.x + 'px'; d.style.top = s.y + 'px';
    $('ov').appendChild(d);
  };
  mark(c, '1');
  if (g) {
    mark(g.xEnd, 'X');
    if (live || place.pts[2]) mark(g.yEnd, 'Y');
    const C = pos(c[0], c[1]), X = pos(g.xEnd[0], g.xEnd[1]), Y = pos(g.yEnd[0], g.yEnd[1]);
    const svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('class', 'ghost-line');
    const ax = document.createElementNS(ns, 'line');
    ax.setAttribute('x1', C.x); ax.setAttribute('y1', C.y); ax.setAttribute('x2', X.x); ax.setAttribute('y2', X.y);
    svg.appendChild(ax);
    if (live || place.pts[2]) {
      const ay = document.createElementNS(ns, 'line');
      ay.setAttribute('x1', C.x); ay.setAttribute('y1', C.y); ay.setAttribute('x2', Y.x); ay.setAttribute('y2', Y.y);
      svg.appendChild(ay);
    }
    const rx = Math.hypot(X.x - C.x, X.y - C.y), ry = Math.hypot(Y.x - C.x, Y.y - C.y);
    if (rx > 1 && ry > 1) {
      const ell = document.createElementNS(ns, 'ellipse');
      ell.setAttribute('class', 'rim');
      ell.setAttribute('cx', C.x); ell.setAttribute('cy', C.y);
      ell.setAttribute('rx', rx); ell.setAttribute('ry', ry);
      const screenAng = Math.atan2(X.y - C.y, X.x - C.x) * 180 / Math.PI;
      ell.setAttribute('transform', `rotate(${screenAng} ${C.x} ${C.y})`);
      svg.appendChild(ell);
    }
    $('ov').appendChild(svg);
  } else mark(place.pts[1], '2');
}
function paintPolyPlace(pos) {
  const pts = place.pts.filter(Boolean);
  const live = placeHover ? [placeHover.x, placeHover.y] : null;
  const chain = live ? pts.concat([live]) : pts.slice();
  const ns = 'http://www.w3.org/2000/svg';
  if (place.n >= 1) ports.forEach(p => {
    if (p.wx == null || p.anchor === 'center') return;
    const d = document.createElement('div'); d.className = 'port'; d.title = '(' + p.ref + ')';
    const s = pos(p.wx, p.wy); d.style.left = s.x + 'px'; d.style.top = s.y + 'px';
    d.onmousedown = e => {
      e.preventDefault(); e.stopPropagation();
      if (e.button === 2) { confirmPlace(); return; }
      putPlace(p.wx, p.wy, p.ref);
    };
    $('ov').appendChild(d);
  });
  if (chain.length >= 2) {
    const svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('class', 'ghost-line');
    const spots = chain.map(p => pos(p[0], p[1]));
    for (let i = 1; i < spots.length; i++) {
      const ln = document.createElementNS(ns, 'line');
      ln.setAttribute('x1', spots[i - 1].x); ln.setAttribute('y1', spots[i - 1].y);
      ln.setAttribute('x2', spots[i].x); ln.setAttribute('y2', spots[i].y);
      svg.appendChild(ln);
    }
    const a = spots[spots.length - 2], b = spots[spots.length - 1];
    const dx = b.x - a.x, dy = b.y - a.y, L = Math.hypot(dx, dy) || 1;
    const ux = dx / L, uy = dy / L, bx = b.x - ux * 12, by = b.y - uy * 12, px = -uy * 5, py = ux * 5;
    [[b.x, b.y, bx + px, by + py], [b.x, b.y, bx - px, by - py]].forEach(seg => {
      const ln = document.createElementNS(ns, 'line');
      ln.setAttribute('x1', seg[0]); ln.setAttribute('y1', seg[1]);
      ln.setAttribute('x2', seg[2]); ln.setAttribute('y2', seg[3]);
      svg.appendChild(ln);
    });
    $('ov').appendChild(svg);
  }
  pts.forEach((p, i) => {
    const s = pos(p[0], p[1]);
    const d = document.createElement('div');
    d.className = 'ghost'; d.textContent = String(i + 1);
    d.style.left = s.x + 'px'; d.style.top = s.y + 'px';
    $('ov').appendChild(d);
  });
}
function paintArcPlace(pos) {
  const c = place.pts[0], start = place.pts[1];
  const live = place.pts[2] || (c && start && placeHover ? [placeHover.x, placeHover.y] : null);
  const g = c && start ? arcGeom(c, start, live) : null;
  const ns = 'http://www.w3.org/2000/svg';
  const mark = (p, lab) => {
    if (!p) return;
    const d = document.createElement('div');
    d.className = 'ghost'; d.textContent = lab;
    const s = pos(p[0], p[1]);
    d.style.left = s.x + 'px'; d.style.top = s.y + 'px';
    $('ov').appendChild(d);
  };
  mark(c, 'C');
  if (!c) return;
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('class', 'ghost-line');
  if (!start && placeHover) {
    const C = pos(c[0], c[1]), S = pos(placeHover.x, placeHover.y);
    const ln = document.createElementNS(ns, 'line');
    ln.setAttribute('x1', C.x); ln.setAttribute('y1', C.y); ln.setAttribute('x2', S.x); ln.setAttribute('y2', S.y);
    svg.appendChild(ln);
    const rr = Math.hypot(S.x - C.x, S.y - C.y);
    if (rr > 1) {
      const rim = document.createElementNS(ns, 'circle');
      rim.setAttribute('class', 'rim');
      rim.setAttribute('cx', C.x); rim.setAttribute('cy', C.y); rim.setAttribute('r', rr);
      svg.appendChild(rim);
    }
    $('ov').appendChild(svg);
    mark([placeHover.x, placeHover.y], 'S');
    return;
  }
  if (!g) { mark(start, 'S'); return; }
  mark(g.start, 'S');
  if (live || place.pts[2]) mark(g.end, 'E');
  const C = pos(c[0], c[1]), S = pos(g.start[0], g.start[1]), E = pos(g.end[0], g.end[1]);
  [[C, S], [C, E]].forEach(([a, b]) => {
    const ln = document.createElementNS(ns, 'line');
    ln.setAttribute('x1', a.x); ln.setAttribute('y1', a.y); ln.setAttribute('x2', b.x); ln.setAttribute('y2', b.y);
    svg.appendChild(ln);
  });
  const steps = Math.max(8, Math.ceil((g.a1 - g.a0) / 5));
  const toRad = d => d * Math.PI / 180;
  for (let i = 0; i < steps; i++) {
    const t0 = g.a0 + (g.a1 - g.a0) * i / steps, t1 = g.a0 + (g.a1 - g.a0) * (i + 1) / steps;
    const A = pos(c[0] + g.r * Math.cos(toRad(t0)), c[1] + g.r * Math.sin(toRad(t0)));
    const B = pos(c[0] + g.r * Math.cos(toRad(t1)), c[1] + g.r * Math.sin(toRad(t1)));
    const ln = document.createElementNS(ns, 'line');
    ln.setAttribute('class', 'rim');
    ln.setAttribute('x1', A.x); ln.setAttribute('y1', A.y); ln.setAttribute('x2', B.x); ln.setAttribute('y2', B.y);
    svg.appendChild(ln);
  }
  $('ov').appendChild(svg);
}
function paintPlace() {
  $('ov').querySelectorAll('.ghost,.ghost-line,.ghost-lab,.port').forEach(el => {
    if (el.classList.contains('shape-ghost')) return;
    el.remove();
  });
  if (!place || !cal) return;
  const z = +$('zm').value, pos = (x, y) => { const [px, py] = tikzToPage(x, y); return { x: px * z, y: py * z }; };
  if (place.adim) { paintAngPlace(pos); return; }
  if (place.curveDim) { (place.ddim ? paintDdimPlace : paintRdimPlace)(pos); return; }
  if (place.circ) { paintCircPlace(pos); return; }
  if (place.ell) { paintEllPlace(pos); return; }
  if (place.arc) { paintArcPlace(pos); return; }
  if (place.poly) { paintPolyPlace(pos); return; }
  const spots = place.pts.map(p => p ? pos(p[0], p[1]) : null);
  if (!place.pts[1] && spots[0] && placeHover) spots[1] = pos(placeHover.x, placeHover.y);
  if (place.n >= 1) ports.forEach(p => {
    if (p.wx == null || p.anchor === 'center') return;
    const d = document.createElement('div'); d.className = 'port'; d.title = '(' + p.ref + ')';
    const s = pos(p.wx, p.wy); d.style.left = s.x + 'px'; d.style.top = s.y + 'px';
    d.onmousedown = e => {
      e.preventDefault(); e.stopPropagation();
      if (e.button === 2) { confirmPlace(); return; }
      putPlace(p.wx, p.wy, p.ref);
    };
    $('ov').appendChild(d);
  });
  const tLive = place.dim && place.pts[0] && place.pts[1] ? (place.pts[2] || (placeHover ? [placeHover.x, placeHover.y] : null)) : null;
  if (tLive) paintDimFrame(place.pts[0], place.pts[1], tLive, pos);
  else if (spots[0] && spots[1]) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'ghost-line');
    if (place.rect) {
      const a = place.pts[0], b = place.pts[1] || [placeHover.x, placeHover.y];
      const corners = [pos(a[0], a[1]), pos(b[0], a[1]), pos(b[0], b[1]), pos(a[0], b[1])];
      const poly = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
      poly.setAttribute('class', 'rim');
      poly.setAttribute('points', corners.map(c => c.x + ',' + c.y).join(' '));
      svg.appendChild(poly);
    } else {
      const ln = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      ln.setAttribute('x1', spots[0].x); ln.setAttribute('y1', spots[0].y);
      ln.setAttribute('x2', spots[1].x); ln.setAttribute('y2', spots[1].y);
      svg.appendChild(ln);
    }
    $('ov').appendChild(svg);
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
function paintDimFrame(p1, p2, t, pos) {
  const mode = dimModeNow(), [d1, d2] = dimFeet(p1, p2, t, mode);
  const A = pos(p1[0], p1[1]), B = pos(p2[0], p2[1]), C = pos(d1[0], d1[1]), D = pos(d2[0], d2[1]), T = pos(t[0], t[1]);
  const pt = Math.max(1.2, Math.hypot(cal.xx, cal.xy) * +$('zm').value / 28.45);
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg'); svg.setAttribute('class', 'ghost-line ghost-dim');
  const seg = (a, b, ext) => {
    const ln = document.createElementNS(ns, 'line');
    ln.setAttribute('x1', a.x); ln.setAttribute('y1', a.y); ln.setAttribute('x2', b.x); ln.setAttribute('y2', b.y);
    if (ext) ln.setAttribute('class', 'ext'); svg.appendChild(ln);
  };
  const walk = (from, to, dist) => { const dx = to.x - from.x, dy = to.y - from.y, L = Math.hypot(dx, dy) || 1; return { x: from.x + dx / L * dist, y: from.y + dy / L * dist }; };
  const head = (tip, from) => { const back = walk(tip, from, 11), dx = tip.x - from.x, dy = tip.y - from.y, L = Math.hypot(dx, dy) || 1; const px = -dy / L * 4, py = dx / L * 4; seg(tip, { x: back.x + px, y: back.y + py }); seg(tip, { x: back.x - px, y: back.y - py }); };
  const hide = place.dim.hide || '', show1 = !hide.includes('1'), show2 = !hide.includes('2');
  const M = { x: (C.x + D.x) / 2, y: (C.y + D.y) / 2 };
  const from = show1 ? C : M, to = show2 ? D : M;
  if (show1 && Math.hypot(C.x - A.x, C.y - A.y) > 4) seg(walk(A, C, pt * 2), walk(C, A, -pt * 4), true);
  if (show2 && Math.hypot(D.x - B.x, D.y - B.y) > 4) seg(walk(B, D, pt * 2), walk(D, B, -pt * 4), true);
  if (place.dim.arrow === 'out') {
    const o1 = walk(C, D, -pt * 10), o2 = walk(D, C, -pt * 10);
    if (show1) { seg(o1, C); head(C, o1); }
    if (show2) { seg(o2, D); head(D, o2); }
    if (show1 || show2) seg(from, to);
  } else if (show1 || show2) { seg(from, to); if (show1) head(C, to); if (show2) head(D, from); }
  $('ov').appendChild(svg);
  const lab = document.createElement('div'); lab.className = 'ghost-lab';
  lab.textContent = ($('plab') && place.dim.labelEdited && $('plab').value) || dimLength(p1, p2, mode);
  lab.style.left = T.x + 'px'; lab.style.top = T.y + 'px'; $('ov').appendChild(lab);
  if (!place.pts[2]) {
    const g = document.createElement('div'); g.className = 'ghost'; g.textContent = 'T';
    g.style.left = T.x + 'px'; g.style.top = T.y + 'px'; $('ov').appendChild(g);
  }
}
function placeTitle() {
  if (place && place.ell) {
    const n = place.pts.filter(Boolean).length;
    if (n < 1) { $('place-title').textContent = t('椭圆线：点中心'); return; }
    if (n < 2) { $('place-title').textContent = t('椭圆线：点横轴端点'); return; }
    const g = place.pts[0] && place.pts[1] ? ellGeom(place.pts[0], place.pts[1], place.pts[2] || (placeHover ? [placeHover.x, placeHover.y] : null)) : null;
    $('place-title').textContent = t('椭圆线：点纵轴端点') + (g ? `  ${radNum(g.rx)}×${radNum(g.ry)} ∠${radNum(g.ang)}°` : '');
    return;
  }
  if (place && place.arc) {
    const n = place.pts.filter(Boolean).length;
    if (n < 1) { $('place-title').textContent = t('弧：点圆心'); return; }
    if (n < 2) {
      const r = placeHover ? Math.hypot(placeHover.x - place.pts[0][0], placeHover.y - place.pts[0][1]) : 0;
      $('place-title').textContent = t('弧：点起点') + (r > 0.02 ? `  R=${radNum(r)}` : '');
      return;
    }
    const g = place.pts[0] && place.pts[1] ? arcGeom(place.pts[0], place.pts[1], place.pts[2] || (placeHover ? [placeHover.x, placeHover.y] : null)) : null;
    $('place-title').textContent = t('弧：点终点') + (g ? `  ${radNum(g.a0)}°→${radNum(g.a1)}°  R=${radNum(g.r)}` : '');
    return;
  }
  if (place && place.poly) {
    const n = place.pts.filter(Boolean).length;
    const refs = place.pts.filter(Boolean).map(p => p.ref ? `(${p.ref})` : '').filter(Boolean).join(' → ');
    if (n < 1) { $('place-title').textContent = t('折线箭头：点起点'); return; }
    $('place-title').textContent = t('折线箭头：继续点转折点，右键或确认结束') + `  (${n}` + tf('点', ' pts') + ')' + (refs ? ' ' + refs : '');
    return;
  }
  if (place && place.circ) {
    if (!place.pts[0]) { $('place-title').textContent = t('圆：点圆心'); return; }
    const hit = place.circHit;
    const r = hit ? radNum(hit.R) : (($('pf-r') && $('pf-r').value) || '');
    const how = hit && hit.kind === 'line' ? t('切直线') : hit && hit.kind === 'curve' ? t('切圆/弧') : hit && hit.kind === 'pt' ? t('过点') : '';
    $('place-title').textContent = t('圆：点第二点或切线') + (how ? ' · ' + how : '') + (r ? '  R=' + r : '');
    return;
  }
  if (place && place.adim) {
    const nseg = place.ang.segs.length;
    if (nseg < 1) { $('place-title').textContent = t('角度：点第一条直线'); return; }
    if (nseg < 2) { $('place-title').textContent = t('角度：点第二条直线'); return; }
    $('place-title').textContent = place.pts[0] ? t('角度：改文字后回车确认') : t('角度：点文字位置');
    return;
  }
  if (place && place.curveDim) {
    const kind = place.ddim ? '直径' : '半径';
    if (!place.curve) { $('place-title').textContent = t(kind + '：点圆弧或圆'); return; }
    $('place-title').textContent = place.pts[0] ? t(kind + '：改文字后回车确认') : t(kind + '：点文字位置');
    return;
  }
  if (place && place.dim) {
    syncDimButtons();
    const got = place.pts.filter(Boolean).length;
    const mode = t({ h: '水平', v: '竖直', a: '对齐' }[dimModeNow()]);
    const arrow = t(place.dim.arrow === 'out' ? '箭头在外' : '箭头在内');
    if (got < 1) { $('place-title').textContent = t('尺寸：点起点'); return; }
    if (got < 2) { $('place-title').textContent = t('尺寸：点终点'); return; }
    const len = place.pts[0] && place.pts[1] ? ' ' + dimLength(place.pts[0], place.pts[1], dimModeNow()) : '';
    $('place-title').textContent = got < 3 ? tf(`尺寸：点文字位置（${mode}，${arrow}）${len}。H 水平，V 竖直，R 对齐，I 内，O 外，1 抑起点，2 抑终点`, `Dimension: click the text (${mode}, ${arrow})${len}. H horizontal, V vertical, R aligned, I inside, O outside, 1 hide start, 2 hide end`) : t('尺寸：改文字后回车确认');
    return;
  }
  const spec = PLACE[place.key], got = place.pts.filter(Boolean).length, name = t(spec.name);
  const refs = place.pts.map(p => p && p.ref ? `(${p.ref})` : '').filter(Boolean).join(' → ');
  if (!spec.n) { $('place-title').textContent = tf(`添加${spec.name}：填好后点确认`, `Add ${name}: fill in the fields, then confirm`); return; }
  $('place-title').textContent = got >= spec.n ? tf(`添加${spec.name}：${refs || '改好坐标后点确认'}`, `Add ${name}: ${refs || 'edit the coordinates, then confirm'}`) : tf(`添加${spec.name}：在画布上点击 ${got}/${spec.n} 个点${refs ? ' ' + refs : ''}`, `Add ${name}: click ${got}/${spec.n} points on the canvas${refs ? ' ' + refs : ''}`);
}
function putPlace(x, y, ref) {
  if (!place || !place.n) return;
  if (x && typeof x === 'object') { ref = x.ref; y = x.y; x = x.x; }
  if (place.poly) {
    const sn = snapPolyPlacePoint(x, y, ref);
    x = sn.x; y = sn.y; ref = sn.ref;
  }
  let idx = place.pts.findIndex(p => p == null);
  if (idx < 0) {
    if (place.poly) {
      place.pts.push(null);
      place.n = place.pts.length;
      idx = place.n - 1;
    } else idx = place.n - 1;
  }
  const fresh = place.pts[idx] == null;
  let p = [+Number(x).toFixed(3), +Number(y).toFixed(3)];
  if (place.ell && idx === 2 && place.pts[0] && place.pts[1]) {
    const g = ellGeom(place.pts[0], place.pts[1], [+x, +y]);
    if (!g) return;
    p = [+g.yEnd[0].toFixed(3), +g.yEnd[1].toFixed(3)];
  }
  if (place.arc && idx === 2 && place.pts[0] && place.pts[1]) {
    const g = arcGeom(place.pts[0], place.pts[1], [+x, +y]);
    if (!g) return;
    p = [+g.end[0].toFixed(3), +g.end[1].toFixed(3)];
  }
  if (ref) p.ref = ref;
  place.pts[idx] = p;
  if (place.poly && place.pts.every(Boolean)) {
    place.pts.push(null);
    place.n = place.pts.length;
    paintPlaceForm();
    placeHover = null;
    return;
  }
  if ($('px' + idx)) { $('px' + idx).value = p[0]; $('py' + idx).value = p[1]; }
  const tag = $('pr' + idx); if (tag) tag.textContent = ref ? `(${ref})` : '';
  placeHover = null;
  if (place.adim && idx === 0 && fresh && place.ang.meet && $('plab')) {
    const g = angGeom(place.ang.segs, place.ang.meet, p);
    if (g) { $('plab').value = angLabel(g.ang); $('plab').focus(); $('plab').select(); }
  }
  if (place.curveDim && idx === 0 && fresh && place.curve && $('plab')) {
    $('plab').value = place.ddim ? diaLabel(place.curve.rr) : String(radNum(place.curve.rr));
    $('plab').focus(); $('plab').select();
  }
  if (place.dim && idx === 2 && place.pts[0] && place.pts[1]) {
    setDimLabel(dimLength(place.pts[0], place.pts[1], dimModeNow()));
    if (fresh && $('plab')) { $('plab').focus(); $('plab').select(); }
  }
  if (place.circ && idx === 0 && fresh) {
    place.circHit = null;
    if ($('pf-r')) $('pf-r').value = '';
  }
  if (place.ell && idx === 2 && fresh) {
    placeTitle(); paintPlace();
    confirmPlace();
    return;
  }
  if (place.arc && idx === 2 && fresh) {
    placeTitle(); paintPlace();
    confirmPlace();
    return;
  }
  placeTitle(); paintPlace();
}
function readPlaceInputs() {
  if (!place) return;
  for (let i = 0; i < place.n; i++) {
    if (!$('px' + i) || !$('py' + i)) continue;
    const x = parseFloat($('px' + i).value), y = parseFloat($('py' + i).value);
    const prev = place.pts[i];
    if (!Number.isFinite(x) || !Number.isFinite(y)) {
      if (!(place.poly && i === place.n - 1 && !String($('px' + i).value || '').trim() && !String($('py' + i).value || '').trim())) {
        place.pts[i] = null; if ($('pr' + i)) $('pr' + i).textContent = '';
      }
      continue;
    }
    if (prev && prev.ref && Math.abs(prev[0] - x) < 1e-6 && Math.abs(prev[1] - y) < 1e-6) continue;
    place.pts[i] = [x, y];
    if ($('pr' + i)) $('pr' + i).textContent = '';
  }
  if (place.dim && place.pts[0] && place.pts[1] && place.pts[2]) setDimLabel(dimLength(place.pts[0], place.pts[1], dimModeNow()));
  placeTitle(); paintPlace();
}
function paintPlaceForm() {
  const spec = PLACE[place.key];
  const box = $('place-fields');
  const keep = {};
  box.querySelectorAll('input').forEach(el => { keep[el.id] = el.value; });
  box.innerHTML = '';
  const attr = s => String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;');
  if ((spec.rdim || spec.ddim) && !place.curve) { placeTitle(); paintPlace(); return; }
  if (spec.adim && place.ang.segs.length < 2) { placeTitle(); paintPlace(); return; }
  const val = (id, fallback) => Object.prototype.hasOwnProperty.call(keep, id) ? keep[id] : fallback;
  if (spec.adim) {
    const on = place.ang.arrow !== 'out';
    box.insertAdjacentHTML('beforeend', `<span>${t('箭头')}</span><button type="button" id="ang-in" class="sec${on ? ' dimon' : ''}">${t('内')}</button><button type="button" id="ang-out" class="sec${on ? '' : ' dimon'}">${t('外')}</button>`);
    $('ang-in').onclick = () => setAngArrow('in'); $('ang-out').onclick = () => setAngArrow('out');
  }
  if (spec.dim) {
    box.insertAdjacentHTML('beforeend', `<span>${t('方向')}</span><button type="button" id="dim-h" class="sec">${t('水平')}</button><button type="button" id="dim-v" class="sec">${t('竖直')}</button><button type="button" id="dim-a" class="sec">${t('对齐')}</button><span>${t('箭头')}</span><button type="button" id="dim-in" class="sec">${t('内')}</button><button type="button" id="dim-out" class="sec">${t('外')}</button><span>${t('抑制')}</span><button type="button" id="dim-s1" class="sec" title="${attr(t('不画起点一侧的箭头和引出线'))}">${t('抑起点')}</button><button type="button" id="dim-s2" class="sec" title="${attr(t('不画终点一侧的箭头和引出线'))}">${t('抑终点')}</button>`);
    $('dim-h').onclick = () => setDimMode('h'); $('dim-v').onclick = () => setDimMode('v'); $('dim-a').onclick = () => setDimMode('a');
    $('dim-in').onclick = () => setDimArrow('in'); $('dim-out').onclick = () => setDimArrow('out');
    $('dim-s1').onclick = () => toggleDimSide('1'); $('dim-s2').onclick = () => toggleDimSide('2');
  }
  if (spec.idField) {
    const idDef = val('pf-id', nextBlockId($('code').value));
    box.insertAdjacentHTML('beforeend', `<span>${t('代号')}</span><input id="pf-id" value="${attr(idDef)}"><b id="pid-msg" class="pid-msg"></b>`);
    $('pf-id').oninput = () => syncBlockIdMsg();
    $('pf-id').onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); confirmPlace(); } };
    syncBlockIdMsg();
  }
  if (spec.field) box.insertAdjacentHTML('beforeend', `<span>${t(spec.field)}</span><input id="plab" class="wide" placeholder="${spec.dim ? t('长度或 $L$') : ''}" value="${attr(val('plab', spec.def || ''))}">`);
  (spec.inputs || []).forEach(inp => {
    if (spec.idField && inp.id === 'id') return;
    const cls = inp.wide ? (inp.wide === true ? 'wide' : 'wide ' + inp.wide) : '';
    const lab = inp.id === 'tip' ? tf('线', 'Tip') : (inp.label === '点' ? tf('点', 'Points') : t(inp.label));
    box.insertAdjacentHTML('beforeend', `<span>${lab}</span><input id="pf-${inp.id}" class="${cls}" value="${attr(val('pf-' + inp.id, inp.def || ''))}">`);
    $('pf-' + inp.id).onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); confirmPlace(); } };
  });
  if (spec.n === 1 && spec.rot !== false) box.insertAdjacentHTML('beforeend', `<span>${t('角度')}</span><input id="prot" type="number" step="15" value="${attr(val('prot', '0'))}">`);
  const nShow = place.poly ? place.n : spec.n;
  for (let i = 0; i < nShow; i++) {
    const pointName = spec.dim ? [t('起点'), t('终点'), t('文字')][i] : spec.arc ? [t('圆心'), t('起点'), t('终点')][i] : (spec.rdim || spec.ddim || spec.adim) ? t('文字') : tf('点' + (i + 1), 'Point ' + (i + 1));
    const p = place.pts[i];
    box.insertAdjacentHTML('beforeend', `<span>${pointName} X</span><input id="px${i}" type="number" step="0.05" value="${p ? attr(p[0]) : ''}"><span>Y</span><input id="py${i}" type="number" step="0.05" value="${p ? attr(p[1]) : ''}"><b id="pr${i}" class="pref">${p && p.ref ? '(' + p.ref + ')' : ''}</b>`);
    $('px' + i).oninput = $('py' + i).oninput = readPlaceInputs;
    $('px' + i).onkeydown = $('py' + i).onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); confirmPlace(); } };
  }
  if ($('plab')) {
    $('plab').onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); confirmPlace(); } };
    $('plab').oninput = () => { if (place && place.dim && !place.dim.filling) place.dim.labelEdited = true; };
  }
  if ($('prot')) { $('prot').oninput = paintPlace; $('prot').onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); confirmPlace(); } }; }
  if (place.circ && $('pf-r')) $('pf-r').oninput = () => paintPlace();
  placeTitle(); paintPlace();
}
function startPlace(key) {
  const spec = PLACE[key]; if (!spec) return;
  place = { key, n: spec.n, pts: Array(spec.n).fill(null), dim: spec.dim === true ? { mode: 'auto', arrow: 'in', hide: '', labelEdited: false, filling: false } : null, rdim: !!spec.rdim, ddim: !!spec.ddim, adim: !!spec.adim, circ: !!spec.circ, ell: !!spec.ell, arc: !!spec.arc, poly: !!spec.poly, rect: !!spec.rect, circHit: null, curveDim: !!(spec.rdim || spec.ddim), curve: null, hoverCurve: null, ang: spec.adim ? { arrow: 'in', segs: [], meet: null } : null, hoverSeg: null }; placeHover = null;
  $('inputs').style.display = 'none'; activeIdx = -1; idleSel();
  $('place-fields').innerHTML = '';
  paintPlaceForm();
  $('place').style.display = 'inline-flex'; $('wrap').classList.toggle('placing', spec.n > 0);
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
  const usePts = place.poly ? place.pts.filter(Boolean) : place.pts;
  if (place.poly) {
    if (usePts.length < 2) { setStatus('needpts'); return; }
  } else if (spec.n && place.pts.some(p => !p)) { setStatus('needpts'); return; }
  let extra = spec.field ? $('plab').value : '';
  const rot = $('prot') ? (parseFloat($('prot').value) || 0) : 0;
  const vals = {}; (spec.inputs || []).forEach(inp => { const el = $('pf-' + inp.id); vals[inp.id] = el ? el.value : ''; });
  if (spec.idField) {
    const id = String(vals.id || ($('pf-id') && $('pf-id').value) || '').trim();
    vals.id = id;
    if (!syncBlockIdMsg()) {
      setStatus(!id ? 'badname' : (blockIdOk(id) ? 'dupname' : 'badname'));
      return;
    }
  }
  if (place.adim) {
    if (place.ang.segs.length < 2 || place.pts.some(p => !p)) { setStatus('needpts'); return; }
    const g = angGeom(place.ang.segs, place.ang.meet, place.pts[0]);
    if (!g) { setStatus('angpar'); return; }
    vals.geom = g; vals.arrow = place.ang.arrow;
    vals.id = ($('code').value.match(/% adim\b/g) || []).length + 1;
    if (!extra) extra = angLabel(g.ang);
  }
  if (place.curveDim) {
    if (!place.curve || place.pts.some(p => !p)) { setStatus('needpts'); return; }
    vals.curve = place.curve;
    const word = place.ddim ? 'ddim' : 'rdim';
    vals.id = ($('code').value.match(new RegExp('% ' + word + '\\b', 'g')) || []).length + 1;
    if (!extra) extra = place.ddim ? diaLabel(place.curve.rr) : String(radNum(place.curve.rr));
  }
  if (place.dim) {
    vals.mode = dimModeNow(); vals.arrow = place.dim.arrow; vals.hide = place.dim.hide || '';
    vals.id = ($('code').value.match(/\\begin\{scope\}[^\n]*\budim\b/g) || []).length + 1;
    if (!extra) extra = dimLength(place.pts[0], place.pts[1], vals.mode);
  }
  if (place.circ) {
    const R = parseFloat(vals.r);
    if (!(R > 0.02)) { setStatus('needpts'); return; }
    vals.r = String(radNum(R));
  }
  if (place.ell) {
    const g = ellGeom(place.pts[0], place.pts[1], place.pts[2]);
    if (!g) { setStatus('needpts'); return; }
    vals.rx = g.rx; vals.ry = g.ry; vals.ang = g.ang;
  }
  if (place.arc) {
    const g = arcGeom(place.pts[0], place.pts[1], place.pts[2]);
    if (!g) { setStatus('needpts'); return; }
    vals.a0 = g.a0; vals.a1 = g.a1; vals.r = g.r;
  }
  const snip = '\n  ' + spec.build(usePts, extra, rot, vals);
  endPlace(); appendSnip(snip, spec);
}
function appendSnip(s, spec) {
  const ta = $('code'); let v = ta.value || "\\begin{circuitikz}[european]\n\\end{circuitikz}";
  let i = spec && spec.panel === 'plot' ? v.lastIndexOf('\\end{axis}') : -1;
  if (i < 0) i = Math.max(v.lastIndexOf('\\end{circuitikz}'), v.lastIndexOf('\\end{tikzpicture}'));
  ta.value = i !== -1 ? v.slice(0, i).trimEnd() + s + "\n" + v.slice(i) : v + s; go(true);
}
function markedScopeSpan(text, pos, word) {
  const re = /\\begin\{scope\}|\\end\{scope\}/g;
  const stack = [];
  let m;
  while ((m = re.exec(text))) {
    if (m[0].charAt(1) === 'b') {
      const lineEnd = text.indexOf('\n', m.index);
      const line = text.slice(m.index, lineEnd === -1 ? text.length : lineEnd);
      const hit = /\\begin\{scope\}/.test(line) && new RegExp('\\b' + word + '\\b').test(line);
      stack.push({ at: m.index, hit });
    } else if (stack.length) {
      const top = stack.pop();
      const end = m.index + m[0].length;
      if (top.hit && pos >= top.at && pos < end) {
        let st = top.at;
        const lineStart = text.lastIndexOf('\n', st - 1) + 1;
        if (/^\s*$/.test(text.slice(lineStart, st))) st = lineStart;
        let ed = end;
        if (text.charAt(ed) === '\r') ed++;
        if (text.charAt(ed) === '\n') ed++;
        return [st, ed];
      }
    }
  }
  return null;
}
function udimScopeSpan(text, pos) { return markedScopeSpan(text, pos, 'udim'); }
function readUdim(text, span) {
  const raw = text.slice(span[0], span[1]);
  const indent = (raw.match(/^[ \t]*/) || [''])[0];
  const idm = raw.match(/\\coordinate \((d(\d+))a\) at /);
  if (!idm) return null;
  const id = idm[2];
  const atOf = suf => {
    const m = raw.match(new RegExp('\\\\coordinate \\(d' + id + suf + '\\) at (\\([^;]*\\));'));
    return m ? m[1] : null;
  };
  const a = atOf('a'), b = atOf('b'), t = atOf('t'), c = atOf('c'), d = atOf('d');
  if (!a || !b || !t || !c || !d) return null;
  const labm = raw.match(/\\node\[[^\]]*\] at \(\\udtx,\\udty\) \{([\s\S]*?)\};/);
  const label = labm ? labm[1] : '';
  const head = raw.match(/%\s*udim(?:\s+([hva]))?(?:\s+(in|out))?(?:\s+([12]+))?/);
  let mode = head && head[1], arrow = head && head[2], hide = head && head[3] ? head[3] : '';
  if (!arrow) arrow = /!-10pt!/.test(raw) ? 'out' : 'in';
  if (!mode) {
    const num = s => { const m = String(s).match(/^\(\s*([+-]?\d*\.?\d+)\s*,\s*([+-]?\d*\.?\d+)\s*\)$/); return m ? [+m[1], +m[2]] : null; };
    const pa = num(a), pc = num(c);
    if (pa && pc) {
      const dx = Math.abs(pc[0] - pa[0]), dy = Math.abs(pc[1] - pa[1]);
      mode = dx <= 1e-3 && dy <= 1e-3 ? 'h' : dx <= 1e-3 && dy > dx ? 'h' : dy <= 1e-3 && dx > dy ? 'v' : 'a';
    } else mode = 'h';
  }
  if (!(head && head[1]) && raw.includes('black!65')) {
    const has1 = /\\draw\[thin, black!65\][^\n]*\\udax/.test(raw);
    const has2 = /\\draw\[thin, black!65\][^\n]*\\udbx/.test(raw);
    hide = (has1 ? '' : '1') + (has2 ? '' : '2');
  }
  return { id, mode, arrow, hide, at: [a, b, t], feet: [c, d], label, indent };
}
function dimWorld(text, id, suf) {
  const marker = '\\coordinate (d' + id + suf + ')';
  const i = pts.findIndex(p => text.slice(text.lastIndexOf('\n', p.s) + 1, p.s).includes(marker));
  if (i < 0) return null;
  const p = pts[i];
  if (p.wx == null || p.wy == null) return null;
  return [p.wx, p.wy];
}
function hideDimEdit() {
  const el = $('dimedit');
  if (!el) return;
  el.style.display = 'none';
  el.classList.remove('rdim');
  el.classList.remove('ddim');
  el.classList.remove('adim');
}
function syncDimEdit(info) {
  ['h', 'v', 'a'].forEach(k => { const b = $('ed-' + k); if (b) b.classList.toggle('dimon', k === info.mode); });
  const inn = $('ed-in'), out = $('ed-out');
  if (inn) inn.classList.toggle('dimon', info.arrow !== 'out');
  if (out) out.classList.toggle('dimon', info.arrow === 'out');
  const s1 = $('ed-s1'), s2 = $('ed-s2');
  if (s1) s1.classList.toggle('dimon', info.hide.includes('1'));
  if (s2) s2.classList.toggle('dimon', info.hide.includes('2'));
  const lab = $('ed-lab');
  if (lab && document.activeElement !== lab) lab.value = info.label;
}
function lineAt(s) {
  const text = $('code').value;
  const end = text.indexOf('\n', s);
  return text.slice(text.lastIndexOf('\n', s) + 1, end < 0 ? text.length : end);
}
function dimNameRole(name) {
  const m = String(name || '').match(/^(rd|dd|ag)\d+([a-z][a-z0-9]*)$/);
  if (!m) return '';
  const rest = m[2];
  if (m[1] === 'ag' && rest !== 'u' && rest !== 'v' && rest !== 't' && rest !== 'm' && !/^[ctpabouv]$/.test(rest)) return 'k';
  if (rest === 'm' || /^[ctpabouv]$/.test(rest)) return rest;
  return '';
}
function radAnchorRole(idx) {
  const p = pts[idx];
  if (!p) return '';
  const base = p.kind === 'anchor' ? (p.base || '') : '';
  const fromBase = dimNameRole(base);
  if (fromBase) return (p.kind === 'anchor' && (fromBase === 't' || fromBase === 'u' || fromBase === 'v' || fromBase === 'm')) ? 'ta' : fromBase;
  const m = lineAt(p.s).match(/\\coordinate \(((?:rd|dd|ag)\d+[a-z][a-z0-9]*)\)/);
  return m ? dimNameRole(m[1]) : '';
}
function radLocked(idx) {
  const role = radAnchorRole(idx);
  if (role === 'c' || role === 'p' || role === 'a' || role === 'b' || role === 'o' || role === 'ta' || role === 'k') return true;
  const p = pts[idx];
  if (!p || p.s == null) return false;
  const line = lineAt(p.s);
  return /plane origin=|plane [xy]=/.test(line) && !!markedScopeSpan($('code').value, p.s, 'adim');
}
function readRdimAt(idx) {
  const c = pts[idx];
  if (!c) return null;
  const text = $('code').value;
  const span = markedScopeSpan(text, c.s, 'rdim');
  if (!span) return null;
  const raw = text.slice(span[0], span[1]);
  const idm = raw.match(/\\coordinate \((rd\d+)c\) at (\([^;]*\));/);
  if (!idm) return null;
  const tm = raw.match(new RegExp('\\\\coordinate \\(' + idm[1] + 't\\) at (\\([^;]*\\));'));
  const pm = raw.match(new RegExp('\\\\coordinate \\(' + idm[1] + 'p\\) at (\\([^;]*\\));'));
  if (!tm || !pm) return null;
  const head = raw.match(/%\s*rdim\s+([+-]?\d*\.?\d+)(?:\s+([+-]?\d*\.?\d+)\s+([+-]?\d*\.?\d+))?/);
  const labm = raw.match(new RegExp('\\\\node\\[[^\\]]*\\] at \\(' + idm[1] + 't\\) \\{([\\s\\S]*?)\\};'));
  const cen = parseAt(idm[2]);
  return {
    id: idm[1], span, cen: idm[2], center: cen, rr: head ? +head[1] : null,
    a0: head && head[2] != null ? +head[2] : null, a1: head && head[3] != null ? +head[3] : null,
    label: labm ? labm[1] : '', z: cen && cen.z != null ? cen.z : null
  };
}
function radMoveEdits(idx, fx, fy) {
  const info = readRdimAt(idx);
  if (!info || !info.center || info.rr == null) return null;
  const text = $('code').value;
  const it = coordIdx(text, info.id + 't'), ip = coordIdx(text, info.id + 'p');
  if (it < 0 || ip < 0) return null;
  const [px, py] = radRim(info.center.x, info.center.y, info.rr, fx, fy, info.a0, info.a1);
  const z = info.z;
  return [
    { s: pts[it].s, e: pts[it].e, txt: radPt(fx, fy, z) },
    { s: pts[ip].s, e: pts[ip].e, txt: radPt(px, py, z) }
  ];
}
function writeRadMove(idx, fx, fy) {
  const edits = radMoveEdits(idx, fx, fy);
  if (!edits) return false;
  let t = $('code').value;
  edits.sort((a, b) => b.s - a.s).forEach(ed => { t = t.slice(0, ed.s) + ed.txt + t.slice(ed.e); });
  $('code').value = t; go(true); return true;
}
function readDdimAt(idx) {
  const c = pts[idx];
  if (!c) return null;
  const text = $('code').value;
  const span = markedScopeSpan(text, c.s, 'ddim');
  if (!span) return null;
  const raw = text.slice(span[0], span[1]);
  const idm = raw.match(/\\coordinate \((dd\d+)c\) at (\([^;]*\));/);
  if (!idm) return null;
  const tm = raw.match(new RegExp('\\\\coordinate \\(' + idm[1] + 't\\) at (\\([^;]*\\));'));
  const am = raw.match(new RegExp('\\\\coordinate \\(' + idm[1] + 'a\\) at (\\([^;]*\\));'));
  const bm = raw.match(new RegExp('\\\\coordinate \\(' + idm[1] + 'b\\) at (\\([^;]*\\));'));
  if (!tm || !am || !bm) return null;
  const head = raw.match(/%\s*ddim\s+([+-]?\d*\.?\d+)/);
  const labm = raw.match(new RegExp('\\\\node\\[[^\\]]*\\] at \\(' + idm[1] + 't\\) \\{([\\s\\S]*?)\\};'));
  const cen = parseAt(idm[2]);
  return {
    id: idm[1], span, cen: idm[2], center: cen, rr: head ? +head[1] : null,
    label: labm ? labm[1] : '', z: cen && cen.z != null ? cen.z : null
  };
}
function diaScopeBody(info, fx, fy) {
  const text = $('code').value;
  const raw = text.slice(info.span[0], info.span[1]);
  const indent = (raw.match(/^[ \t]*/) || [''])[0];
  const code = diaDimCode({ cen: info.cen, ox: info.center.x, oy: info.center.y, oz: info.z, rr: info.rr }, [fx, fy], info.label, info.id.slice(2));
  const lines = code.split('\n');
  return indent + lines[0] + '\n' + lines.slice(1).join('\n') + '\n';
}
function diaMoveEdits(idx, fx, fy) {
  const info = readDdimAt(idx);
  if (!info || !info.center || info.rr == null) return null;
  return [{ s: info.span[0], e: info.span[1], txt: diaScopeBody(info, fx, fy) }];
}
function writeDiaMove(idx, fx, fy) {
  const edits = diaMoveEdits(idx, fx, fy);
  if (!edits) return false;
  const ed = edits[0], t = $('code').value;
  $('code').value = t.slice(0, ed.s) + ed.txt + t.slice(ed.e);
  go(true); return true;
}
function applyRdimLabel(label) {
  if (activeIdx < 0) return;
  const info = readRdimAt(activeIdx) || readDdimAt(activeIdx);
  if (!info) return;
  const text = $('code').value;
  const raw = text.slice(info.span[0], info.span[1]);
  const safe = String(label).replace(/\$/g, '$$$$');
  const next = raw.replace(new RegExp('(\\\\node\\[[^\\]]*\\] at \\(' + info.id + 't\\) \\{)[\\s\\S]*?(\\};)'), '$1' + safe + '$2');
  $('code').value = text.slice(0, info.span[0]) + next + text.slice(info.span[1]);
  dimKeep = info.id + 't';
  go(true);
}
function vecAt(expr) { const p = parseAt(expr); return p ? [p.x, p.y, p.z || 0] : null; }
function adimOrigin(raw) {
  return raw.match(/\\coordinate \((ag\d+)o\) at (\([^;]*\));/) || raw.match(/%\s*(ag\d+)o\s+(\([^)\n]*\))/);
}
function readAdimAt(idx) {
  const c = pts[idx];
  if (!c) return null;
  const text = $('code').value;
  const span = markedScopeSpan(text, c.s, 'adim');
  if (!span) return null;
  const raw = text.slice(span[0], span[1]);
  const idm = adimOrigin(raw);
  if (!idm) return null;
  const atOf = suf => { const m = raw.match(new RegExp('\\\\coordinate \\(' + idm[1] + suf + '\\) at (\\([^;]*\\));')); return m ? vecAt(m[1]) : null; };
  const o = vecAt(idm[2]), a = atOf('a'), b = atOf('b'), u = atOf('u'), v = atOf('v'), t = atOf('t');
  if (!o || !a || !b || !u || !v || !t) return null;
  const head = raw.match(/%\s*adim\s+(in|out)/);
  const labm = raw.match(new RegExp('\\\\node\\[[^\\]]*\\] at \\(' + idm[1] + 't\\) \\{([\\s\\S]*?)\\};'));
  return { id: idm[1], span, o, a, b, u, v, t, arrow: head && head[1] === 'out' ? 'out' : 'in', label: labm ? labm[1] : '', useZ: idm[2].split(',').length > 2 };
}
function angState(o, u, v, t, a, b, useZ) {
  const r1 = vunit(vsub(u, o)), r2 = vunit(vsub(v, o));
  const n = r1 && r2 ? vunit(vcross(r1, r2)) : null;
  if (!n) return null;
  let e2 = vcross(n, r1);
  let ang = Math.atan2(vdot(r2, e2), vdot(r2, r1));
  if (ang < 0) { e2 = vmul(e2, -1); ang = -ang; }
  e2 = vunit(e2);
  if (!e2 || ang < 1e-4) return null;
  return { o, a, b, u, v, t, e1: r1, e2, ang, R: vlen(vsub(u, o)), useZ };
}
function angScopeText(info, g) {
  const text = $('code').value, raw = text.slice(info.span[0], info.span[1]);
  const indent = (raw.match(/^[ \t]*/) || [''])[0];
  const code = angDimCode(g, info.label, info.id.slice(2), info.arrow);
  const lines = code.split('\n');
  return indent + lines[0] + '\n' + lines.slice(1).join('\n') + '\n';
}
function angBis(o, u, v, R) {
  const r1 = vunit(vsub(u, o)), r2 = vunit(vsub(v, o));
  const b = r1 && r2 ? vunit(vadd(r1, r2)) : r1;
  return b ? vadd(o, vmul(b, R)) : o;
}
function angMoved(idx, fx, fy) {
  const role = radAnchorRole(idx);
  if (role !== 'u' && role !== 'v' && role !== 't' && role !== 'm') return null;
  const info = readAdimAt(idx);
  const c = pts[idx];
  if (!info || !c || c.wx == null) return null;
  const [dvx, dvy] = mapVec(c, (fx - c.x) * (c.xs || 1), (fy - c.y) * (c.ys || 1), false);
  const nwx = c.wx + dvx, nwy = c.wy + dvy;
  const o = info.o, u = info.u, v = info.v, t = info.t;
  const R0 = vlen(vsub(u, o)) || 0.25;
  let nu = u, nv = v, nt = t, R = R0;
  if (role === 'u' || role === 'v' || role === 'm') {
    const text = $('code').value;
    const ow = coordIdx(text, info.id + 'o'), iw = coordIdx(text, info.id + role);
    const W0 = ow >= 0 ? pts[ow] : null, We = iw >= 0 ? pts[iw] : null;
    let tv = null;
    if (W0 && We && W0.wx != null && We.wx != null) {
      const dx = We.wx - W0.wx, dy = We.wy - W0.wy, L2 = dx * dx + dy * dy;
      if (L2 > 1e-8) tv = ((nwx - W0.wx) * dx + (nwy - W0.wy) * dy) / L2;
    }
    if (tv == null) {
      const end = role === 'u' ? u : role === 'v' ? v : angBis(o, u, v, R0);
      const n = vunit(vcross(vsub(u, o), vsub(v, o)));
      let tp = vsub([fx, fy, end[2] || 0], o);
      if (n) tp = vsub(tp, vmul(n, vdot(tp, n)));
      const dir = vunit(vsub(end, o));
      R = dir ? Math.max(0.25, vdot(tp, dir)) : R0;
    } else R = Math.max(0.25, tv * R0);
    const s = R / R0;
    nu = vadd(o, vmul(vsub(u, o), s)); nv = vadd(o, vmul(vsub(v, o), s)); nt = vadd(o, vmul(vsub(t, o), s));
  } else {
    const n = vunit(vcross(vsub(u, o), vsub(v, o)));
    let tp = vsub([fx, fy, t[2] || 0], o);
    if (n) tp = vsub(tp, vmul(n, vdot(tp, n)));
    nt = vadd(o, tp);
    R = Math.max(0.25, vlen(tp));
    const s = R / R0;
    nu = vadd(o, vmul(vsub(u, o), s)); nv = vadd(o, vmul(vsub(v, o), s));
  }
  const g = angState(o, nu, nv, nt, info.a, info.b, info.useZ);
  return g ? { info, g, nu, nv, nt } : null;
}
function angLayout(idx, fx, fy) {
  const moved = angMoved(idx, fx, fy);
  if (!moved) return null;
  const text = $('code').value;
  const iu = coordIdx(text, moved.info.id + 'u'), iv = coordIdx(text, moved.info.id + 'v'), it = coordIdx(text, moved.info.id + 't');
  if (iu < 0 || iv < 0 || it < 0) return null;
  const r = n => +Number(n).toFixed(4);
  const mid = angMid(moved.g);
  const im = coordIdx(text, moved.info.id + 'm');
  const out = [{ i: iu, x: r(moved.nu[0]), y: r(moved.nu[1]) }, { i: iv, x: r(moved.nv[0]), y: r(moved.nv[1]) }, { i: it, x: r(moved.nt[0]), y: r(moved.nt[1]) }];
  if (im >= 0) out.push({ i: im, x: r(mid[0]), y: r(mid[1]) });
  return out;
}
function angMoveEdits(idx, fx, fy) {
  const moved = angMoved(idx, fx, fy);
  if (!moved) return null;
  return [{ s: moved.info.span[0], e: moved.info.span[1], txt: angScopeText(moved.info, moved.g) }];
}
function writeAngMove(idx, fx, fy) {
  const edits = angMoveEdits(idx, fx, fy);
  if (!edits) return false;
  const ed = edits[0], t = $('code').value;
  $('code').value = t.slice(0, ed.s) + ed.txt + t.slice(ed.e);
  go(true); return true;
}
function applyAngLabel(label) {
  if (activeIdx < 0) return;
  const info = readAdimAt(activeIdx);
  if (!info) return;
  const text = $('code').value, raw = text.slice(info.span[0], info.span[1]);
  const safe = String(label).replace(/\$/g, '$$$$');
  const next = raw.replace(new RegExp('(\\\\node\\[[^\\]]*\\] at \\(' + info.id + 't\\) \\{)[\\s\\S]*?(\\};)'), '$1' + safe + '$2');
  $('code').value = text.slice(0, info.span[0]) + next + text.slice(info.span[1]);
  dimKeep = info.id + 't';
  go(true);
}
function applyAngArrow(arrow) {
  if (activeIdx < 0) return;
  const info = readAdimAt(activeIdx);
  if (!info) return;
  info.arrow = arrow;
  const g = angState(info.o, info.u, info.v, info.t, info.a, info.b, info.useZ);
  if (!g) return;
  const role = radAnchorRole(activeIdx);
  const text = $('code').value;
  $('code').value = text.slice(0, info.span[0]) + angScopeText(info, g) + text.slice(info.span[1]);
  dimKeep = info.id + (role === 'u' || role === 'v' || role === 't' || role === 'm' ? role : 't');
  go(true);
}
function syncAngEdit(info) {
  const inn = $('ed-in'), out = $('ed-out');
  if (inn) inn.classList.toggle('dimon', info.arrow !== 'out');
  if (out) out.classList.toggle('dimon', info.arrow === 'out');
  const lab = $('ed-lab');
  if (lab && document.activeElement !== lab) lab.value = info.label;
}
function showDimEdit(idx) {
  const el = $('dimedit');
  const ainfo = readAdimAt(idx), arole = radAnchorRole(idx);
  if (ainfo && (arole === 't' || arole === 'u' || arole === 'v' || arole === 'm')) {
    el.style.display = 'inline-flex';
    el.classList.remove('rdim', 'ddim');
    el.classList.add('adim');
    syncAngEdit(ainfo);
    return;
  }
  if (el) el.classList.remove('adim');
  const rinfo = readRdimAt(idx) || readDdimAt(idx);
  if (rinfo && radAnchorRole(idx) === 't') {
    el.style.display = 'inline-flex';
    el.classList.remove('rdim', 'ddim', 'adim');
    el.classList.add(rinfo.id.charAt(0) === 'd' ? 'ddim' : 'rdim');
    const lab = $('ed-lab');
    if (lab && document.activeElement !== lab) lab.value = rinfo.label;
    return;
  }
  if (el) el.classList.remove('rdim', 'ddim', 'adim');
  const c = pts[idx];
  const span = c && udimScopeSpan($('code').value, c.s);
  const info = span && readUdim($('code').value, span);
  if (!info) { hideDimEdit(); return; }
  $('dimedit').style.display = 'inline-flex';
  syncDimEdit(info);
}
function applyDimEdit(patch) {
  if (activeIdx < 0) return;
  const text = $('code').value, c = pts[activeIdx];
  if (!c) return;
  const span = udimScopeSpan(text, c.s);
  if (!span) return;
  const info = readUdim(text, span);
  if (!info) return;
  let hide = info.hide;
  if (patch.hideToggle) hide = (hide.includes(patch.hideToggle) ? hide.replace(patch.hideToggle, '') : hide + patch.hideToggle).split('').filter(ch => ch === '1' || ch === '2').sort().join('');
  const mode = patch.mode || info.mode;
  const arrow = patch.arrow || info.arrow;
  const label = patch.label != null ? patch.label : info.label;
  let geom = null, feet = info.feet;
  if (mode !== info.mode) {
    geom = ['a', 'b', 't'].map(suf => dimWorld(text, info.id, suf));
    if (geom.every(Boolean)) feet = null; else geom = null;
  }
  const code = dimCode(geom || [[0, 0], [0, 0], [0, 0]], label, { mode, arrow, hide, id: info.id, at: info.at, feet });
  const lines = code.split('\n');
  const body = info.indent + lines[0] + '\n' + lines.slice(1).join('\n') + '\n';
  $('code').value = text.slice(0, span[0]) + body + text.slice(span[1]);
  dimKeep = 'd' + info.id + 'a';
  go(true);
}
function delSel() {
  if (activeIdx < 0 || statusNow.kind === 'compiling') return;
  const c = pts.at(activeIdx);
  if (!c || c.s == null) return;
  const t = $('code').value;
  if (c.s < 0 || c.s > t.length || (c.e != null && c.e > t.length)) return;
  const scope = udimScopeSpan(t, c.s) || markedScopeSpan(t, c.s, 'rdim') || markedScopeSpan(t, c.s, 'ddim') || markedScopeSpan(t, c.s, 'adim') || planeAxesScopeSpan(t, c.s) || ax2ScopeSpan(t, c.s);
  let next;
  if (scope) next = t.slice(0, scope[0]) + t.slice(scope[1]);
  else {
    let st = t.lastIndexOf('\n', c.s); st = st === -1 ? 0 : st + 1;
    let ed = t.indexOf(';', Math.max(c.e || c.s, st));
    if (ed < 0) return;
    ed++;
    if (t.at(ed) === '\r') ed++; if (t.at(ed) === '\n') ed++;
    next = t.slice(0, st) + t.slice(ed);
  }
  activeIdx = -1; multiSet.clear(); $('inputs').style.display = 'none'; idleSel();
  $('code').value = next; go(true);
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
function xformAx2(info, sc, rot) {
  if (sc === 1 && rot === 0) return;
  writeAx2Scope(info, info.shift, (info.rot || 0) + rot, (info.scale || 1) * sc);
  $('isc').value = '1.0'; $('irot').value = '0';
}
function xformSel() {
  const sc = parseFloat($('isc').value), rot = parseFloat($('irot').value);
  if (isNaN(sc) || sc <= 0 || isNaN(rot)) return;
  if (activeIdx >= 0 && (planeAxesLocked(activeIdx) || gridLocked(activeIdx))) return;
  if (multiSet.size > 0) {
    [...multiSet].forEach(i => { if (noMultiSelect(i)) multiSet.delete(i); });
    if (!multiSet.size) return;
    const axIds = [...multiSet].map(i => findAx2At(i)).filter(Boolean);
    if (axIds.length && axIds.every(a => a.span[0] === axIds[0].span[0])) {
      xformAx2(axIds[0], sc, rot); return;
    }
    xformMulti(sc, rot); return;
  }
  if (activeIdx < 0) return;
  const ax2 = findAx2At(activeIdx);
  if (ax2) { xformAx2(ax2, sc, rot); return; }
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
    if (!movablePoint(pts[i]) || noMultiSelect(i)) continue;
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
  if (!spans.length) { setStatus('noscale'); return; }
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
  if (!spans.length) { setStatus('noselect'); return; }
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
async function saveTex() {
  const code = $('code').value;
  const desk = window.pywebview && window.pywebview.api && window.pywebview.api.save_tex;
  if (desk) {
    setStatus('exporting');
    let d;
    try { d = await window.pywebview.api.save_tex(code); }
    catch (err) { exportFail(err); return; }
    if (!d || d.cancelled) { setStatus('ready'); return; }
    if (!d.ok) { exportFail(d.err || ''); return; }
    $('toast').style.display = 'none';
    setStatus('exported', { note: d.name, path: d.path });
    return;
  }
  if (window.showSaveFilePicker) {
    try {
      const handle = await showSaveFilePicker({
        suggestedName: 'tikz.tex',
        types: [{ description: 'TeX', accept: { 'text/plain': ['.tex'] } }]
      });
      const w = await handle.createWritable();
      await w.write(code);
      await w.close();
      $('toast').style.display = 'none';
      setStatus('exported', { note: handle.name });
      return;
    } catch (err) {
      if (err && err.name === 'AbortError') return;
    }
  }
  dl(new Blob([code], { type: 'text/plain' }), 'tikz.tex');
  setStatus('exported', { note: 'tikz.tex' });
}
function exportFail(msg) {
  $('toast').style.display = 'block';
  $('toast').textContent = t('❌ 导出失败：') + '\n' + msg;
  setStatus('fail');
}
async function exportFile(fmt) {
  const suggested = fmt === 'png' ? 'tikz_600dpi.png' : `tikz.${fmt}`;
  const desk = window.pywebview && window.pywebview.api && window.pywebview.api.export_file;
  if (desk) {
    setStatus('exporting');
    let d;
    try { d = await window.pywebview.api.export_file($('code').value, $('comp').value, fmt); }
    catch (err) { exportFail(err); return; }
    if (!d || d.cancelled) { setStatus('ready'); return; }
    if (!d.ok) { exportFail(d.err || ''); return; }
    $('toast').style.display = 'none';
    setStatus('exported', { note: d.name, path: d.path });
    return;
  }
  const mime = { pdf: 'application/pdf', png: 'image/png', svg: 'image/svg+xml' }[fmt] || 'application/octet-stream';
  let handle = null;
  if (window.showSaveFilePicker) {
    try {
      handle = await showSaveFilePicker({ suggestedName: suggested, types: [{ description: fmt.toUpperCase(), accept: { [mime]: ['.' + fmt] } }] });
    } catch (err) {
      if (err && err.name === 'AbortError') return;
    }
  }
  setStatus('exporting');
  const r = await fetch('/api/export', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({code:$('code').value, compiler:$('comp').value, fmt})});
  if (!r.ok) { exportFail(await r.text()); return; }
  const blob = await r.blob();
  if (handle) {
    const w = await handle.createWritable();
    await w.write(blob);
    await w.close();
    $('toast').style.display = 'none';
    setStatus('exported', { note: handle.name });
    return;
  }
  dl(blob, suggested);
  $('toast').style.display = 'none';
  setStatus('exported', { note: suggested });
}
function lineSpan(text, s) {
  let st = text.lastIndexOf('\n', Math.max(0, s - 1)); st = st < 0 ? 0 : st + 1;
  let ed = text.indexOf('\n', s); if (ed < 0) ed = text.length; if (text.at(ed - 1) === '\r') ed--;
  return [st, ed];
}
function hideLine() { const hl = $('hl'); if (!hl) return; hl.style.display = 'none'; hl.dataset.line = ''; }
function idleSel() {
  $('sel-info').textContent = t('拖拽框选或点全选，然后平移、缩放、旋转');
  hideLine(); hideDimEdit();
  const ellBox = $('ell-extra'), paBox = $('planeaxes-extra'), xform = $('xform-wrap');
  if (ellBox) ellBox.style.display = 'none';
  if (paBox) paBox.style.display = 'none';
  if (xform) xform.style.display = '';
  if ($('lx')) $('lx').style.display = 'inline';
  if ($('ix')) $('ix').style.display = 'inline';
}
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
  multiSet.clear();
  showLine(c, true);
  $('sel-info').textContent = planeAxesLocked(idx)
    ? tf('坐标轴/刻度：在输入框修改范围', 'Axes/ticks: edit ranges in the inputs')
    : `L${c.l} (${c.wx ?? c.x}, ${c.wy ?? c.y})`;
  $('inputs').style.display = 'inline-flex';
  showFields(c);
  showDimEdit(idx);
  draw();
  if (fi) {
    const focusEl = planeAxesLocked(idx) ? $('pa-x0') : $('ix');
    if (focusEl) { focusEl.focus(); focusEl.select(); }
  }
}
function applyEdit(idx, fx, fy, moveStmt = false) {
  const c = pts.at(idx); let t = $('code').value;
  const paInfo = findPlaneAxesAt(idx);
  if (paInfo && $('planeaxes-extra') && $('planeaxes-extra').style.display !== 'none') {
    writePlaneAxes(paInfo, planeAxesValsFromInputs());
    return;
  }
  if (planeAxesLocked(idx)) return;
  const ellInfo = findEllAt(idx);
  if (ellInfo && ellInfo.role === 'c' && $('ell-extra') && $('ell-extra').style.display !== 'none') {
    const rx = parseFloat($('ell-rx').value), ry = parseFloat($('ell-ry').value), rot = parseFloat($('ell-rot').value);
    if (!(rx > 0.02) || !(ry > 0.02) || !Number.isFinite(fx) || !Number.isFinite(fy)) return;
    writeEllStmt(ellInfo, fx, fy, rx, ry, Number.isFinite(rot) ? rot : 0);
    return;
  }
  const ax2Edit = findAx2At(idx);
  if (ax2Edit && (c.kind === 'abs' || moveStmt)) {
    const [vx, vy] = mapVec(c, (fx - c.x) * (c.xs || 1), (fy - c.y) * (c.ys || 1), false);
    writeAx2Scope(ax2Edit, [ax2Edit.shift[0] + vx, ax2Edit.shift[1] + vy], ax2Edit.rot, ax2Edit.scale);
    return;
  }
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
  if (radLocked(idx)) return;
  if (radAnchorRole(idx) === 't' && (writeRadMove(idx, fx, fy) || writeDiaMove(idx, fx, fy))) return;
  if ((radAnchorRole(idx) === 'u' || radAnchorRole(idx) === 'v' || radAnchorRole(idx) === 't' || radAnchorRole(idx) === 'm') && readAdimAt(idx)) { writeAngMove(idx, fx, fy); return; }
  if ((c.kind === 'abs' || c.kind === 'xyz') && writeDimLayout(idx, fx, fy)) return;
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
  hideDimEdit();
  const ellBox = $('ell-extra');
  if (ellBox) ellBox.style.display = 'none';
  if (!multiSet.size) { $('inputs').style.display = 'none'; $('sel-info').textContent = t('没有可变换的坐标点'); hideLine(); draw(); return; }
  $('sel-info').textContent = tf(`已多选 ${multiSet.size} 点，可平移；缩放和旋转后点变换`, `${multiSet.size} points selected. Move them, or set scale and rotation, then Transform`);
  $('inputs').style.display = 'inline-flex';
  $('lx').textContent = 'ΔX:'; $('ix').value = '0';
  $('ly').style.display = 'inline'; $('iy').style.display = 'inline'; $('ly').textContent = 'ΔY:'; $('iy').value = '0';
  draw();
  if (focus) { $('ix').focus(); $('ix').select(); }
}
function selectAllPoints() {
  multiSet.clear();
  pts.forEach((c, i) => { if (movablePoint(c) && !noMultiSelect(i)) multiSet.add(i); });
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
      if (!movablePoint(c) || noMultiSelect(i) || c.wx == null || !pointShown(c)) return;
      const [px, py] = pointClient(c);
      if (px >= l && px <= rgt && py >= t && py <= b) multiSet.add(i);
    });
    showMulti(false);
  };
  window.addEventListener('mousemove', mv); window.addEventListener('mouseup', up);
}
function dimMoveAlso(dx, dy) {
  const also = {};
  multiSet.forEach(i => {
    const xy = dimXY(pts[i]);
    if (xy) also[i] = [xy[0] + dx, xy[1] + dy];
  });
  return also;
}
function applyMultiMove(dx, dy) {
  let t = $('code').value; const edits = [], seen = new Set(), add = (s, e, x, y) => edits.push({s, e, txt: `(${+(x+dx).toFixed(3)},${+(y+dy).toFixed(3)})`});
  multiSet.forEach(idx => {
    const c = pts.at(idx); if (!movablePoint(c) || noMultiSelect(idx)) return;
    const arole = radAnchorRole(idx);
    if (arole === 't' || arole === 'u' || arole === 'v' || arole === 'm') {
      const got = (arole === 't' && (radMoveEdits(idx, c.x + dx, c.y + dy) || diaMoveEdits(idx, c.x + dx, c.y + dy))) || angMoveEdits(idx, c.x + dx, c.y + dy);
      if (got) { got.forEach(ed => edits.push(ed)); return; }
    }
    if (c.kind === 'xyz') edits.push({ s: c.s, e: c.e, txt: pointText(c, c.x + dx, c.y + dy) });
    else if ($('mv-all').checked) { let st = t.lastIndexOf('\n', c.s); st = st === -1 ? 0 : st + 1; let ed = t.indexOf(';', c.e); ed = ed === -1 ? t.length : ed + 1; if (!seen.has(st)) { seen.add(st); for (const m of t.slice(st, ed).matchAll(/\(\s*([-+]?\d*\.?\d+)\s*,\s*([-+]?\d*\.?\d+)\s*\)/g)) add(st + m.index, st + m.index + m.at(0).length, parseFloat(m.at(1)), parseFloat(m.at(2))); } }
    else { add(c.s, c.e, c.x, c.y); if ($('lk').checked) pts.forEach((o, j) => { if (!multiSet.has(j) && o.kind === 'abs' && Math.abs(o.x-c.x)<1e-4 && Math.abs(o.y-c.y)<1e-4) add(o.s, o.e, o.x, o.y); }); }
    const layout = dimLineLayout(idx, c.x + dx, c.y + dy, dimMoveAlso(dx, dy));
    if (layout) layout.forEach(ed => { const o = pts[ed.i]; edits.push({ s: o.s, e: o.e, txt: pointText(o, ed.x, ed.y) }); });
  });
  const uniq = new Map(); edits.forEach(ed => uniq.set(ed.s, ed)); [...uniq.values()].sort((a, b) => b.s - a.s).forEach(ed => { t = t.slice(0, ed.s) + ed.txt + t.slice(ed.e); }); $('code').value = t; go(true);
}
async function importDxfFile(f) {
  setStatus('importing');
  const fd = new FormData(); fd.append('file', f); fd.append('lang', lang);
  let d;
  try {
    const r = await fetch('/api/dxf', {method:'POST', body: fd});
    d = await r.json();
  } catch (err) {
    $('toast').style.display = 'block'; $('toast').textContent = t('❌ 导入失败：') + '\n' + err; setStatus('fail'); return;
  }
  if (!d.ok) { $('toast').style.display = 'block'; $('toast').textContent = t('❌ 导入失败：') + '\n' + t(d.err); setStatus('fail'); return; }
  $('toast').style.display = 'none'; $('code').value = d.code; await go(false);
  if (statusNow.kind === 'ok') setStatus('note', { note: d.note });
}
function rebuildAdim(raw) {
  const idm = adimOrigin(raw);
  if (!idm) return '';
  const atOf = suf => { const hit = raw.match(new RegExp('\\\\coordinate \\(' + idm[1] + suf + '\\) at (\\([^;]*\\));')); return hit ? vecAt(hit[1]) : null; };
  const o = vecAt(idm[2]), a = atOf('a'), b = atOf('b'), u = atOf('u'), v = atOf('v'), t = atOf('t');
  if (!o || !a || !b || !u || !v || !t) return '';
  const g = angState(o, u, v, t, a, b, idm[2].split(',').length > 2);
  if (!g) return '';
  const head = raw.match(/%\s*adim\s+(in|out)/);
  const labm = raw.match(new RegExp('\\\\node\\[[^\\]]*\\] at \\(' + idm[1] + 't\\) \\{([\\s\\S]*?)\\};'));
  const indent = (raw.match(/^[ \t]*/) || [''])[0];
  const code = angDimCode(g, labm ? labm[1] : angLabel(g.ang), idm[1].slice(2), head && head[1] === 'out' ? 'out' : 'in');
  const lines = code.split('\n');
  return indent + lines[0] + '\n' + lines.slice(1).join('\n') + '\n';
}
function adimNeedsArc(raw) {
  return /plane origin=\{\(\s*[-+]?\d/.test(raw) || /\\coordinate \(ag\d+k\d+\)/.test(raw);
}
function upgradeAdims(code) {
  if (!adimNeedsArc(code)) return code;
  const marks = [];
  let from = 0;
  while (from < code.length) {
    const i = code.indexOf('% adim', from);
    if (i < 0) break;
    marks.push(i);
    from = i + 6;
  }
  let out = code;
  for (let n = marks.length - 1; n >= 0; n--) {
    const span = markedScopeSpan(out, marks[n], 'adim');
    if (!span) continue;
    const raw = out.slice(span[0], span[1]);
    if (!adimNeedsArc(raw)) continue;
    const rebuilt = rebuildAdim(raw);
    if (!rebuilt) continue;
    out = out.slice(0, span[0]) + rebuilt + out.slice(span[1]);
  }
  return out;
}
let goSeq = 0;
async function go(rb = false) {
  const keep = dimKeep; dimKeep = '';
  const upgraded = upgradeAdims($('code').value);
  if (upgraded !== $('code').value) $('code').value = upgraded;
  const cur = $('code').value; syncPanel(cur); setStatus('compiling');
  const seq = ++goSeq;
  const r = await fetch('/api/compile', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({code:cur, compiler:$('comp').value})});
  const d = await r.json();
  if (seq !== goSeq) return;
  if (!d.ok) { $('toast').style.display = 'block'; if (rb && lastGood && lastGood !== cur) { $('code').value = lastGood; $('toast').textContent = t('⚠️ 已回退：') + '\n' + d.err; setStatus('revert'); draw(); } else { $('toast').textContent = t('❌ 编译错误：') + '\n' + d.err; setStatus('fail'); } return; }
  $('toast').style.display = 'none'; if (cur !== lastGood) { lastGood = cur; history.push(cur); if (history.length > 30) history.shift(); }
  $('svg').innerHTML = d.svg; W = d.w; H = d.h; pts = d.coords; ports = d.ports || []; cal = d.cal; activeIdx = -1; multiSet.clear(); $('inputs').style.display = 'none'; idleSel(); draw(); setStatus('ok', { n: pts.length });
  if (!keep) return;
  const i = pts.findIndex(p => cur.slice(cur.lastIndexOf('\n', p.s) + 1, p.s).includes('\\coordinate (' + keep + ')'));
  if (i >= 0) selectPt(i);
}
function draw() {
  const z = +$('zm').value, s = $('svg').querySelector('svg'); if (s && W) { s.style.width = (W * z) + 'px'; s.style.height = (H * z) + 'px'; }
  $('ov').innerHTML = ''; if (!cal) return;
  const order = pts.map((_, n) => n).sort((a, b) => (pts[a].kind === 'abs' || pts[a].kind === 'xyz') - (pts[b].kind === 'abs' || pts[b].kind === 'xyz'));
  order.forEach(i0 => {
    const c0 = pts[i0];
    if (!pointShown(c0) || radLocked(i0)) return;
    const d = document.createElement('div'); d.dataset.idx = i0;
    const red = c0.kind === 'abs' || c0.kind === 'xyz', purple = c0.kind === 'lerp' || c0.kind === 'mid';
    const locked = planeAxesLocked(i0);
    d.className = 'dot' + (locked ? ' locked' : (purple ? ' lerp' : (red ? '' : ' rel'))) + (multiSet.has(i0) ? ' msel' : (i0 === activeIdx ? ' sel' : ''));
    const [cpx, cpy] = tikzToPage(c0.wx, c0.wy);
    d.style.left = (cpx * z) + 'px'; d.style.top = (cpy * z) + 'px';
    d.onmousedown = e => {
      if (place) {
        e.preventDefault(); e.stopPropagation();
        if (e.button === 2) { confirmPlace(); return; }
        if (place.adim && place.ang.segs.length < 2) { const hit = pickSeg(e.clientX, e.clientY); if (hit) acceptSeg(hit); return; }
        if (place.curveDim && !place.curve) { const hit = pickCurve(e.clientX, e.clientY); if (hit) { place.curve = hit; place.hoverCurve = null; paintPlaceForm(); } return; }
        if (place.circ && place.pts[0]) {
          const hit = circSnap(e.clientX, e.clientY);
          if (hit && hit.R > 0.02) {
            const el = $('pf-r');
            if (el) el.value = String(radNum(hit.R));
            place.circHit = hit;
            confirmPlace();
          }
          return;
        }
        putPlace(c0.wx, c0.wy, refForPoint(c0)); return;
      }
      let i = i0, c = c0;
      if (c.kind === 'anchor' && c.wx != null) {
        const j = pts.findIndex(o => o.kind === 'abs' && o.wx != null && Math.abs(o.wx - c.wx) < 0.01 && Math.abs(o.wy - c.wy) < 0.01);
        if (j >= 0) { i = j; c = pts[j]; }
      }
      e.preventDefault(); e.stopPropagation();
      if (planeAxesLocked(i)) {
        multiSet.clear();
        selectPt(i, true);
        return;
      }
      document.body.style.cursor = 'grabbing'; const isMod = e.ctrlKey || e.shiftKey;
      const mark = i === i0 ? d : ($('ov').querySelector('.dot[data-idx="' + i + '"]') || d);
      const movers = mark === d ? [d] : [d, mark];
      if (!isMod && !multiSet.has(i)) { multiSet.clear(); activeIdx = i; $('ov').querySelectorAll('.dot').forEach(el => el.classList.remove('sel', 'msel')); mark.classList.add('sel'); }
      showLine(c);
      const sx = e.clientX, sy = e.clientY, sn = +$('sn').value; let fx = c.x, fy = c.y, rawFx = c.x, rawFy = c.y, mv0 = false;
      const moveAll0 = !!($('mv-all') && $('mv-all').checked);
      const ax2Info0 = findAxesAt(i);
      const ax2Origin = ax2Info0 ? {
        info: ax2Info0,
        kind: ax2Info0.kind || 'ax2',
        shift: [ax2Info0.shift[0], ax2Info0.shift[1]],
        rot: ax2Info0.rot, scale: ax2Info0.scale, lx: ax2Info0.lx, ly: ax2Info0.ly, lz: ax2Info0.lz || 0,
        tips: ax2Info0.tips || { ow: ax2Info0.shift[0], oh: ax2Info0.shift[1], tips: [] },
        members: ax2Info0.members.map(({ p, i: j }) => ({ i: j, wx: p.wx, wy: p.wy }))
      } : null;
      const rectInfo0 = ax2Origin ? null : findRectAt(i);
      const rectOrigin = rectInfo0 ? { awx: rectInfo0.a.wx, awy: rectInfo0.a.wy, bwx: rectInfo0.b.wx, bwy: rectInfo0.b.wy, aIdx: rectInfo0.aIdx, bIdx: rectInfo0.bIdx, role: rectInfo0.role, info: rectInfo0 } : null;
      const lineInfo0 = (ax2Origin || rectOrigin) ? null : findLineAt(i);
      const orthoPoly0 = lineInfo0 ? findOrthoPolyAt(i) : null;
      const lineOrigin = lineInfo0 ? {
        idx: i,
        poly: orthoPoly0,
        neighbors: (orthoPoly0 ? orthoPoly0.neighbors : lineInfo0.segs.map(s => {
          const j = s.i0 === i ? s.i1 : s.i0, o = pts[j];
          return o && o.wx != null ? { i: j, wx: o.wx, wy: o.wy } : null;
        }).filter(Boolean)).map(n => ({ i: n.i, wx: n.wx, wy: n.wy })),
        segs: (orthoPoly0 ? orthoPoly0.segs : lineInfo0.segs).map(s => ({ i0: s.i0, i1: s.i1, w0: [s.w0[0], s.w0[1]], w1: [s.w1[0], s.w1[1]] }))
      } : null;
      const mv = v => {
        if (Math.abs(v.clientX - sx) < 2 && Math.abs(v.clientY - sy) < 2) return; mv0 = true;
        const [dwx, dwy] = pageDeltaToTikz((v.clientX - sx) / z, (v.clientY - sy) / z);
        if (c.kind === 'lerp') { fx = +Math.max(0.05, Math.min(0.95, Math.round((c.x + dwx * 0.4) / 0.05) * 0.05)).toFixed(2); $('ix').value = fx; return; }
        const plan = planDrag(c, dwx, dwy, sn);
        rawFx = plan.fx; rawFy = plan.fy; fx = rawFx; fy = rawFy;
        let nwx = +plan.nwx.toFixed(3), nwy = +plan.nwy.toFixed(3); const dx = nwx - c.wx, dy = nwy - c.wy;
        const placeDot = (el, x, y) => { const [px, py] = tikzToPage(x, y); el.style.left = (px * z) + 'px'; el.style.top = (py * z) + 'px'; };
        movers.forEach(el => placeDot(el, nwx, nwy));
        const layout = dimLineLayout(i, rawFx, rawFy) || angLayout(i, rawFx, rawFy);
        if (multiSet.has(i) && multiSet.size > 1) $('ov').querySelectorAll('.dot').forEach(el => { const j = +el.dataset.idx, o = pts.at(j); if (multiSet.has(j) && o) placeDot(el, o.wx + dx, o.wy + dy); });
        else if ($('mv-all').checked && c.kind === 'abs') { const t = $('code').value; let st = t.lastIndexOf('\n', c.s); st = st === -1 ? 0 : st + 1; let ed = t.indexOf(';', c.e); ed = ed === -1 ? t.length : ed + 1; $('ov').querySelectorAll('.dot').forEach(el => { const j = +el.dataset.idx, o = pts.at(j); if (o && o.s >= st && o.e <= ed) placeDot(el, o.wx + dx, o.wy + dy); }); }
        if (layout) {
          const mine = layout.find(ed => ed.i === i);
          if (mine) {
            fx = mine.x; fy = mine.y;
            const [vx, vy] = mapVec(c, (mine.x - c.x) * (c.xs || 1), (mine.y - c.y) * (c.ys || 1), false);
            nwx = +(c.wx + vx).toFixed(3); nwy = +(c.wy + vy).toFixed(3);
          }
          $('ov').querySelectorAll('.dot').forEach(el => {
            const j = +el.dataset.idx, ed = layout.find(item => item.i === j), o = pts.at(j);
            if (!ed || !o || o.wx == null) return;
            const [vx, vy] = mapVec(o, (ed.x - o.x) * (o.xs || 1), (ed.y - o.y) * (o.ys || 1), false);
            placeDot(el, o.wx + vx, o.wy + vy);
          });
        }
        if (radAnchorRole(i) === 't') {
          const info = readRdimAt(i);
          const dinfo = info ? null : readDdimAt(i);
          const use = info || dinfo;
          const rimName = info ? info.id + 'p' : dinfo && dinfo.id + 'a';
          const ic = use && coordIdx($('code').value, use.id + 'c'), ir = use && coordIdx($('code').value, rimName);
          const C = ic >= 0 ? pts[ic] : null, Rp = ir >= 0 ? pts[ir] : null;
          if (C && Rp && C.wx != null && Rp.wx != null) {
            const rv = Math.hypot(Rp.wx - C.wx, Rp.wy - C.wy);
            let g = $('ov').querySelector('.rad-ghost');
            if (!g) { g = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); g.setAttribute('class', 'ghost-line ghost-dim rad-ghost'); $('ov').appendChild(g); }
            g.replaceChildren();
            const gp = (x, y) => { const [px, py] = tikzToPage(x, y); return { x: px * z, y: py * z }; };
            if (dinfo) paintDiaAt(g, gp, C.wx, C.wy, rv, nwx, nwy);
            else {
              let deg = Math.atan2(nwy - C.wy, nwx - C.wx) * 180 / Math.PI;
              if (info.a0 != null) deg = clampArc(deg, info.a0, info.a1);
              const ra = deg * Math.PI / 180;
              paintArrow(g, gp(nwx, nwy), gp(C.wx + rv * Math.cos(ra), C.wy + rv * Math.sin(ra)));
            }
          }
        }
        const ellInfo = findEllAt(i);
        if (ellInfo) {
          let cx = ellInfo.cx, cy = ellInfo.cy, rx = ellInfo.rx, ry = ellInfo.ry, rot = ellInfo.rot || 0;
          const xr = ellInfo.xr || pts.find(p => p.kind === 'rad' && p.label === 'X半径' && p.s >= ellInfo.span.st && p.s < ellInfo.span.ed);
          const yr = ellInfo.yr || pts.find(p => p.kind === 'rad' && p.label === 'Y半径' && p.s >= ellInfo.span.st && p.s < ellInfo.span.ed);
          let xSign = 1, ySign = 1;
          if (xr && xr.wx != null) { const ax = ellAxes(rot); xSign = ((xr.wx - (xr.cx ?? cx)) * ax.ux + (xr.wy - (xr.cy ?? cy)) * ax.uy) < 0 ? -1 : 1; }
          if (yr && yr.wx != null) { const ax = ellAxes(rot); ySign = ((yr.wx - (yr.cx ?? cx)) * ax.vx + (yr.wy - (yr.cy ?? cy)) * ax.vy) < 0 ? -1 : 1; }
          if (ellInfo.role === 'c') {
            cx = nwx; cy = nwy;
          } else if (ellInfo.role === 'x' && plan.ellRot != null) {
            rx = plan.ellLen; rot = plan.ellRot; xSign = (nwx - cx) * ellAxes(rot).ux + (nwy - cy) * ellAxes(rot).uy < 0 ? -1 : 1;
          } else if (ellInfo.role === 'y' && plan.ellRot != null) {
            ry = plan.ellLen; rot = plan.ellRot; ySign = (nwx - cx) * ellAxes(rot).vx + (nwy - cy) * ellAxes(rot).vy < 0 ? -1 : 1;
          }
          const ends = paintEllGhost(cx, cy, rx, ry, rot, xSign, ySign);
          if (xr) { const el = $('ov').querySelector('.dot[data-idx="' + pts.indexOf(xr) + '"]'); if (el) placeDot(el, ends.xEnd[0], ends.xEnd[1]); }
          if (yr) { const el = $('ov').querySelector('.dot[data-idx="' + pts.indexOf(yr) + '"]'); if (el) placeDot(el, ends.yEnd[0], ends.yEnd[1]); }
          if (ellInfo.role === 'c') {
            const cen = $('ov').querySelector('.dot[data-idx="' + i + '"]');
            if (cen) placeDot(cen, cx, cy);
          }
          shapeDrag = { kind: 'ell', info: ellInfo, cx, cy, rx, ry, rot };
          if ($('ell-rx')) $('ell-rx').value = radNum(rx);
          if ($('ell-ry')) $('ell-ry').value = radNum(ry);
          if ($('ell-rot')) $('ell-rot').value = radNum(rot);
        } else {
          const circInfo = findCircAt(i);
          if (circInfo) {
            let cx = circInfo.cx, cy = circInfo.cy, R = circInfo.R;
            if (circInfo.role === 'c') { cx = nwx; cy = nwy; }
            else R = Math.max(0.02, plan.fx * (c.xs || 1));
            paintCircGhost(cx, cy, R);
            if (circInfo.rad) {
              const el = $('ov').querySelector('.dot[data-idx="' + pts.indexOf(circInfo.rad) + '"]');
              if (el) placeDot(el, cx + R, cy);
            }
            if (circInfo.role === 'c') {
              const cen = $('ov').querySelector('.dot[data-idx="' + i + '"]');
              if (cen) placeDot(cen, cx, cy);
            }
            shapeDrag = { kind: 'circ', info: circInfo, cx, cy, R };
          } else {
            const arcInfo = findArcAt(i);
            if (arcInfo && arcInfo.cx != null) {
              let cx = arcInfo.cx, cy = arcInfo.cy, a0 = arcInfo.a0, a1 = arcInfo.a1, r = arcInfo.r;
              if (arcInfo.role === 'c') {
                cx = nwx; cy = nwy;
              } else if (arcInfo.role === 'start') {
                const mx = c.kind === 'polar' ? nwx : (c.wx + dwx), my = c.kind === 'polar' ? nwy : (c.wy + dwy);
                r = Math.max(0.02, Math.hypot(mx - cx, my - cy));
                if (sn > 0) r = Math.max(0.02, Math.round(r / sn) * sn);
                a0 = Math.atan2(my - cy, mx - cx) * 180 / Math.PI;
                if (sn > 0) a0 = Math.round(a0);
                while (a1 <= a0 + 1e-6) a1 += 360;
                while (a1 > a0 + 360) a1 -= 360;
              } else {
                const mx = c.wx + dwx, my = c.wy + dwy;
                r = Math.max(0.02, Math.hypot(mx - cx, my - cy));
                if (sn > 0) r = Math.max(0.02, Math.round(r / sn) * sn);
                a1 = Math.atan2(my - cy, mx - cx) * 180 / Math.PI;
                if (sn > 0) a1 = Math.round(a1);
                while (a1 <= a0 + 1e-6) a1 += 360;
              }
              const ends = paintArcGhost(cx, cy, a0, a1, r);
              if (ends) {
                if (arcInfo.polarPt) {
                  const el = $('ov').querySelector('.dot[data-idx="' + pts.indexOf(arcInfo.polarPt) + '"]');
                  if (el) placeDot(el, ends.start[0], ends.start[1]);
                }
                if (arcInfo.arcPt) {
                  const el = $('ov').querySelector('.dot[data-idx="' + pts.indexOf(arcInfo.arcPt) + '"]');
                  if (el) placeDot(el, ends.end[0], ends.end[1]);
                }
                if (arcInfo.classic && arcInfo.role === 'start') {
                  const el = $('ov').querySelector('.dot[data-idx="' + i + '"]');
                  if (el) placeDot(el, ends.start[0], ends.start[1]);
                }
                if (arcInfo.role === 'c') {
                  const cen = $('ov').querySelector('.dot[data-idx="' + i + '"]');
                  if (cen) placeDot(cen, cx, cy);
                }
              }
              shapeDrag = { kind: 'arc', info: arcInfo, cx, cy, a0, a1, r };
              fx = arcInfo.role === 'end' ? +a1.toFixed(2) : (arcInfo.role === 'start' ? +a0.toFixed(2) : cx);
              fy = arcInfo.role === 'c' ? cy : +r.toFixed(3);
            } else if (ax2Origin) {
            const tdx = nwx - c.wx, tdy = nwy - c.wy;
            ax2Origin.members.forEach(m => {
              const el = $('ov').querySelector('.dot[data-idx="' + m.i + '"]');
              if (el) placeDot(el, m.wx + tdx, m.wy + tdy);
            });
            const tip = ax2Origin.tips;
            if (tip && tip.tips && tip.tips.length) {
              paintAxesGhost(tip.ow + tdx, tip.oh + tdy, tip.tips);
            } else if (ax2Origin.kind === 'ax3') {
              const th = (ax2Origin.rot || 0) * Math.PI / 180, s = ax2Origin.scale > 0 ? ax2Origin.scale : 1;
              const cs = Math.cos(th), sn = Math.sin(th), uzx = -0.385, uzy = -0.385;
              const map = (x, y, z) => {
                const px = (x + z * uzx) * s, py = (y + z * uzy) * s;
                return [cs * px - sn * py, sn * px + cs * py];
              };
              paintAxesGhost(ax2Origin.shift[0] + tdx, ax2Origin.shift[1] + tdy, [
                map(ax2Origin.lx, 0, 0), map(0, ax2Origin.ly, 0), map(0, 0, ax2Origin.lz || 1.35)
              ]);
            } else {
              paintAx2Ghost(ax2Origin.shift[0] + tdx, ax2Origin.shift[1] + tdy, ax2Origin.lx, ax2Origin.ly, ax2Origin.rot, ax2Origin.scale);
            }
            shapeDrag = { kind: 'ax2', info: ax2Origin.info, shift: [ax2Origin.shift[0] + tdx, ax2Origin.shift[1] + tdy], rot: ax2Origin.rot, scale: ax2Origin.scale };
          } else if (rectOrigin) {
            const tdx = nwx - c.wx, tdy = nwy - c.wy;
            let ax, ay, bx, by;
            if (moveAll0) {
              ax = rectOrigin.awx + tdx; ay = rectOrigin.awy + tdy;
              bx = rectOrigin.bwx + tdx; by = rectOrigin.bwy + tdy;
              const ea = $('ov').querySelector('.dot[data-idx="' + rectOrigin.aIdx + '"]');
              const eb = $('ov').querySelector('.dot[data-idx="' + rectOrigin.bIdx + '"]');
              if (ea) placeDot(ea, ax, ay);
              if (eb) placeDot(eb, bx, by);
            } else if (rectOrigin.role === 'a') {
              ax = nwx; ay = nwy;
              bx = rectOrigin.bwx; by = rectOrigin.bwy;
            } else {
              ax = rectOrigin.awx; ay = rectOrigin.awy;
              bx = nwx; by = nwy;
            }
            paintRectGhost(ax, ay, bx, by);
            shapeDrag = { kind: 'rect', info: rectOrigin.info, ax, ay, bx, by };
          } else if (lineOrigin) {
            if (!moveAll0 && lineOrigin.neighbors && lineOrigin.neighbors.length) {
              const snapped = orthoSnapPoly(nwx, nwy, lineOrigin.neighbors);
              nwx = +snapped.x.toFixed(3); nwy = +snapped.y.toFixed(3);
              const [vx, vy] = mapVec(c, nwx - c.wx, nwy - c.wy, true);
              fx = +(c.x + vx / (c.xs || 1)).toFixed(3);
              fy = +(c.y + vy / (c.ys || 1)).toFixed(3);
              rawFx = fx; rawFy = fy;
              movers.forEach(el => placeDot(el, nwx, nwy));
            }
            const tdx = nwx - c.wx, tdy = nwy - c.wy;
            const live = lineOrigin.segs.map(s => {
              let x0 = s.w0[0], y0 = s.w0[1], x1 = s.w1[0], y1 = s.w1[1];
              if (moveAll0) {
                x0 += tdx; y0 += tdy; x1 += tdx; y1 += tdy;
              } else {
                if (s.i0 === lineOrigin.idx) { x0 = nwx; y0 = nwy; }
                if (s.i1 === lineOrigin.idx) { x1 = nwx; y1 = nwy; }
              }
              return [[x0, y0], [x1, y1]];
            });
            if (moveAll0) {
              const seen = new Set([i]);
              lineOrigin.segs.forEach(s => {
                [s.i0, s.i1].forEach(j => {
                  if (seen.has(j)) return;
                  seen.add(j);
                  const o = pts[j], el = $('ov').querySelector('.dot[data-idx="' + j + '"]');
                  if (el && o && o.wx != null) placeDot(el, o.wx + tdx, o.wy + tdy);
                });
              });
            }
            paintLineGhost(live);
            shapeDrag = { kind: 'line', segs: live };
            }
          }
        }
        $('ix').value = fx; $('iy').value = fy; $('tip').style.display = 'block'; $('tip').style.left = (v.clientX + 14) + 'px'; $('tip').style.top = (v.clientY + 14) + 'px'; $('tip').textContent = tf(`位置:(${nwx},${nwy}) 参数:(${fx},${fy})`, `Position: (${nwx}, ${nwy}) value: (${fx}, ${fy})`);
      };
      const up = () => {
        window.removeEventListener('mousemove', mv); window.removeEventListener('mouseup', up); document.body.style.cursor = ''; $('tip').style.display = 'none';
        const live = shapeDrag; clearShapeGhost();
        if (!mv0) {
          if (isMod && !noMultiSelect(i)) {
            if (multiSet.has(i)) multiSet.delete(i); else multiSet.add(i);
            showMulti(multiSet.size > 0);
          } else selectPt(i, true);
        }
        else if (live && live.kind === 'ell') writeEllStmt(live.info, live.cx, live.cy, live.rx, live.ry, live.rot);
        else if (live && live.kind === 'circ' && live.info.role === 'r') applyEdit(i, +(live.R / (c.xs || 1)).toFixed(3), 0, false);
        else if (live && live.kind === 'circ' && live.info.role === 'c') applyEdit(i, live.cx, live.cy, $('mv-all').checked);
        else if (live && live.kind === 'arc') writeArcStmt(live.info, live.cx, live.cy, live.a0, live.a1, live.r);
        else if (live && live.kind === 'ax2') writeAx2Scope(live.info, live.shift, live.rot, live.scale);
        else if (fx !== c.x || fy !== c.y) { if (multiSet.has(i) && multiSet.size > 1) applyMultiMove(rawFx - c.x, rawFy - c.y); else applyEdit(i, rawFx, rawFy, $('mv-all').checked); }
      };
      window.addEventListener('mousemove', mv); window.addEventListener('mouseup', up);
    };
    $('ov').appendChild(d);
  });
  paintPlace();
}
function refreshLang() {
  applyI18n();
  renderBar();
  if ($('libbox').style.display === 'block') fillLibPick();
  if (place) paintPlaceForm();
  else if (multiSet.size) showMulti(false);
  else if (activeIdx >= 0) { showFields(pts.at(activeIdx)); showDimEdit(activeIdx); }
  else idleSel();
  paintStatus();
}
window.onload = () => {
  loadEditorConfig();
  applyI18n();
  setStatus('ready');
  $('lang').onclick = () => { setLang(lang === 'en' ? 'zh' : 'en'); refreshLang(); };
  $('del-btn').onclick = delSel; $('xform-btn').onclick = xformSel; $('sel-all').onclick = selectAllPoints;
  $('tpl-sel').onchange = e => {
    const key = e.target.value;
    if (!key) return;
    endPlace();
    $('code').value = TPLS[key];
    const forced = { rc: 'circuit', buck: 'circuit', opamp: 'circuit', block: 'block', struct2d: 'plane', struct3d: 'space', plot: 'plot', plane: 'plane', cms: 'space', gauss: 'plot' }[key];
    if (forced && forced !== panel) { $('libbox').style.display = 'none'; panel = forced; renderBar(); }
    syncPanel($('code').value);
    e.target.value = '';
    go(false);
  };
  $('open-tex').onclick = () => $('file-in').click();
  $('file-in').onchange = e => { const f = e.target.files.item(0); if (!f) return; const rd = new FileReader(); rd.onload = ev => { $('code').value = ev.target.result; go(false); }; rd.readAsText(f, 'UTF-8'); e.target.value = ''; };
  $('open-dxf').onclick = () => $('dxf-in').click();
  $('dxf-in').onchange = e => { const f = e.target.files.item(0); e.target.value = ''; if (f) importDxfFile(f); };
  $('save-tex').onclick = () => { saveTex(); };
  $('place-ok').onclick = confirmPlace; $('place-cancel').onclick = endPlace;
  $('ed-h').onclick = () => applyDimEdit({ mode: 'h' }); $('ed-v').onclick = () => applyDimEdit({ mode: 'v' }); $('ed-a').onclick = () => applyDimEdit({ mode: 'a' });
  $('ed-in').onclick = () => { if ($('dimedit').classList.contains('adim')) applyAngArrow('in'); else applyDimEdit({ arrow: 'in' }); };
  $('ed-out').onclick = () => { if ($('dimedit').classList.contains('adim')) applyAngArrow('out'); else applyDimEdit({ arrow: 'out' }); };
  $('ed-s1').onclick = () => applyDimEdit({ hideToggle: '1' }); $('ed-s2').onclick = () => applyDimEdit({ hideToggle: '2' });
  $('ed-lab').onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); const bar = $('dimedit'); if (bar.classList.contains('adim')) applyAngLabel($('ed-lab').value); else if (bar.classList.contains('rdim') || bar.classList.contains('ddim')) applyRdimLabel($('ed-lab').value); else applyDimEdit({ label: $('ed-lab').value }); } };
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
    if (place && place.adim && place.ang.segs.length >= 2) {
      const tag = (e.target && e.target.tagName) || '';
      if (tag !== 'INPUT' && tag !== 'TEXTAREA' && tag !== 'SELECT') {
        const k = e.key.toLowerCase();
        if (k === 'i') { e.preventDefault(); setAngArrow('in'); return; }
        if (k === 'o') { e.preventDefault(); setAngArrow('out'); return; }
      }
    }
    if (place && place.dim) {
      const tag = (e.target && e.target.tagName) || '';
      if (tag !== 'INPUT' && tag !== 'TEXTAREA' && tag !== 'SELECT') {
        const k = e.key.toLowerCase();
        if (k === 'h') { e.preventDefault(); setDimMode('h'); return; }
        if (k === 'v') { e.preventDefault(); setDimMode('v'); return; }
        if (k === 'r') { e.preventDefault(); setDimMode('a'); return; }
        if (k === 'i') { e.preventDefault(); setDimArrow('in'); return; }
        if (k === 'o') { e.preventDefault(); setDimArrow('out'); return; }
        if (k === '1') { e.preventDefault(); toggleDimSide('1'); return; }
        if (k === '2') { e.preventDefault(); toggleDimSide('2'); return; }
      }
    }
    if (e.key !== 'Escape') return;
    if (place) { e.preventDefault(); endPlace(); return; }
    if ($('libbox').style.display === 'block') { e.preventDefault(); $('libbox').style.display = 'none'; }
  });
  $('wrap').onmousemove = e => {
    if (place && place.adim && cal) {
      if (place.ang.segs.length < 2) {
        const hit = pickSeg(e.clientX, e.clientY);
        if ((hit && place.hoverSeg && sameSeg(hit, place.hoverSeg)) || (!hit && !place.hoverSeg)) return;
        place.hoverSeg = hit; paintPlace(); return;
      }
      if (place.pts[0]) return;
      const w = pickWorld(e.clientX, e.clientY);
      if (placeHover && w.x === placeHover.x && w.y === placeHover.y && w.ref === placeHover.ref) return;
      placeHover = w; paintPlace(); return;
    }
    if (place && place.circ && place.pts[0] && cal) {
      if (document.activeElement && document.activeElement.id === 'pf-r') return;
      const hit = circSnap(e.clientX, e.clientY);
      const prev = place.circHit;
      if (prev && hit && prev.kind === hit.kind && Math.abs(prev.R - hit.R) < 1e-4 && Math.abs(prev.tx - hit.tx) < 1e-4 && Math.abs(prev.ty - hit.ty) < 1e-4) return;
      place.circHit = hit;
      const el = $('pf-r');
      if (el && hit) el.value = String(radNum(hit.R));
      placeTitle(); paintPlace(); return;
    }
    if (place && place.curveDim && cal) {
      if (!place.curve) {
        const hit = pickCurve(e.clientX, e.clientY);
        if ((hit && hit.idx) === (place.hoverCurve && place.hoverCurve.idx)) return;
        place.hoverCurve = hit; paintPlace(); return;
      }
      if (place.pts[0]) return;
      const w = pickWorld(e.clientX, e.clientY);
      if (placeHover && w.x === placeHover.x && w.y === placeHover.y && w.ref === placeHover.ref) return;
      placeHover = w; paintPlace(); return;
    }
    const slot = place ? place.pts.findIndex(p => p == null) : -1;
    if (!place || !cal || slot < 1) { if (placeHover) { placeHover = null; paintPlace(); } return; }
    let w = pickWorld(e.clientX, e.clientY);
    if (place.poly) w = snapPolyPlacePoint(w.x, w.y, w.ref);
    if (placeHover && w.x === placeHover.x && w.y === placeHover.y && w.ref === placeHover.ref) return;
    placeHover = w; paintPlace();
  };
  $('wrap').oncontextmenu = e => {
    if (!place) return;
    e.preventDefault();
    confirmPlace();
  };
  $('wrap').onmousedown = e => {
    if (e.button === 2) { if (place) e.preventDefault(); return; }
    if (e.target.closest && e.target.closest('.dot')) return;
    const onCanvas = e.target === $('wrap') || ($('stage') && $('stage').contains(e.target));
    if (place && place.adim && place.ang.segs.length < 2 && onCanvas && cal) {
      e.preventDefault();
      const hit = pickSeg(e.clientX, e.clientY);
      if (hit) acceptSeg(hit);
      return;
    }
    if (place && place.circ && place.pts[0] && onCanvas && cal) {
      e.preventDefault();
      const hit = circSnap(e.clientX, e.clientY);
      if (!hit || !(hit.R > 0.02)) return;
      const el = $('pf-r');
      if (el) el.value = String(radNum(hit.R));
      place.circHit = hit;
      confirmPlace();
      return;
    }
    if (place && place.curveDim && !place.curve && onCanvas && cal) {
      e.preventDefault();
      const hit = pickCurve(e.clientX, e.clientY);
      if (hit) { place.curve = hit; place.hoverCurve = null; paintPlaceForm(); }
      return;
    }
    if (place && place.n > 0 && onCanvas && cal) { e.preventDefault(); putPlace(pickWorld(e.clientX, e.clientY)); return; }
    if (e.target === $('wrap') || e.target === $('stage') || ($('svg') && $('svg').contains(e.target))) { e.preventDefault(); beginMarquee(e); }
  };
  $('code').onscroll = placeLine; $('code').oninput = hideLine;
  $('apply').onclick = () => {
    if (activeIdx >= 0 && planeAxesLocked(activeIdx) && $('planeaxes-extra') && $('planeaxes-extra').style.display !== 'none') {
      applyEdit(activeIdx, 0, 0, false);
      return;
    }
    const fx = parseFloat($('ix').value), fy = parseFloat($('iy').value); if (isNaN(fx)) return; const yv = isNaN(fy) ? 0 : fy;
    if (multiSet.size > 0) { if (fx !== 0 || yv !== 0) applyMultiMove(fx, yv); }
    else if (activeIdx >= 0) applyEdit(activeIdx, fx, yv, $('mv-all').checked);
  };
  $('ix').onkeydown = $('iy').onkeydown = e => { if (e.key === 'Enter') $('apply').click(); };
  ['ell-rx', 'ell-ry', 'ell-rot', 'pa-x0', 'pa-x1', 'pa-y0', 'pa-y1', 'pa-tx0', 'pa-tx1', 'pa-ty0', 'pa-ty1'].forEach(id => {
    const el = $(id); if (el) el.onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); $('apply').click(); } };
  });
  $('undo').onclick = () => { if (history.length > 1) { history.pop(); $('code').value = history.at(-1); go(false); } };
  $('run').onclick = () => go(false); $('zm').oninput = draw; $('sh-r').onchange = $('sh-b').onchange = $('sh-p').onchange = draw;
  $('code').onkeydown = e => {
    if (e.key === 'Tab') {
      e.preventDefault();
      const ta = $('code'), a = ta.selectionStart, b = ta.selectionEnd, pad = tabPad;
      const strip = new RegExp('^( {1,' + pad.length + '}|\\t)', 'gm');
      if (!e.shiftKey && a === b) { ta.setRangeText(pad, a, b, 'end'); return; }
      const start = ta.value.lastIndexOf('\n', Math.max(0, a - 1)) + 1;
      const block = ta.value.slice(start, b);
      const next = e.shiftKey ? block.replace(strip, '') : block.replace(/^[^\n]/gm, m => pad + m);
      ta.setRangeText(next, start, b, 'select');
      return;
    }
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); go(false); }
  };
  $('code').value = INIT_CODE; go(false);
};

