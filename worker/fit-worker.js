function getContentType(path) {
	const ext = path.split(".").pop().toLowerCase();
	const types = {
		html: "text/html; charset=utf-8",
		css: "text/css; charset=utf-8",
		js: "application/javascript; charset=utf-8",
		json: "application/json; charset=utf-8",
		woff2: "font/woff2",
		woff: "font/woff",
		ttf: "font/ttf",
		otf: "font/otf",
		png: "image/png",
		jpg: "image/jpeg",
		jpeg: "image/jpeg",
		svg: "image/svg+xml",
		ico: "image/x-icon",
	};
	return types[ext] || "application/octet-stream";
}

export default {
	async fetch(request, env) {
		const url = new URL(request.url);
		let path = url.pathname.replace(/^\/fit\/?/, "");

		// Reject path traversal attempts
		if (path.includes("..")) {
			return new Response("Bad request", { status: 400 });
		}

		// Default to index.html for directory-style or extensionless URLs
		if (!path || path.endsWith("/")) {
			path = path + "index.html";
		} else if (!path.includes(".")) {
			path = path + "/index.html";
		}

		const object = await env.FIT_PAGES.get(path);
		if (!object) {
			return new Response("Not found", { status: 404 });
		}

		return new Response(object.body, {
			headers: {
				"Content-Type": getContentType(path),
				"Cache-Control": "public, max-age=3600",
				"X-Robots-Tag": "noindex, nofollow",
			},
		});
	},
};
