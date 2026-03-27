export default {
	async fetch(request, env) {
		const url = new URL(request.url);
		let path = url.pathname.replace(/^\/fit\/?/, '');

		// Default to index.html for directory-style URLs
		if (!path || path.endsWith('/')) {
			path = path + 'index.html';
		}
		if (!path.endsWith('.html')) {
			path = path + '/index.html';
		}

		const object = await env.FIT_PAGES.get(path);
		if (!object) {
			return new Response('Not found', { status: 404 });
		}

		return new Response(object.body, {
			headers: {
				'Content-Type': 'text/html; charset=utf-8',
				'Cache-Control': 'public, max-age=3600',
				'X-Robots-Tag': 'noindex, nofollow',
			},
		});
	},
};
