/**
 * 件明细防呆（失焦后再校验，输入过程中不打断）：
 * - 外框须小于标准板材（可旋转）
 * - 内孔须小于外框；内孔宽高同填或同空
 * 提交时再全表扫一遍。
 */
(function () {
  const SHEET_W = (window.CUT_SHEET && window.CUT_SHEET.w) || 120;
  const SHEET_H = (window.CUT_SHEET && window.CUT_SHEET.h) || 100;

  function num(v) {
    const s = String(v ?? '').trim();
    if (s === '') return null;
    const x = parseFloat(s);
    return Number.isFinite(x) ? x : NaN;
  }

  function fitsSheet(ow, oh) {
    return (ow < SHEET_W && oh < SHEET_H) || (ow < SHEET_H && oh < SHEET_W);
  }

  function clearRow(tr) {
    tr.classList.remove('row-invalid');
    tr.querySelectorAll('.field-invalid').forEach((el) => el.classList.remove('field-invalid'));
    const tip = tr.querySelector('.item-err');
    if (tip) tip.remove();
  }

  function mark(tr, fields, msg) {
    tr.classList.add('row-invalid');
    fields.forEach((name) => {
      const inp = tr.querySelector(`[name="${name}"]`);
      if (inp) inp.classList.add('field-invalid');
    });
    let tip = tr.querySelector('.item-err');
    if (!tip) {
      const cell = tr.lastElementChild || tr;
      tip = document.createElement('div');
      tip.className = 'item-err';
      cell.appendChild(tip);
    }
    tip.textContent = msg;
  }

  function validateRow(tr) {
    clearRow(tr);
    const owEl = tr.querySelector('[name="ow"]');
    if (!owEl) return true;

    const ow = num(owEl.value);
    const oh = num(tr.querySelector('[name="oh"]')?.value);
    const iw = num(tr.querySelector('[name="iw"]')?.value);
    const ih = num(tr.querySelector('[name="ih"]')?.value);
    const qty = num(tr.querySelector('[name="qty"]')?.value);

    const any =
      owEl.value.trim() ||
      (tr.querySelector('[name="oh"]')?.value || '').trim() ||
      (tr.querySelector('[name="iw"]')?.value || '').trim() ||
      (tr.querySelector('[name="ih"]')?.value || '').trim() ||
      (tr.querySelector('[name="qty"]')?.value || '').trim();
    if (!any) return true;

    if (ow === null || oh === null || !(ow > 0) || !(oh > 0)) {
      mark(tr, ['ow', 'oh'], '外框宽/高必须大于 0');
      return false;
    }
    if (!fitsSheet(ow, oh)) {
      mark(tr, ['ow', 'oh'], `外框须小于板材 ${SHEET_W}×${SHEET_H} cm（可旋转）`);
      return false;
    }
    if (qty === null || !(qty > 0)) {
      mark(tr, ['qty'], '数量必须大于 0');
      return false;
    }

    const hasW = iw !== null;
    const hasH = ih !== null;
    if (hasW !== hasH) {
      mark(tr, ['iw', 'ih'], '内孔宽和高要么都填，要么都空（实心）');
      return false;
    }
    if (hasW) {
      if (!(iw > 0) || !(ih > 0) || Number.isNaN(iw) || Number.isNaN(ih)) {
        mark(tr, ['iw', 'ih'], '内孔必须大于 0');
        return false;
      }
      if (iw >= ow || ih >= oh) {
        mark(tr, ['iw', 'ih'], '内孔必须小于外框（画框要留边）');
        return false;
      }
    }
    return true;
  }

  function validateAll(root) {
    const rows = (root || document).querySelectorAll('tr');
    let ok = true;
    rows.forEach((tr) => {
      if (tr.querySelector('[name="ow"]') && !validateRow(tr)) ok = false;
    });
    return ok;
  }

  // 失焦（换格/换行）后再校验当前行
  document.addEventListener('focusout', (e) => {
    const t = e.target;
    if (!t || !t.name) return;
    if (!['ow', 'oh', 'iw', 'ih', 'qty'].includes(t.name)) return;
    const tr = t.closest('tr');
    if (!tr) return;
    // 仍在同一行内换格：等焦点离开该行再校验，避免填一半就报错
    const next = e.relatedTarget;
    if (next && tr.contains(next)) return;
    validateRow(tr);
  });

  document.addEventListener('submit', (e) => {
    const form = e.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (!form.querySelector('[name="ow"]')) return;
    if (!validateAll(form)) {
      e.preventDefault();
      const bad = form.querySelector('.row-invalid');
      if (bad) bad.scrollIntoView({ behavior: 'smooth', block: 'center' });
      alert(`件尺寸有误：外框须小于板材 ${SHEET_W}×${SHEET_H} cm，内孔须小于外框。`);
    }
  }, true);
})();
