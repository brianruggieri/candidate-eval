/**
 * popup.js — Popup controller for claude-candidate extension.
 *
 * State machine:
 *   loading → no-backend | no-profile | no-job | assessing → results | error
 *
 * All DOM interactions go through the show/hide helpers to keep the UI in sync.
 */

'use strict';

// ── State names ──────────────────────────────────────────────────────────────

const STATES = ['loading', 'no-backend', 'no-profile', 'no-job', 'assessing', 'results', 'error'];

// How long a cached posting stays fresh (5 minutes)
const POSTING_TTL_MS = 5 * 60 * 1000;

// ── DOM helpers ──────────────────────────────────────────────────────────────

function el(id) {
	return document.getElementById(id);
}

function showState(name) {
	STATES.forEach((s) => {
		const node = el(`state-${s}`);
		if (node) {
			node.classList.toggle('hidden', s !== name);
		}
	});
}

// ── Messaging helpers ────────────────────────────────────────────────────────

function sendToBackground(message) {
	return new Promise((resolve) => {
		chrome.runtime.sendMessage(message, (response) => {
			resolve(response || {});
		});
	});
}

function sendToActiveTab(message) {
	return new Promise((resolve) => {
		chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
			if (!tabs || tabs.length === 0) {
				resolve({ success: false, error: 'No active tab' });
				return;
			}
			chrome.tabs.sendMessage(tabs[0].id, message, (response) => {
				if (chrome.runtime.lastError) {
					resolve({ success: false, error: chrome.runtime.lastError.message });
				} else {
					resolve(response || {});
				}
			});
		});
	});
}

// ── Score → letter grade ─────────────────────────────────────────────────────

function scoreToGrade(score) {
	// score is 0.0–1.0
	if (score >= 0.93) return 'A+';
	if (score >= 0.90) return 'A';
	if (score >= 0.87) return 'A-';
	if (score >= 0.83) return 'B+';
	if (score >= 0.80) return 'B';
	if (score >= 0.77) return 'B-';
	if (score >= 0.73) return 'C+';
	if (score >= 0.70) return 'C';
	if (score >= 0.67) return 'C-';
	if (score >= 0.63) return 'D+';
	if (score >= 0.60) return 'D';
	return 'F';
}

// ── Render results ────────────────────────────────────────────────────────────

let currentAssessment = null;
let currentPosting = null;

function renderResults(data) {
	currentAssessment = data;

	const fit = data.fit || data; // support both wrapped and flat responses

	// Header
	el('results-company').textContent = fit.company || currentPosting?.company || '';
	el('results-title').textContent = fit.title || currentPosting?.title || 'Unknown Role';

	const overallScore = typeof fit.overall_score === 'number' ? fit.overall_score : null;
	const overallGrade = fit.grade || (overallScore !== null ? scoreToGrade(overallScore) : '—');
	const gradeEl = el('results-grade');
	gradeEl.textContent = overallGrade;
	gradeEl.dataset.grade = overallGrade;

	// Score bars
	function setBar(barId, gradeId, scoreKey) {
		const score = typeof fit[scoreKey] === 'number' ? fit[scoreKey] : null;
		const barEl = el(barId);
		const gradeEl = el(gradeId);

		if (score !== null) {
			// Defer width assignment so CSS transition fires
			requestAnimationFrame(() => {
				barEl.style.width = `${Math.round(score * 100)}%`;
			});
			gradeEl.textContent = scoreToGrade(score);
		} else {
			barEl.style.width = '0%';
			gradeEl.textContent = '—';
		}
	}

	setBar('bar-skills', 'grade-skills', 'skills_score');
	setBar('bar-mission', 'grade-mission', 'mission_score');
	setBar('bar-culture', 'grade-culture', 'culture_score');

	// Detail rows
	function setDetail(rowId, valueId, value) {
		const row = el(rowId);
		const valEl = el(valueId);
		if (value) {
			valEl.textContent = value;
			row.classList.remove('hidden');
		} else {
			row.classList.add('hidden');
		}
	}

	setDetail('row-must-haves', 'detail-must-haves',
		Array.isArray(fit.must_haves) ? fit.must_haves.join(', ') : fit.must_haves || null);
	setDetail('row-strongest-match', 'detail-strongest-match',
		fit.strongest_match || null);
	setDetail('row-biggest-gap', 'detail-biggest-gap',
		fit.biggest_gap || null);

	// Discoveries
	const gaps = fit.resume_gaps_discovered;
	const discoveriesSection = el('section-discoveries');
	const discoveriesList = el('discoveries-list');

	if (Array.isArray(gaps) && gaps.length > 0) {
		discoveriesList.innerHTML = '';
		gaps.forEach((gap) => {
			const li = document.createElement('li');
			li.textContent = gap;
			discoveriesList.appendChild(li);
		});
		discoveriesSection.classList.remove('hidden');
	} else {
		discoveriesSection.classList.add('hidden');
	}

	// Verdict banner
	const verdict = fit.should_apply || fit.verdict || '';
	const verdictBanner = el('verdict-banner');
	const verdictText = el('verdict-text');

	const verdictLabels = {
		yes: 'Apply — this looks like a strong fit',
		strong_yes: 'Strong yes — definitely apply',
		maybe: 'Maybe — worth exploring, but gaps exist',
		probably_not: 'Probably not — significant gaps',
		no: 'Pass — poor fit',
	};

	verdictText.textContent = verdictLabels[verdict] || verdict || 'Verdict unavailable';

	// Remove all verdict classes then apply the right one
	verdictBanner.className = 'verdict-banner';
	if (verdict) {
		verdictBanner.classList.add(`verdict-${verdict}`);
	}

	showState('results');
}

// ── Main initialization flow ─────────────────────────────────────────────────

async function initialize() {
	showState('loading');

	// 1. Check backend connectivity
	const healthResponse = await sendToBackground({ action: 'checkBackend' });

	if (!healthResponse.connected) {
		showState('no-backend');
		return;
	}

	// 2. Check for loaded profile
	if (healthResponse.profile_loaded === false) {
		showState('no-profile');
		return;
	}

	// 3. Get job posting — try cache first
	let posting = null;
	const stored = await new Promise((resolve) => {
		chrome.storage.local.get('currentPosting', (result) => {
			resolve(result.currentPosting || null);
		});
	});

	const isRecent = stored && stored.extractedAt &&
		(Date.now() - stored.extractedAt) < POSTING_TTL_MS;

	if (isRecent && stored.description) {
		posting = stored;
	} else {
		// Ask content script to extract
		const extractResult = await sendToActiveTab({ action: 'extractJobPosting' });
		if (extractResult.success && extractResult.posting) {
			posting = extractResult.posting;
		}
	}

	if (!posting || !posting.description) {
		showState('no-job');
		return;
	}

	currentPosting = posting;

	// 4. Show assessing state
	const assComp = el('assessing-company');
	if (assComp) {
		assComp.textContent = posting.company
			? `${posting.title || 'Role'} at ${posting.company}`
			: posting.title || '';
	}
	showState('assessing');

	// 5. Request assessment
	const assessResponse = await sendToBackground({
		action: 'assess',
		payload: {
			title: posting.title,
			company: posting.company,
			description: posting.description,
			url: posting.url,
			source: posting.source,
		},
	});

	if (!assessResponse.success && assessResponse.error) {
		el('error-message').textContent = assessResponse.error;
		showState('error');
		return;
	}

	renderResults(assessResponse);
}

// ── Event listeners ───────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {

	// Retry buttons (multiple states share this id via class targeting)
	document.querySelectorAll('#btn-retry').forEach((btn) => {
		btn.addEventListener('click', initialize);
	});

	// Manual re-extract from active tab
	const btnManual = el('btn-manual-extract');
	if (btnManual) {
		btnManual.addEventListener('click', initialize);
	}

	// Save to watchlist
	const btnWatchlist = el('btn-watchlist');
	if (btnWatchlist) {
		btnWatchlist.addEventListener('click', async () => {
			if (!currentAssessment && !currentPosting) return;
			btnWatchlist.disabled = true;

			const payload = {
				...(currentPosting || {}),
				assessment: currentAssessment || null,
			};

			const response = await sendToBackground({
				action: 'addToWatchlist',
				payload,
			});

			if (response.success) {
				btnWatchlist.textContent = 'Saved ✓';
			} else {
				btnWatchlist.disabled = false;
				btnWatchlist.textContent = 'Failed — retry';
				setTimeout(() => {
					btnWatchlist.textContent = 'Save to Watchlist';
				}, 2500);
			}
		});
	}

	// Full details — open assessment in new tab if we have an id
	const btnFull = el('btn-full-details');
	if (btnFull) {
		btnFull.addEventListener('click', () => {
			const id = currentAssessment?.id || currentAssessment?.assessment_id;
			const url = id
				? `http://localhost:7429/assessments/${id}`
				: 'http://localhost:7429';
			chrome.tabs.create({ url });
		});
	}

	// Kick off the initialization flow
	initialize();
});
