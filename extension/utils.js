// extension/utils.js
/**
 * Shared utilities for URL normalization and per-URL keyed storage.
 * Loaded via <script> in popup.html and importScripts() in background.js.
 */

const TRACKING_PARAMS = /^(utm_\w+|trk|eBP|trackingId|tracking_id|refId|fbclid|gclid|mc_[ce]id|_hsenc|_hsmi)$/i;

/**
 * Normalize a URL for use as a storage key.
 * Strips tracking params, hash fragments, and trailing slashes. Sorts remaining params.
 */
function normalizeUrl(u) {
	try {
		const url = new URL(u || '');
		[...url.searchParams.keys()].forEach(k => {
			if (TRACKING_PARAMS.test(k)) url.searchParams.delete(k);
		});
		url.searchParams.sort();
		url.hash = '';
		return url.origin + url.pathname.replace(/\/+$/, '') + url.search;
	} catch {
		return (u || '').replace(/[?#].*$/, '').replace(/\/+$/, '');
	}
}

/**
 * Build a per-URL storage key: "prefix:{normalizedUrl}"
 */
function _urlKey(prefix, url) {
	return `${prefix}:${normalizeUrl(url)}`;
}

/**
 * Get a value scoped to a URL from chrome.storage.local.
 * Returns null if not found.
 */
async function getForUrl(prefix, url) {
	const key = _urlKey(prefix, url);
	const result = await chrome.storage.local.get(key);
	return result[key] || null;
}

/**
 * Set a value scoped to a URL in chrome.storage.local.
 */
async function setForUrl(prefix, url, value) {
	const key = _urlKey(prefix, url);
	await chrome.storage.local.set({ [key]: value });
}

/**
 * Remove a value scoped to a URL from chrome.storage.local.
 */
async function removeForUrl(prefix, url) {
	const key = _urlKey(prefix, url);
	await chrome.storage.local.remove(key);
}

// Expose on globalThis for popup.js (loaded via <script>) and background.js (importScripts)
if (typeof globalThis !== 'undefined') {
	globalThis.normalizeUrl = normalizeUrl;
	globalThis.getForUrl = getForUrl;
	globalThis.setForUrl = setForUrl;
	globalThis.removeForUrl = removeForUrl;
}

// Also support ES module import for vitest
if (typeof module !== 'undefined' && module.exports) {
	module.exports = { normalizeUrl, getForUrl, setForUrl, removeForUrl };
}
