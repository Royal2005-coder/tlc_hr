/* TLC People: actions shared by every page (leave request dialog, decisions, withdraw, tabs, filters). */
(function () {
  const CSRF = document.body.dataset.tpCsrf;
  const $ = (s, el) => (el || document).querySelector(s);
  const $$ = (s, el) => Array.from((el || document).querySelectorAll(s));
  const fmt = (n) => (Math.round(n * 10) / 10).toString().replace(".", ",");

  function toast(text, ok) {
    const el = $("#tp-toast");
    el.textContent = text; el.className = ok ? "ok" : "bad"; el.style.display = "block";
    clearTimeout(el._t); el._t = setTimeout(() => (el.style.display = "none"), 4500);
  }
  async function call(method, args) {
    const res = await fetch("/api/method/" + method, {
      method: "POST", headers: {"Content-Type": "application/json", "X-Frappe-CSRF-Token": CSRF}, body: JSON.stringify(args || {})});
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      let msg = "Không thực hiện được.";
      try { msg = JSON.parse(JSON.parse(data._server_messages)[0]).message; }
      catch (e) { if (data.exception) msg = data.exception.split(":").slice(1).join(":"); }
      throw new Error(String(msg).replace(/<[^>]+>/g, "").trim());
    }
    return data.message;
  }
  const reloadSoon = () => setTimeout(() => location.reload(), 1400);

  /* leave request dialog with a live preview of days and balance */
  const modal = $("#tp-leave");
  window.tpOpenLeave = function () {
    if (!modal) return;
    modal.classList.add("open");
    setTimeout(() => $("#lf-from").focus(), 50);
  };
  window.tpCloseLeave = function () { modal && modal.classList.remove("open"); };
  let previewTimer;
  async function preview() {
    const f = $("#tp-leave-form"); const box = $("#lf-preview"); const warn = $("#lf-warn");
    if (!f.from_date.value || !f.to_date.value) { box.hidden = true; return; }
    try {
      const r = await call("tlc_hr.api.preview_leave", {leave_type: f.leave_type.value, from_date: f.from_date.value,
        to_date: f.to_date.value, half_day: f.half_day.checked ? 1 : 0});
      box.hidden = false;
      $("#lp-days").textContent = fmt(r.days); $("#lp-now").textContent = fmt(r.balance); $("#lp-after").textContent = fmt(r.after);
      box.classList.toggle("bad", r.after < 0);
      warn.hidden = !(r.after < 0 || r.days === 0);
      warn.textContent = r.days === 0 ? "Khoảng ngày này không có ngày làm việc nào (cuối tuần hoặc ngày lễ)."
                                      : "Số ngày xin vượt số ngày phép còn lại. Hãy rút ngắn hoặc chọn loại nghỉ khác.";
      $("#lf-submit").disabled = r.after < 0 || r.days === 0;
    } catch (e) { box.hidden = true; warn.hidden = false; warn.textContent = e.message; $("#lf-submit").disabled = true; }
  }
  const onLeaveInput = (ev) => {
    if (ev.target.closest && ev.target.closest("#tp-leave-form")) {
      const f = $("#tp-leave-form");
      if (ev.target.name === "from_date" && (!f.to_date.value || f.to_date.value < f.from_date.value)) f.to_date.value = f.from_date.value;
      clearTimeout(previewTimer); previewTimer = setTimeout(preview, 200);
    }
  };
  document.addEventListener("change", onLeaveInput);
  document.addEventListener("input", onLeaveInput);
  window.tpSubmitLeave = async function (ev) {
    ev.preventDefault();
    const f = ev.target; const btn = $("#lf-submit"); btn.disabled = true;
    try {
      const r = await call("tlc_hr.api.submit_leave", {leave_type: f.leave_type.value, from_date: f.from_date.value,
        to_date: f.to_date.value, half_day: f.half_day.checked ? 1 : 0, reason: f.reason.value});
      tpCloseLeave();
      toast("Đã gửi đơn " + r.name + " (" + fmt(r.total_leave_days) + " ngày) — " + r.workflow_state, true);
      reloadSoon();
    } catch (e) { toast(e.message, false); btn.disabled = false; }
    return false;
  };

  /* decisions and withdraw */
  window.tpToggleReject = (name) => { const el = $("#reject-" + name); el.classList.toggle("open"); $("textarea", el).focus(); };
  window.tpDecide = async function (btn, name, decision) {
    const reason = decision === "reject" ? $("#reject-" + name + " textarea").value : null;
    btn.disabled = true;
    try {
      const r = await call("tlc_hr.api.decide", {name, decision, reason});
      toast((decision === "approve" ? "Đã duyệt " : "Đã từ chối ") + r.name + " — " + r.workflow_state, true);
      reloadSoon();
    } catch (e) { toast(e.message, false); btn.disabled = false; }
  };
  window.tpWithdraw = async function (btn, name) {
    if (!confirm("Rút đơn " + name + "? Đơn sẽ bị xoá và người duyệt không còn thấy nữa.")) return;
    btn.disabled = true;
    try { await call("tlc_hr.api.withdraw", {name}); toast("Đã rút đơn " + name, true); reloadSoon(); }
    catch (e) { toast(e.message, false); btn.disabled = false; }
  };

  /* tabs, menu, filters */
  $$("[data-tp-tabs]").forEach((bar) => {
    $$("button", bar).forEach((b) => b.addEventListener("click", () => {
      $$("button", bar).forEach((x) => x.classList.toggle("on", x === b));
      $$(".tp-pane", bar.parentElement).forEach((p) => p.classList.toggle("on", p.id === b.dataset.pane));
      history.replaceState(null, "", "#" + b.dataset.pane);
    }));
    const wanted = location.hash.slice(1);
    const start = wanted && $(`button[data-pane="${wanted}"]`, bar);
    if (start) { start.click(); window.scrollTo(0, 0); }
  });
  const userBtn = $("#tp-user-btn");
  if (userBtn) {
    userBtn.addEventListener("click", (e) => { e.stopPropagation(); $("#tp-menu").classList.toggle("open"); });
    document.addEventListener("click", () => $("#tp-menu").classList.remove("open"));
  }
  const q = $("#tp-people-q");
  if (q) {
    const apply = () => {
      const text = q.value.trim().toLowerCase(); const site = $("#tp-people-site").value; const wf = $("#tp-people-wf").value;
      let shown = 0;
      $$("[data-person]").forEach((card) => {
        const ok = (!text || card.dataset.search.includes(text)) && (!site || card.dataset.site === site) && (!wf || card.dataset.wf === wf);
        card.hidden = !ok; if (ok) shown++;
      });
      $("#tp-people-count").textContent = shown;
    };
    [q, $("#tp-people-site"), $("#tp-people-wf")].forEach((el) => el.addEventListener("input", apply));
  }
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") tpCloseLeave(); });
  if (location.hash === "#xin-nghi") tpOpenLeave();
})();
