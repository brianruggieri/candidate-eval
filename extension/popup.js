'use strict';

const STATES = ['loading', 'no-backend', 'no-profile', 'no-job', 'assessing', 'results', 'error'];
const POSTING_TTL_MS = 5 * 60 * 1000;

function el(id) { return document.getElementById(id); }

function showState(name) {
	STATES.forEach(s => {
		const node = el(`state-${s}`);
		if (node) node.classList.toggle('hidden', s !== name);
	});
}

function sendToBackground(msg) {
	return new Promise(resolve => {
		chrome.runtime.sendMessage(msg, r => resolve(r || {}));
	});
}

async function injectAndSend(msg) {
	const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
	if (!tabs || !tabs.length) return { success: false, error: 'No active tab' };
	const tabId = tabs[0].id;

	try {
		await chrome.scripting.executeScript({
			target: { tabId },
			files: ['content.js'],
		});
	} catch (err) {
		return { success: false, error: 'Cannot inject script: ' + (err.message || '') };
	}

	await new Promise(r => setTimeout(r, 100));

	return new Promise(resolve => {
		chrome.tabs.sendMessage(tabId, msg, r => {
			if (chrome.runtime.lastError) {
				resolve({ success: false, error: chrome.runtime.lastError.message });
			} else {
				resolve(r || {});
			}
		});
	});
}

function scoreToGrade(s) {
	if (s >= 0.93) return 'A+'; if (s >= 0.90) return 'A'; if (s >= 0.87) return 'A-';
	if (s >= 0.83) return 'B+'; if (s >= 0.80) return 'B'; if (s >= 0.77) return 'B-';
	if (s >= 0.73) return 'C+'; if (s >= 0.70) return 'C'; if (s >= 0.67) return 'C-';
	if (s >= 0.63) return 'D+'; if (s >= 0.60) return 'D'; return 'F';
}

function barColor(score) {
	if (score >= 0.75) return 'green';
	if (score >= 0.50) return 'yellow';
	if (score >= 0.30) return 'blue';
	return 'red';
}

function pct(score) { return Math.round(score * 100) + '%'; }

let currentAssessment = null;
let currentPosting = null;

function renderResults(data) {
	currentAssessment = data;

	// Header
	el('results-company').textContent = data.company_name || currentPosting?.company || '';
	el('results-title').textContent = data.job_title || currentPosting?.title || 'Unknown Role';

	const overall = data.overall_score;
	const grade = data.overall_grade || scoreToGrade(overall);
	const gradeEl = el('results-grade');
	gradeEl.textContent = grade;
	gradeEl.dataset.grade = grade;

	// Overall bar
	requestAnimationFrame(() => {
		el('bar-overall').style.width = pct(overall);
	});
	el('pct-overall').textContent = pct(overall);

	// Summary
	el('results-summary').textContent = data.overall_summary || '';

	// Three dimensions — server returns nested objects
	function setDim(key, barId, pctId, detailId) {
		const dim = data[key]; // e.g. data.skill_match = {score, grade, summary, details}
		if (!dim) return;
		const score = dim.score || 0;
		const fill = el(barId);
		requestAnimationFrame(() => {
			fill.style.width = pct(score);
			fill.className = 'dim-fill ' + barColor(score);
		});
		el(pctId).textContent = `${pct(score)} ${dim.grade || scoreToGrade(score)}`;
		el(detailId).textContent = dim.summary || '';
	}

	setDim('skill_match', 'bar-skills', 'pct-skills', 'detail-skills');
	setDim('mission_alignment', 'bar-mission', 'pct-mission', 'detail-mission');
	setDim('culture_fit', 'bar-culture', 'pct-culture', 'detail-culture');

	// Stats
	el('detail-must-haves').textContent = data.must_have_coverage || '--';
	el('detail-strongest-match').textContent = data.strongest_match || '--';
	el('detail-biggest-gap').textContent = data.biggest_gap || 'None';

	// Skill matches
	const matches = data.skill_matches || [];
	const matchList = el('skill-match-list');
	matchList.innerHTML = '';
	if (matches.length > 0) {
		el('tag-skills').textContent = matches.length;
		matches.forEach(m => {
			const status = m.match_status || '';
			const iconClass = status.includes('strong') || status === 'exceeds' ? 'hit'
				: status === 'no_evidence' ? 'miss' : 'partial';
			const iconChar = iconClass === 'hit' ? '+' : iconClass === 'miss' ? 'x' : '~';
			const div = document.createElement('div');
			div.className = 'match-item';
			div.innerHTML = `
				<span class="match-icon ${iconClass}">${iconChar}</span>
				<span class="match-name">${m.requirement || ''}</span>
				<span class="match-source">${m.evidence_source || ''}</span>
			`;
			matchList.appendChild(div);
		});
		el('section-skills').classList.remove('hidden');
	}

	// Discoveries
	const gaps = data.resume_gaps_discovered || [];
	const discSection = el('section-discoveries');
	const discList = el('discoveries-list');
	discList.innerHTML = '';
	if (gaps.length > 0) {
		gaps.forEach(g => {
			const chip = document.createElement('span');
			chip.className = 'chip green';
			chip.textContent = g;
			discList.appendChild(chip);
		});
		discSection.classList.remove('hidden');
	} else {
		discSection.classList.add('hidden');
	}

	// Unverified
	const unver = data.resume_unverified || [];
	const unverSection = el('section-unverified');
	const unverList = el('unverified-list');
	unverList.innerHTML = '';
	if (unver.length > 0) {
		unver.forEach(u => {
			const chip = document.createElement('span');
			chip.className = 'chip amber';
			chip.textContent = u;
			unverList.appendChild(chip);
		});
		unverSection.classList.remove('hidden');
	} else {
		unverSection.classList.add('hidden');
	}

	// Action items
	const actions = data.action_items || [];
	const actSection = el('section-actions');
	const actList = el('action-list');
	actList.innerHTML = '';
	if (actions.length > 0) {
		el('tag-actions').textContent = actions.length;
		actions.forEach(a => {
			const li = document.createElement('li');
			li.textContent = a;
			actList.appendChild(li);
		});
		actSection.classList.remove('hidden');
	} else {
		actSection.classList.add('hidden');
	}

	// Full Details button — default: open raw assessment JSON endpoint
	const btnFullDefault = el('btn-full-details');
	if (btnFullDefault) {
		const id = data.assessment_id;
		btnFullDefault.onclick = () => {
			chrome.tabs.create({ url: id ? `http://localhost:7429/api/assessments/${id}` : 'http://localhost:7429/api/health' });
		};
	}

	// Verdict
	const verdict = data.should_apply || '';
	const labels = {
		strong_yes: 'Strong Yes -- definitely apply',
		yes: 'Yes -- good fit, apply',
		maybe: 'Maybe -- worth exploring, but gaps exist',
		probably_not: 'Probably not -- significant gaps',
		no: 'Pass -- poor fit',
	};
	el('verdict-text').textContent = labels[verdict] || verdict || '';
	const vb = el('verdict-banner');
	vb.className = 'verdict';
	if (verdict) vb.classList.add('v-' + verdict);

	showState('results');
}

async function initialize() {
	showState('loading');

	const health = await sendToBackground({ action: 'checkBackend' });
	if (!health.connected) { showState('no-backend'); return; }
	if (health.profile_loaded === false) { showState('no-profile'); return; }

	// Check for cached assessment result (instant reopen)
	const cache = await new Promise(r => {
		chrome.storage.local.get(['currentPosting', 'lastAssessment'], res => r(res));
	});
	const stored = cache.currentPosting || null;
	const lastAssessment = cache.lastAssessment || null;
	const fresh = stored && stored.extractedAt && (Date.now() - stored.extractedAt) < POSTING_TTL_MS;

	// Fast path: cached assessment for the same URL — render instantly
	if (fresh && lastAssessment && lastAssessment.url === stored.url) {
		currentPosting = stored;
		renderResults(lastAssessment.data);

		// Check if full report completed while popup was closed
		const fullReady = await new Promise(r => {
			chrome.storage.local.get('fullReportReady', res => r(res.fullReportReady || null));
		});
		if (fullReady && fullReady.assessmentId) {
			const btnFull = el('btn-full-details');
			if (btnFull) {
				btnFull.onclick = () => sendToBackground({ action: 'openReport', url: fullReady.url });
			}
		}
		return;
	}

	// Resolve posting (from cache or fresh extraction)
	let posting = null;
	if (fresh && stored.description) {
		posting = stored;
	}

	if (!posting) {
		const ext = await injectAndSend({ action: 'extractJobPosting' });
		if (ext.success && ext.pageData) {
			const extraction = await sendToBackground({
				action: 'extractPosting',
				payload: ext.pageData,
			});
			if (extraction.success && extraction.description) {
				posting = { ...extraction, extractedAt: Date.now() };
				chrome.storage.local.set({ currentPosting: posting });
			}
		}

		if (!posting) {
			const fallback = await injectAndSend({ action: 'extractFallback' });
			if (fallback.success && fallback.posting && fallback.posting.description) {
				posting = { ...fallback.posting, extractedAt: Date.now() };
			}
		}
	}

	if (!posting || !posting.description) { showState('no-job'); return; }
	currentPosting = posting;

	const ac = el('assessing-company');
	if (ac) ac.textContent = posting.company
		? `${posting.title || 'Role'} at ${posting.company}`
		: posting.title || '';
	showState('assessing');

	const partial = await sendToBackground({ action: 'assessPartial', payload: posting });
	if (!partial.success && partial.error) {
		el('error-message').textContent = partial.error;
		showState('error');
		return;
	}

	// Cache assessment result for instant reopen
	chrome.storage.local.set({ lastAssessment: { url: posting.url, data: partial } });

	renderResults(partial);
	const banner = el('banner-full-loading');
	if (banner) banner.classList.remove('hidden');

	// Fire-and-forget: background.js runs the full assessment independently.
	// If the popup closes, the background continues and stores the result.
	const assessmentId = partial.assessment_id;
	sendToBackground({ action: 'startFullAssess', assessmentId });

	// Poll for completion (if popup stays open)
	const pollInterval = setInterval(async () => {
		const ready = await new Promise(r => {
			chrome.storage.local.get('fullReportReady', res => r(res.fullReportReady || null));
		});
		if (ready && ready.assessmentId) {
			clearInterval(pollInterval);
			if (banner) banner.classList.add('hidden');
			const btnFull = el('btn-full-details');
			if (btnFull) {
				btnFull.onclick = () => sendToBackground({ action: 'openReport', url: ready.url });
			}
		}
	}, 2000);
}

document.addEventListener('DOMContentLoaded', () => {
	document.querySelectorAll('#btn-retry, #btn-retry-backend, #btn-retry-profile').forEach(b => {
		b.addEventListener('click', initialize);
	});

	const btnManual = el('btn-manual-extract');
	if (btnManual) btnManual.addEventListener('click', initialize);

	const btnWatch = el('btn-watchlist');
	if (btnWatch) btnWatch.addEventListener('click', async () => {
		if (!currentAssessment && !currentPosting) return;
		btnWatch.disabled = true;
		const r = await sendToBackground({
			action: 'addToWatchlist',
			payload: { ...(currentPosting || {}), assessment_id: currentAssessment?.assessment_id },
		});
		btnWatch.textContent = r.success ? 'Saved' : 'Failed';
		if (!r.success) { btnWatch.disabled = false; setTimeout(() => { btnWatch.textContent = 'Save to Watchlist'; }, 2000); }
	});

	// btn-full-details default click is set by renderResults (or overridden by
	// the assessFull callback once Claude deliverables are ready).

	initialize();
});
