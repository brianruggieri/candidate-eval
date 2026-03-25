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

function escHtml(s) {
	return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function barColor(score) {
	if (score >= 0.75) return 'green';
	if (score >= 0.50) return 'yellow';
	if (score >= 0.30) return 'blue';
	return 'red';
}

function categorizeSkill(m) {
	if (m.match_status === 'no_evidence') return 'missing';
	const req = (m.requirement || '').toLowerCase().replace(/[^a-z0-9]/g, '');
	const matched = (m.matched_skill || '').toLowerCase().replace(/[^a-z0-9]/g, '');
	if (matched && matched !== req) return 'fuzzy';
	if (m.evidence_source === 'corroborated') return 'direct';
	// resume_only, sessions_only, conflicting → inferred.
	// sessions_only is intentionally "inferred": agentic sessions without
	// resume corroboration are not guaranteed personal mastery.
	return 'inferred';
}

function renderSignalBars(matches) {
	const withEvidence = matches.filter(m => m.match_status !== 'no_evidence');
	if (!withEvidence.length) return;
	const directCount = withEvidence.filter(m => categorizeSkill(m) === 'direct').length;
	const ratio = directCount / withEvidence.length;
	const litCount = ratio >= 0.75 ? 4 : ratio >= 0.5 ? 3 : ratio >= 0.25 ? 2 : 1;
	for (let i = 1; i <= 4; i++) {
		const bar = el(`sb${i}`);
		if (bar) bar.classList.toggle('lit', i <= litCount);
	}
	const sbContainer = el('signal-bars');
	if (sbContainer) sbContainer.classList.remove('hidden');
}

function renderEvidenceSummary(matches) {
	const counts = { direct: 0, inferred: 0, fuzzy: 0, missing: 0 };
	matches.forEach(m => counts[categorizeSkill(m)]++);
	['direct', 'inferred', 'fuzzy', 'missing'].forEach(cat => {
		const chip = el(`chip-${cat}`);
		const countEl = el(`chip-${cat}-count`);
		if (!chip) return;
		if (counts[cat] > 0) {
			if (countEl) countEl.textContent = `${counts[cat]} ${cat}`;
			chip.classList.remove('hidden');
		} else {
			chip.classList.add('hidden');
		}
	});
	const summaryEl = el('section-evidence-summary');
	if (summaryEl && matches.length > 0) summaryEl.classList.remove('hidden');
}

function pct(score) { return Math.round(score * 100) + '%'; }

let currentAssessment = null;
let currentPosting = null;

function renderResults(data) {
	currentAssessment = data;

	const phase = data.assessment_phase || 'partial';

	// Header
	el('results-company').textContent = data.company_name || currentPosting?.company || '';
	el('results-title').textContent = data.job_title || currentPosting?.title || 'Unknown Role';

	// Hero display: target #hero-text child so signal-bars sibling is preserved
	const heroEl = el('results-hero');
	const heroText = el('hero-text');
	if (phase === 'full') {
		const grade = data.overall_grade || scoreToGrade(data.overall_score || 0);
		if (heroText) heroText.textContent = grade;
		heroEl.dataset.grade = grade;
		heroEl.classList.add('hero-grade');
		heroEl.classList.remove('hero-pct');
	} else {
		const partial = data.partial_percentage != null
			? Math.round(data.partial_percentage)
			: Math.round((data.overall_score || 0) * 100);
		if (heroText) heroText.textContent = partial + '%';
		heroEl.dataset.grade = '';
		heroEl.classList.add('hero-pct');
		heroEl.classList.remove('hero-grade');
	}

	// Overall bar
	const overall = data.overall_score || (data.partial_percentage != null ? data.partial_percentage / 100 : 0);
	requestAnimationFrame(() => {
		el('bar-overall').style.width = pct(overall);
	});
	el('pct-overall').textContent = pct(overall);

	// Summary
	el('results-summary').textContent = data.overall_summary || '';

	// Dimension renderer helper
	function setDim(key, barId, pctId, detailId) {
		const dim = data[key];
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

	// Local dimensions (skills always shown; experience/education hidden when insufficient)
	setDim('skill_match', 'bar-skills', 'pct-skills', 'detail-skills');

	const expDim = data.experience_match;
	const expRow = el('dim-experience');
	if (expDim && !expDim.insufficient_data) {
		setDim('experience_match', 'bar-experience', 'pct-experience', 'detail-experience');
		if (expRow) expRow.classList.remove('hidden');
	} else if (expRow) {
		expRow.classList.add('hidden');
	}

	const eduDim = data.education_match;
	const eduRow = el('dim-education');
	if (eduDim && !eduDim.insufficient_data) {
		setDim('education_match', 'bar-education', 'pct-education', 'detail-education');
		if (eduRow) eduRow.classList.remove('hidden');
	} else if (eduRow) {
		eduRow.classList.add('hidden');
	}

	// Full assessment dimensions (only shown when phase === 'full')
	const fullDimsSection = el('section-full-dims');
	const narrativeSection = el('section-narrative');
	const receptivitySection = el('section-receptivity');

	if (phase === 'full') {
		// Mission & culture
		if (data.mission_alignment) {
			setDim('mission_alignment', 'bar-mission', 'pct-mission', 'detail-mission');
		}
		if (data.culture_fit) {
			setDim('culture_fit', 'bar-culture', 'pct-culture', 'detail-culture');
		}
		if (data.mission_alignment || data.culture_fit) {
			fullDimsSection.classList.remove('hidden');
		}

		// Narrative verdict
		if (data.narrative_verdict) {
			el('narrative-verdict').textContent = data.narrative_verdict;
			narrativeSection.classList.remove('hidden');
		}

		// Receptivity badge
		if (data.receptivity_level) {
			const badge = el('receptivity-badge');
			badge.textContent = data.receptivity_level;
			badge.className = 'receptivity-badge receptivity-' + data.receptivity_level;
			if (data.receptivity_reason) {
				el('receptivity-reason').textContent = data.receptivity_reason;
			}
			receptivitySection.classList.remove('hidden');
		}
	} else {
		fullDimsSection.classList.add('hidden');
		narrativeSection.classList.add('hidden');
		receptivitySection.classList.add('hidden');
	}

	// Stats
	el('detail-must-haves').textContent = data.must_have_coverage || '--';
	el('detail-strongest-match').textContent = data.strongest_match || '--';
	el('detail-biggest-gap').textContent = data.biggest_gap || 'None';
	el('detail-direct-evid').textContent = '--';

	// Eligibility gates
	const gates = data.eligibility_gates || [];
	const eligSection = el('section-eligibility');
	const eligList = el('eligibility-list');
	if (eligList) eligList.innerHTML = '';
	if (gates.length > 0 && eligList) {
		gates.forEach(g => {
			const iconClass = g.status === 'met' ? 'hit' : g.status === 'unmet' ? 'miss' : 'partial';
			const iconChar = g.status === 'met' ? '+' : g.status === 'unmet' ? 'x' : '?';
			const div = document.createElement('div');
			div.className = 'match-item';
			div.innerHTML = `
				<span class="match-icon ${iconClass}">${iconChar}</span>
				<span class="match-name">${escHtml(g.description || '')}</span>
				<span class="match-source">${escHtml(g.status || 'unknown')}</span>
			`;
			eligList.appendChild(div);
		});
		if (eligSection) eligSection.classList.remove('hidden');
	} else if (eligSection) {
		eligSection.classList.add('hidden');
	}

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
			const cat = categorizeSkill(m);
			const isMissing = cat === 'missing';
			const conf = m.confidence || 0;
			const confFill = conf >= 0.75 ? 'high' : conf >= 0.50 ? 'medium' : 'low';
			const confDisplay = isMissing ? '—' : conf.toFixed(2);
			const confValStyle = isMissing ? ' style="color:#d1d5db"' : '';
			const sourceHtml = isMissing
				? `<span style="font-family:'SF Mono','Fira Code',monospace;font-size:9px;color:#d1d5db;flex-shrink:0">—</span>`
				: `<span class="source-chip ${cat}">${cat}</span>`;
			const div = document.createElement('div');
			div.className = 'match-item' + (!isMissing && conf <= 0.70 ? ' low-conf' : '');
			div.innerHTML = `
				<span class="match-icon ${iconClass}">${iconChar}</span>
				<span class="match-name">${escHtml(m.requirement || '')}</span>
				<div class="conf-bar-wrap">
					<div class="conf-bar">
						<div class="conf-bar-fill ${isMissing ? '' : confFill}" style="width:${isMissing ? 0 : Math.round(conf * 100)}%"></div>
					</div>
					<span class="conf-val"${confValStyle}>${confDisplay}</span>
				</div>
				${sourceHtml}
			`;
			matchList.appendChild(div);
		});
		el('section-skills').classList.remove('hidden');

		// Compute and render confidence layer from full matches array
		const withEvidence = matches.filter(m => m.match_status !== 'no_evidence');
		const directCount = withEvidence.filter(m => categorizeSkill(m) === 'direct').length;
		const directPct = withEvidence.length
			? Math.round(directCount / withEvidence.length * 100) + '%'
			: '--';
		el('detail-direct-evid').textContent = directPct;

		renderEvidenceSummary(matches);
		renderSignalBars(matches);
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

	// Get current tab URL to validate cache
	const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
	const currentTabUrl = activeTab?.url || '';

	// Check cache FIRST — before any server calls. Instant reopen.
	const cache = await new Promise(r => {
		chrome.storage.local.get(['currentPosting', 'lastAssessment', 'fullAssessmentReady'], res => r(res));
	});
	const stored = cache.currentPosting || null;
	const lastAssessment = cache.lastAssessment || null;
	const fullReady = cache.fullAssessmentReady || null;
	const fresh = stored && stored.extractedAt && (Date.now() - stored.extractedAt) < POSTING_TTL_MS;

	// Cache only valid if it matches the current tab's URL
	const normalizeUrl = (u) => (u || '').replace(/\?.*$/, '').replace(/\/+$/, '');
	const cacheMatchesTab = stored && normalizeUrl(stored.url) === normalizeUrl(currentTabUrl);

	if (fresh && cacheMatchesTab && lastAssessment && lastAssessment.url === stored.url) {
		currentPosting = stored;

		if (fullReady && fullReady.assessmentId && fullReady.data) {
			// Full assessment is ready — render it directly
			renderResults(fullReady.data);
		} else {
			// Show partial results, then poll for full
			renderResults(lastAssessment.data);

			const aid = lastAssessment.data.assessment_id;
			if (aid) sendToBackground({ action: 'startFullAssess', assessmentId: aid });
			const pollInterval = setInterval(async () => {
				const ready = await new Promise(r => {
					chrome.storage.local.get('fullAssessmentReady', res => r(res.fullAssessmentReady || null));
				});
				if (ready && ready.assessmentId && ready.data) {
					clearInterval(pollInterval);
					renderResults(ready.data);
				}
			}, 2000);
		}
		return;
	}

	// No cache — need the server
	const health = await sendToBackground({ action: 'checkBackend' });
	if (!health.connected) { showState('no-backend'); return; }
	if (health.profile_loaded === false) { showState('no-profile'); return; }

	// Resolve posting (from cache or fresh extraction)
	let posting = null;
	if (fresh && stored.description) {
		posting = stored;
	}

	if (!posting) {
		const lt = el('loading-text');
		if (lt) lt.textContent = 'Extracting job posting...';
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

	// Show deep analysis indicator
	const deepBanner = el('banner-deep-analysis');
	if (deepBanner) deepBanner.classList.remove('hidden');

	// Fire-and-forget: background.js runs the full assessment independently.
	const assessmentId = partial.assessment_id;
	sendToBackground({ action: 'startFullAssess', assessmentId });

	// Poll for completion (if popup stays open) — update in-place
	const pollInterval = setInterval(async () => {
		const ready = await new Promise(r => {
			chrome.storage.local.get('fullAssessmentReady', res => r(res.fullAssessmentReady || null));
		});
		if (ready && ready.assessmentId && ready.data) {
			clearInterval(pollInterval);
			if (deepBanner) deepBanner.classList.add('hidden');
			renderResults(ready.data);
		}
	}, 2000);
}

document.addEventListener('DOMContentLoaded', () => {
	document.querySelectorAll('#btn-retry, #btn-retry-backend, #btn-retry-profile').forEach(b => {
		b.addEventListener('click', initialize);
	});

	const btnManual = el('btn-manual-extract');
	if (btnManual) btnManual.addEventListener('click', initialize);

	const btnShortlist = el('btn-shortlist');
	if (btnShortlist) btnShortlist.addEventListener('click', async () => {
		if (!currentAssessment && !currentPosting) return;
		btnShortlist.disabled = true;
		const r = await sendToBackground({
			action: 'addToShortlist',
			payload: {
				...(currentPosting || {}),
				assessment_id: currentAssessment?.assessment_id,
				salary: currentPosting?.salary || null,
				location: currentPosting?.location || null,
				overall_grade: currentAssessment?.overall_grade || null,
			},
		});
		btnShortlist.textContent = r.success ? 'Added' : 'Failed';
		if (!r.success) {
			btnShortlist.disabled = false;
			setTimeout(() => { btnShortlist.textContent = 'Add to Shortlist'; }, 2000);
		}
	});

	const btnCopy = el('btn-clipboard');
	if (btnCopy) btnCopy.addEventListener('click', () => {
		const data = currentAssessment;
		const posting = currentPosting;
		const row = [
			data?.company_name || '',
			data?.job_title || '',
			posting?.location || '',
			posting?.salary || '',
			posting?.url || '',
			data?.overall_grade || '',
			new Date().toLocaleDateString(),
		].join('\t');
		navigator.clipboard.writeText(row);
		btnCopy.textContent = 'Copied!';
		setTimeout(() => { btnCopy.textContent = '\u{1F4CB}'; }, 1500);
	});

	initialize();
});
