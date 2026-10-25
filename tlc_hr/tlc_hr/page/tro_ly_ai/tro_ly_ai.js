frappe.pages["tro-ly-ai"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Trợ lý HR (AI)"),
		single_column: true,
	});
	const style = "width:100%;height:calc(100vh - 190px);min-height:520px;border:0;border-radius:8px;background:#fff";
	page.main.html(`
		<div class="tlc-chat-note" style="padding:8px 0 12px;color:var(--text-muted)">
			${__("Chat nội bộ và trợ lý AI của dữ liệu mẫu TLC. Trợ lý chỉ đọc dữ liệu của chính bạn, chỉ tạo nháp và không tự gửi duyệt, duyệt, ký hay thanh toán.")}
		</div>
		<div class="tlc-chat-frame" style="position:relative">
			<div class="tlc-chat-loading text-muted small" style="padding:24px">${__("Đang mở hội thoại với trợ lý…")}</div>
			<iframe class="tlc-chat-iframe" title="Raven" style="${style};display:none"></iframe>
		</div>
	`);
	const frame = page.main.find(".tlc-chat-iframe");
	const show = (src) => {
		frame.attr("src", src).show();
		page.main.find(".tlc-chat-loading").hide();
	};
	page.add_inner_button(__("Mở Raven"), () => window.open("/raven", "_blank"));
	page.add_inner_button(__("Làm mới"), () => frame.attr("src", frame.attr("src")));
	frappe.call({
		method: "raven.api.raven_channel.get_all_channels",
		args: { hide_archived: "false" },
		callback: ({ message }) => {
			const dms = (message && message.dm_channels) || [];
			const bot = dms.find((c) => /assistant/i.test(c.peer_user_id || "") || /Assistant/i.test(c.channel_name || ""));
			show(bot ? `/raven/dm-channel/${bot.name}` : "/raven");
		},
		error: () => show("/raven"),
	});
};
