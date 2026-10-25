// A way into the TLC screens from any desk page. Frappe HR's own workspaces are not ours to rewrite, so the entry
// sits in the page actions and opens the short list: the six-step board, the applicant list, the AI ledger, the
// assistant tab and the letter templates.
(() => {
	const ITEMS = [
		["Tuyển dụng AI 6 bước (Kanban)", "/desk/job-applicant/view/kanban/TLC%20Tuy%E1%BB%83n%20d%E1%BB%A5ng%206%20b%C6%B0%E1%BB%9Bc"],
		["Ứng viên và chấm CV", "/desk/job-applicant"],
		["Nhật ký AI", "/desk/tlc-ai-trace-log"],
		["Trợ lý AI (Chat)", "/desk/tro-ly-ai"],
		["Mẫu thư tuyển dụng", "/desk/email-template"],
	];
	const ROLES = ["TLC HR Lead", "TLC HR Officer", "TLC Director", "System Manager"];

	function open() {
		frappe.msgprint({
			title: __("TLC HR — tuyển dụng AI và trợ lý"),
			indicator: "green",
			message: ITEMS.map(([label, href]) =>
				`<p style="margin:0 0 6px"><a href="${href}">${label}</a></p>`).join(""),
		});
	}

	function attach() {
		if (document.querySelector(".tlc-hub-entry")) return;
		if (!frappe.session || frappe.session.user === "Guest") return;
		if (!ROLES.some((role) => (frappe.user_roles || []).includes(role))) return;
		const host = document.querySelector(".standard-actions") || document.querySelector(".page-actions");
		if (!host) return;
		const button = document.createElement("button");
		button.className = "btn btn-default btn-sm tlc-hub-entry";
		button.style.marginRight = "6px";
		button.textContent = __("TLC AI");
		button.title = __("Kanban 6 bước · Nhật ký AI · Trợ lý AI");
		button.onclick = open;
		host.prepend(button);
	}

	frappe.router.on("change", () => setTimeout(attach, 900));
	frappe.after_ajax(() => setTimeout(attach, 900));
	setInterval(attach, 4000);
})();
