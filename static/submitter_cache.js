/** 提交人：首次必填，之后用 localStorage 记住本机填写值。 */
(function () {
  const KEY = 'cut_submitter';

  function bindSubmitterCache() {
    const el = document.querySelector('input[name="submitter"]');
    if (!el || el.disabled) return;
    el.required = true;
    if (!String(el.value || '').trim()) {
      const cached = localStorage.getItem(KEY);
      if (cached) el.value = cached;
    }
    const save = () => {
      const v = String(el.value || '').trim();
      if (v) localStorage.setItem(KEY, v);
    };
    el.addEventListener('change', save);
    el.addEventListener('blur', save);
    const form = el.closest('form');
    if (form) form.addEventListener('submit', save);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindSubmitterCache);
  } else {
    bindSubmitterCache();
  }
})();
