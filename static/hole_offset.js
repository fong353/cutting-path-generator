/**
 * 中孔偏移（画框）傻瓜化二级弹窗 + SVG 图示。
 * 用法：每行件带 .hole-left / .hole-bottom hidden，按钮 data-hole-btn。
 */
(function () {
  function el(tag, attrs, html) {
    const n = document.createElement(tag);
    if (attrs) Object.entries(attrs).forEach(([k, v]) => {
      if (k === 'className') n.className = v;
      else n.setAttribute(k, v);
    });
    if (html != null) n.innerHTML = html;
    return n;
  }

  function num(v) {
    const x = parseFloat(v);
    return Number.isFinite(x) ? x : NaN;
  }

  function openHoleOffsetModal(tr) {
    const ow = num(tr.querySelector('[name="ow"]')?.value);
    const oh = num(tr.querySelector('[name="oh"]')?.value);
    const iw = num(tr.querySelector('[name="iw"]')?.value);
    const ih = num(tr.querySelector('[name="ih"]')?.value);
    const hlInput = tr.querySelector('[name="hole_left"]');
    const hbInput = tr.querySelector('[name="hole_bottom"]');

    if (!(ow > 0 && oh > 0 && iw > 0 && ih > 0)) {
      alert('请先填写外框宽高和内孔宽高（画框），再设置中孔偏移。');
      return;
    }
    if (iw >= ow || ih >= oh) {
      alert('内孔必须小于外框。');
      return;
    }

    const hasCustom = hlInput.value !== '' && hbInput.value !== '';
    const defL = (ow - iw) / 2;
    const defB = (oh - ih) / 2;

    const mask = el('div', { className: 'hole-modal-mask' });
    const box = el('div', { className: 'hole-modal' });
    box.innerHTML = `
      <h2>中孔偏移（画框）</h2>
      <p class="muted">成品是<strong>外框减掉中间孔</strong>剩下的一圈边。下面图里彩色条就是四边边距。</p>
      <label class="check" style="margin-bottom:12px">
        <input type="checkbox" id="holeCentered" ${hasCustom ? '' : 'checked'}>
        孔在正中间（四边一样宽，推荐）
      </label>
      <div id="holeCustom" style="${hasCustom ? '' : 'display:none'}">
        <p class="muted">只填「左边距」「下边距」（外框边 → 孔边）。右边、上边自动算出来，看图核对。</p>
        <div class="row cols-2">
          <div>
            <label>← 左边距（cm）</label>
            <input id="holeL" inputmode="decimal" value="${hasCustom ? hlInput.value : defL.toFixed(2)}">
          </div>
          <div>
            <label>↓ 下边距（cm）</label>
            <input id="holeB" inputmode="decimal" value="${hasCustom ? hbInput.value : defB.toFixed(2)}">
          </div>
        </div>
        <p id="holeAuto" class="muted"></p>
      </div>
      <div class="hole-svg-wrap" id="holeSvg"></div>
      <div class="hole-legend" id="holeLegend"></div>
      <p id="holeErr" class="err" style="display:none"></p>
      <div class="actions">
        <button type="button" class="btn secondary" id="holeCancel">取消</button>
        <button type="button" class="btn" id="holeOk">确定</button>
      </div>
    `;
    mask.appendChild(box);
    document.body.appendChild(mask);

    const centered = box.querySelector('#holeCentered');
    const custom = box.querySelector('#holeCustom');
    const inpL = box.querySelector('#holeL');
    const inpB = box.querySelector('#holeB');
    const autoP = box.querySelector('#holeAuto');
    const errP = box.querySelector('#holeErr');
    const svgWrap = box.querySelector('#holeSvg');
    const legend = box.querySelector('#holeLegend');

    function state() {
      if (centered.checked) {
        return { l: defL, b: defB, centered: true };
      }
      return { l: num(inpL.value), b: num(inpB.value), centered: false };
    }

    function dimLine(x1, y1, x2, y2, label, color) {
      const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
      const dx = x2 - x1, dy = y2 - y1;
      const len = Math.hypot(dx, dy) || 1;
      const nx = (-dy / len) * 6, ny = (dx / len) * 6; // 短端线
      return `
        <line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${color}" stroke-width="1.5"/>
        <line x1="${x1 - nx}" y1="${y1 - ny}" x2="${x1 + nx}" y2="${y1 + ny}" stroke="${color}" stroke-width="1.5"/>
        <line x1="${x2 - nx}" y1="${y2 - ny}" x2="${x2 + nx}" y2="${y2 + ny}" stroke="${color}" stroke-width="1.5"/>
        <text x="${mx + nx * 1.8}" y="${my + ny * 1.8 + 4}" text-anchor="middle" font-size="12" font-weight="700" fill="${color}">${label}</text>`;
    }

    function redraw() {
      const s = state();
      let ok = true;
      let msg = '';
      if (!s.centered) {
        if (!(s.l >= 0) || !(s.b >= 0) || Number.isNaN(s.l) || Number.isNaN(s.b)) {
          ok = false; msg = '左边距、下边距需 ≥ 0';
        } else if (s.l + iw > ow + 1e-6 || s.b + ih > oh + 1e-6) {
          ok = false; msg = '孔超出外框了，请减小边距或内孔';
        }
      }
      const l = ok ? s.l : defL;
      const b = ok ? s.b : defB;
      const r = ow - l - iw;
      const t = oh - b - ih;
      autoP.textContent = ok
        ? `自动算出：右边距 ${r.toFixed(2)} cm，上边距 ${t.toFixed(2)} cm`
        : '';
      errP.style.display = ok ? 'none' : 'block';
      errP.textContent = msg;

      const padL = 52, padR = 52, padT = 36, padB = 48;
      const maxW = 280, maxH = 200;
      const sc = Math.min(maxW / ow, maxH / oh);
      const W = ow * sc, H = oh * sc;
      const ox = padL, oy = padT;
      const hx = ox + l * sc;
      const hy = oy + t * sc;
      const hw = iw * sc, hh = ih * sc;
      const lw = l * sc, rw = r * sc, tw = t * sc, bw = b * sc;

      // 四边色块：整条边距带（更好认）
      const leftBand = lw > 0.5 ? `<rect x="${ox}" y="${oy}" width="${lw}" height="${H}" fill="#fde68a" opacity="0.92"/>` : '';
      const rightBand = rw > 0.5 ? `<rect x="${hx + hw}" y="${oy}" width="${rw}" height="${H}" fill="#bbf7d0" opacity="0.92"/>` : '';
      const topBand = tw > 0.5 ? `<rect x="${ox}" y="${oy}" width="${W}" height="${tw}" fill="#bfdbfe" opacity="0.85"/>` : '';
      const botBand = bw > 0.5 ? `<rect x="${ox}" y="${hy + hh}" width="${W}" height="${bw}" fill="#fecaca" opacity="0.85"/>` : '';

      // 角上重合区用外框填充色即可；四边带宽条盖住画框区
      svgWrap.innerHTML = `
        <svg width="${W + padL + padR}" height="${H + padT + padB}" xmlns="http://www.w3.org/2000/svg">
          <rect x="${ox}" y="${oy}" width="${W}" height="${H}" fill="#e7d3b0" stroke="#8b5a2b" stroke-width="2"/>
          ${topBand}${botBand}${leftBand}${rightBand}
          <rect x="${hx}" y="${hy}" width="${hw}" height="${hh}" fill="#ffffff" stroke="#1d4ed8" stroke-width="2"/>
          <text x="${hx + hw / 2}" y="${hy + hh / 2 + 4}" text-anchor="middle" font-size="13" font-weight="700" fill="#1d4ed8">孔（挖空）</text>
          ${lw > 2 ? dimLine(ox, hy + hh / 2, hx, hy + hh / 2, `左 ${l.toFixed(1)}`, '#b45309') : ''}
          ${rw > 2 ? dimLine(hx + hw, hy + hh / 2, ox + W, hy + hh / 2, `右 ${r.toFixed(1)}`, '#15803d') : ''}
          ${tw > 2 ? dimLine(ox + W / 2, oy, ox + W / 2, hy, `上 ${t.toFixed(1)}`, '#1d4ed8') : ''}
          ${bw > 2 ? dimLine(ox + W / 2, hy + hh, ox + W / 2, oy + H, `下 ${b.toFixed(1)}`, '#b91c1c') : ''}
          <text x="${ox + W / 2}" y="${oy + H + 28}" text-anchor="middle" font-size="12" fill="#027a48">彩色条 = 每边边距（画框宽度）</text>
        </svg>`;

      legend.innerHTML = `
        <div class="hole-legend-row">
          <span><i class="swatch" style="background:#bfdbfe"></i>上边距 <b>${t.toFixed(2)}</b> cm</span>
          <span><i class="swatch" style="background:#fecaca"></i>下边距 <b>${b.toFixed(2)}</b> cm</span>
          <span><i class="swatch" style="background:#fde68a"></i>左边距 <b>${l.toFixed(2)}</b> cm</span>
          <span><i class="swatch" style="background:#bbf7d0"></i>右边距 <b>${r.toFixed(2)}</b> cm</span>
        </div>
        <div class="hole-legend-row muted">外框 ${ow}×${oh} cm · 孔 ${iw}×${ih} cm · 中间白=挖掉 · 四周色=留下的画框</div>`;
      return ok;
    }

    centered.addEventListener('change', () => {
      custom.style.display = centered.checked ? 'none' : 'block';
      redraw();
    });
    inpL.addEventListener('input', redraw);
    inpB.addEventListener('input', redraw);
    redraw();

    function close() { mask.remove(); }
    box.querySelector('#holeCancel').onclick = close;
    mask.addEventListener('click', (e) => { if (e.target === mask) close(); });
    box.querySelector('#holeOk').onclick = () => {
      if (!redraw()) return;
      const s = state();
      if (s.centered) {
        hlInput.value = '';
        hbInput.value = '';
      } else {
        hlInput.value = String(s.l);
        hbInput.value = String(s.b);
      }
      const tip = tr.querySelector('.hole-tip');
      if (tip) {
        tip.textContent = s.centered ? '居中' : `偏 L${s.l} 下${s.b}`;
      }
      close();
    };
  }

  window.openHoleOffsetModal = openHoleOffsetModal;

  document.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-hole-btn]');
    if (!btn) return;
    const tr = btn.closest('tr');
    if (tr) openHoleOffsetModal(tr);
  });
})();
