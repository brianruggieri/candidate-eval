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

async function handleAssessPartial(payload) {
	try {
		const body = {
			posting_text: payload.description || '',
			company: payload.company || 'Unknown Company',
			title: payload.title || 'Unknown Position',
			posting_url: payload.url || null,
			requirements: payload.requirements || null,
			seniority: payload.seniority || 'unknown',
		};
		const data = await apiFetch('/api/assess/partial', {
			method: 'POST',
			body: JSON.stringify(body),
		});
		return { success: true, ...data };
	} catch (err) {
		return { success: false, error: err.message };
	}
}

async function handleAssessFull(assessmentId) {
	try {
		const data = await apiFetch('/api/assess/full', {
			method: 'POST',
			body: JSON.stringify({ assessment_id: assessmentId }),
		});
		return { success: true, ...data };
	} catch (err) {
		return { success: false, error: err.message };
	}
}

/**
 * Fire-and-forget: start full assessment in background, store result when done.
 * Survives popup close. Popup checks fullAssessmentReady on reopen.
 */
async function handleStartFullAssess(assessmentId) {
	// Clear any previous result
	chrome.storage.local.remove('fullAssessmentReady');

	// Run in background — this continues even if popup closes
	handleAssessFull(assessmentId).then(result => {
		if (result.success && result.assessment_phase === 'full') {
			chrome.storage.local.set({
				fullAssessmentReady: {
					assessmentId: result.assessment_id,
					data: result,
					completedAt: Date.now(),
				}
			});
		}
	});

	// Return immediately — don't wait for Claude
	return { success: true, started: true };
}

async function handleExtractPosting(payload) {
	try {
		const data = await apiFetch('/api/extract-posting', {
			method: 'POST',
			body: JSON.stringify({
				url: payload.url || '',
				title: payload.title || '',
				text: payload.text || '',
			}),
		});
		return { success: true, ...data };
	} catch (err) {
		return { success: false, error: err.message };
	}
}

async function handleAddToShortlist(payload) {
	try {
		// Map extension fields to server API fields
		const body = {
			company_name: payload.company || payload.company_name || '',
			job_title: payload.title || payload.job_title || '',
			posting_url: payload.url || payload.posting_url || null,
			assessment_id: payload.assessment_id || null,
			salary: payload.salary || null,
			location: payload.location || null,
			overall_grade: payload.overall_grade || null,
			notes: payload.notes || null,
		};
		const data = await apiFetch('/api/shortlist', {
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

		case 'assessPartial':
			promise = handleAssessPartial(request.payload);
			break;

		case 'assessFull':
			promise = handleAssessFull(request.assessmentId);
			break;

		case 'startFullAssess':
			promise = handleStartFullAssess(request.assessmentId);
			break;

		case 'extractPosting':
			promise = handleExtractPosting(request.payload);
			break;

		case 'getAssessment':
			promise = handleGetAssessment(request.id);
			break;

		case 'addToShortlist':
			promise = handleAddToShortlist(request.payload);
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
