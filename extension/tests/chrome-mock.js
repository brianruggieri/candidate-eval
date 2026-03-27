/**
 * Minimal chrome.storage.local mock for vitest.
 * Stores data in a plain Map. All callbacks are synchronous for test simplicity.
 */
const store = new Map();

export function resetStore() {
	store.clear();
}

export const chrome = {
	storage: {
		local: {
			get(keys, cb) {
				const result = {};
				const keyList = Array.isArray(keys) ? keys : [keys];
				for (const k of keyList) {
					if (store.has(k)) result[k] = structuredClone(store.get(k));
				}
				if (cb) cb(result);
				return Promise.resolve(result);
			},
			set(items, cb) {
				for (const [k, v] of Object.entries(items)) {
					store.set(k, structuredClone(v));
				}
				if (cb) cb();
				return Promise.resolve();
			},
			remove(keys, cb) {
				const keyList = Array.isArray(keys) ? keys : [keys];
				for (const k of keyList) store.delete(k);
				if (cb) cb();
				return Promise.resolve();
			},
		},
	},
	tabs: {
		query(opts, cb) {
			const tabs = [{ url: 'https://www.linkedin.com/jobs/view/12345' }];
			if (cb) cb(tabs);
			return Promise.resolve(tabs);
		},
	},
};
