/**
 * background.js — Service worker for claude-candidate extension
 * Routes messages from the popup to the local backend API.
 */

importScripts('utils.js');

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
		const body = {
			posting_text: payload.description || '',
			company: payload.company || 'Unknown Company',
			title: payload.title || 'Unknown Position',
			posting_url: payload.url || null,
			requirements: payload.requirements || null,
			seniority: payload.seniority || 'unknown',
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
async function handleStartFullAssess(assessmentId, postingUrl) {
	// Clear any previous result for this URL
	if (postingUrl) await removeForUrl('fullReady', postingUrl);

	// Run in background — this continues even if popup closes
	handleAssessFull(assessmentId).then(async result => {
		if (result.success && result.assessment_phase === 'full') {
			if (postingUrl) {
				await setForUrl('fullReady', postingUrl, {
					assessmentId: result.assessment_id,
					url: postingUrl || '',
					data: result,
					completedAt: Date.now(),
				});
			}
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

/**
 * Batch assess: find all open job posting tabs, extract + assess each one.
 * Sends progress updates via chrome.storage.local.
 */
async function handleBatchAssess() {
	// Find tabs that look like job postings on any board
	const allTabs = await chrome.tabs.query({});
	console.log(`[batch] Found ${allTabs.length} total tabs`);
	const JOB_URL_PATTERNS = [
		/linkedin\.com\/jobs\/view\//,
		/boards\.greenhouse\.io\/.+\/jobs\//,
		/jobs\.lever\.co\//,
		/indeed\.com\/viewjob/,
		/careers\.|\/careers\//,
		/jobs\.|\/jobs\//,
		/ashbyhq\.com\/.+\/jobs\//,
		/apply\.workable\.com\//,
	];
	const jobTabs = allTabs.filter(t =>
		t.url && JOB_URL_PATTERNS.some(p => p.test(t.url))
	);
	console.log(`[batch] Found ${jobTabs.length} job posting tabs`);

	if (jobTabs.length === 0) {
		return { success: false, error: 'No job posting tabs found. Open some job postings first.' };
	}

	// Clear previous batch results and open dashboard immediately
	chrome.storage.local.set({
		batchProgress: { total: jobTabs.length, done: 0, current: '' },
		batchResults: [],
	});
	chrome.tabs.create({ url: chrome.runtime.getURL('dashboard.html') });

	const results = [];

	for (let i = 0; i < jobTabs.length; i++) {
		const tab = jobTabs[i];
		const tabUrl = tab.url;

		// Update progress
		chrome.storage.local.set({
			batchProgress: { total: jobTabs.length, done: i, current: tab.title || tabUrl },
		});

		try {
			console.log(`[batch] Processing ${i+1}/${jobTabs.length}: ${tab.url}`);
			// Inject content script and grab page text
			await chrome.scripting.executeScript({
				target: { tabId: tab.id },
				files: ['content.js'],
			});
			await new Promise(r => setTimeout(r, 200));

			const pageData = await new Promise((resolve, reject) => {
				chrome.tabs.sendMessage(tab.id, { action: 'extractJobPosting' }, resp => {
					if (chrome.runtime.lastError) {
						reject(new Error(chrome.runtime.lastError.message));
					} else {
						resolve(resp);
					}
				});
			});

			if (!pageData || !pageData.success || !pageData.pageData) {
				results.push({ url: tabUrl, error: 'Could not extract page text' });
				continue;
			}

			// Extract posting via server
			const extraction = await apiFetch('/api/extract-posting', {
				method: 'POST',
				body: JSON.stringify({
					url: pageData.pageData.url || tabUrl,
					title: pageData.pageData.title || '',
					text: pageData.pageData.text || '',
				}),
			});

			if (!extraction || !extraction.description) {
				results.push({ url: tabUrl, error: 'Extraction returned no description' });
				continue;
			}

			// Run partial assessment
			const assessment = await apiFetch('/api/assess/partial', {
				method: 'POST',
				body: JSON.stringify({
					posting_text: extraction.description || '',
					company: extraction.company || 'Unknown',
					title: extraction.title || 'Unknown',
					posting_url: tabUrl,
					requirements: extraction.requirements || null,
					seniority: extraction.seniority || 'unknown',
				}),
			});

			results.push({
				url: tabUrl,
				company: extraction.company || 'Unknown',
				title: extraction.title || 'Unknown',
				location: extraction.location || '',
				salary: extraction.salary || '',
				percentage: assessment.partial_percentage || 0,
				grade: assessment.overall_grade || '?',
				strongest: assessment.strongest_match || '',
				biggest_gap: assessment.biggest_gap || '',
			});
		} catch (err) {
			console.error(`[batch] Error on ${tabUrl}:`, err.message);
			results.push({ url: tabUrl, error: err.message });
		}

		// Update results incrementally so dashboard shows progress
		const sorted = [...results].sort((a, b) => (b.percentage || 0) - (a.percentage || 0));
		chrome.storage.local.set({
			batchProgress: { total: jobTabs.length, done: i + 1, current: tab.title || tabUrl },
			batchResults: sorted,
		});
	}

	// Sort by percentage descending
	results.sort((a, b) => (b.percentage || 0) - (a.percentage || 0));

	// Store final results
	chrome.storage.local.set({
		batchProgress: { total: jobTabs.length, done: jobTabs.length, current: 'Done' },
		batchResults: results,
	});

	return { success: true, total: jobTabs.length, results };
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
			promise = handleStartFullAssess(request.assessmentId, request.postingUrl);
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

		case 'batchAssess':
			// Fire-and-forget — don't await, return immediately
			handleBatchAssess().catch(err => console.error('Batch assess error:', err));
			promise = Promise.resolve({ success: true, started: true });
			break;

		case 'getProfileStatus':
			promise = apiFetch('/api/profile/status').catch(() => ({}));
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
