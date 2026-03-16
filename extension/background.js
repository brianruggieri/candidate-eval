/**
 * background.js — Service worker for claude-candidate extension
 * Routes messages from the popup to the local backend API.
 */

const API_BASE = 'http://localhost:7429';

// ─── Helpers ────────────────────────────────────────────────────────────────

async function apiFetch(path, options = {}) {
	const url = `${API_BASE}${path}`;
	const response = await fetch(url, {
		headers: { 'Content-Type': 'application/json', ...options.headers },
		...options,
	});

	let data;
	try {
		data = await response.json();
	} catch {
		data = null;
	}

	if (!response.ok) {
		const message = (data && (data.detail || data.error || data.message)) ||
			`HTTP ${response.status}`;
		throw new Error(message);
	}

	return data;
}

// ─── Message Handlers ────────────────────────────────────────────────────────

async function handleCheckBackend() {
	try {
		const data = await apiFetch('/api/health');
		return { connected: true, ...data };
	} catch (err) {
		return { connected: false, error: err.message };
	}
}

async function handleAssess(payload) {
	try {
		// Map extension field names to server API field names
		const body = {
			posting_text: payload.description || '',
			company: payload.company || 'Unknown Company',
			title: payload.title || 'Unknown Position',
			posting_url: payload.url || null,
		};
		const data = await apiFetch('/api/assess', {
			method: 'POST',
			body: JSON.stringify(body),
		});
		return { success: true, ...data };
	} catch (err) {
		return { success: false, error: err.message };
	}
}

async function handleGetAssessment(id) {
	try {
		const data = await apiFetch(`/api/assessments/${id}`);
		return { success: true, ...data };
	} catch (err) {
		return { success: false, error: err.message };
	}
}

async function handleAddToWatchlist(payload) {
	try {
		// Map extension fields to server API fields
		const body = {
			company_name: payload.company || payload.company_name || '',
			job_title: payload.title || payload.job_title || '',
			posting_url: payload.url || payload.posting_url || null,
			assessment_id: payload.assessment_id || null,
			notes: payload.notes || null,
		};
		const data = await apiFetch('/api/watchlist', {
			method: 'POST',
			body: JSON.stringify(body),
		});
		return { success: true, ...data };
	} catch (err) {
		return { success: false, error: err.message };
	}
}

// ─── Message Listener ────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener(function (request, _sender, sendResponse) {
	const { action } = request;

	let promise;

	switch (action) {
		case 'checkBackend':
			promise = handleCheckBackend();
			break;

		case 'assess':
			promise = handleAssess(request.payload);
			break;

		case 'getAssessment':
			promise = handleGetAssessment(request.id);
			break;

		case 'addToWatchlist':
			promise = handleAddToWatchlist(request.payload);
			break;

		default:
			sendResponse({ error: `Unknown action: ${action}` });
			return false;
	}

	// Handle the promise and send response
	promise
		.then(sendResponse)
		.catch((err) => sendResponse({ error: err.message || 'Unknown error' }));

	return true; // keep message channel open for async response
});
