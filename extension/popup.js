'use strict';

const STATES = ['loading', 'no-backend', 'no-profile', 'no-job', 'assessing', 'results', 'error'];
const POSTING_TTL_MS = 5 * 60 * 1000;

function el(id) { return document.getElementById(id); }

/** Apply HSL background gradient to a stat card based on a 0–1 score. */
function _colorStat(rowId, score) {
	const row = el(rowId);
	if (!row) return;
	// Clamp to 0–1
	const s = Math.max(0, Math.min(1, score));
	// Hue: 0 (red) → 45 (amber) → 145 (green)
	const hue = Math.round(s * 145);
	const sat = 70 + Math.round((1 - Math.abs(s - 0.5) * 2) * 15); // slightly richer mid-range
	const light = 95 - Math.round(s * 8); // 95% (pale red) → 87% (richer green)
	row.style.background = `hsl(${hue}, ${sat}%, ${light}%)`;
	// Subtle left border accent
	row.style.borderLeft = `3px solid hsl(${hue}, ${sat}%, ${Math.max(light - 30, 35)}%)`;
}

/** Truncate long requirement text for stat cards. */
function _truncStat(text, max = 40) {
	if (!text || text.length <= max) return text;
	// Try to cut at a word boundary
	const cut = text.lastIndexOf(' ', max);
	return text.slice(0, cut > 20 ? cut : max) + '…';
}

/** Parse "10/12 must-haves met" → 0.83 ratio. */
function _parseMustHaveRatio(text) {
	if (!text) return 0;
	const m = text.match(/(\d+)\s*\/\s*(\d+)/);
	if (m) return parseInt(m[1]) / parseInt(m[2]);
	return 0;
}

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
	// Direct = human-attested evidence (resume or resume+repo)
	if (['corroborated', 'resume_and_repo', 'resume_only'].includes(m.evidence_source)) return 'direct';
	// Inferred = detected from code (repo_only) or other automated sources
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

	// Local dimensions (skills always shown; education is now an eligibility gate)
	setDim('skill_match', 'bar-skills', 'pct-skills', 'detail-skills');

	// Hide legacy education row if present
	const eduRow = el('dim-education');
	if (eduRow) {
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
			const dimCulture = el('dim-culture');
			if (dimCulture) dimCulture.classList.remove('hidden');
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

	// Stats with color coding
	el('detail-must-haves').textContent = data.must_have_coverage || '--';
	el('detail-strongest-match').textContent = _truncStat(data.strongest_match) || '--';
	el('detail-biggest-gap').textContent = _truncStat(data.biggest_gap) || 'None';
	el('detail-direct-evid').textContent = '--';
	_colorStat('row-must-haves', _parseMustHaveRatio(data.must_have_coverage));
	if (data.strongest_match) {
		_colorStat('row-strongest', 1.0);
	}
	if (data.biggest_gap && data.biggest_gap !== 'None') {
		_colorStat('row-gap', 0.0);
	}

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
	// Reset confidence layer so stale state from a previous assessment doesn't persist
	const _sbContainer = el('signal-bars');
	if (_sbContainer) _sbContainer.classList.add('hidden');
	const _summaryEl = el('section-evidence-summary');
	if (_summaryEl) _summaryEl.classList.add('hidden');
	if (matches.length > 0) {
		el('tag-skills').textContent = matches.length;
		// Group distilled requirements by parent_id for compound display
		const groups = new Map();
		matches.forEach((m, i) => {
			if (m.parent_id) {
				if (!groups.has(m.parent_id)) groups.set(m.parent_id, []);
				groups.get(m.parent_id).push(i);
			}
		});
		const renderedAsChild = new Set();
		groups.forEach(indices => indices.forEach(i => renderedAsChild.add(i)));

		matches.forEach((m, i) => {
			// Skip children — they render inside their compound group
			if (renderedAsChild.has(i)) return;

			const status = m.match_status || '';
			const iconClass = status.includes('strong') || status === 'exceeds' ? 'hit'
				: status === 'no_evidence' ? 'miss' : 'partial';
			const iconChar = iconClass === 'hit' ? '+' : iconClass === 'miss' ? 'x' : '~';
			const cat = categorizeSkill(m);
			const isMissing = cat === 'missing';
			const conf = m.confidence || 0;
			const confFill = conf >= 0.75 ? 'high' : conf >= 0.50 ? 'medium' : 'low';
			const confDisplay = isMissing ? '\u2014' : conf.toFixed(2);
			const confValStyle = isMissing ? ' style="color:#d1d5db"' : '';
			const sourceHtml = isMissing
				? `<span style="font-family:'SF Mono','Fira Code',monospace;font-size:9px;color:#d1d5db;flex-shrink:0">\u2014</span>`
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
			div.addEventListener('click', () => div.classList.toggle('expanded'));
			matchList.appendChild(div);

			// Expandable evidence detail panel
			const detail = document.createElement('div');
			detail.className = 'match-detail';
			let detailHtml = '';
			if (m.matched_skill) {
				detailHtml += `<div class="match-detail-row"><span class="match-detail-label">Skill</span><span class="match-detail-value">${escHtml(m.matched_skill)}</span></div>`;
			}
			const matchType = m.match_type || 'none';
			detailHtml += `<div class="match-detail-row"><span class="match-detail-label">Match</span><span class="match-detail-value"><span class="match-type-badge match-type-${escHtml(matchType)}">${escHtml(matchType)}</span></span></div>`;
			if (m.evidence_source) {
				const sourceLabel = String(m.evidence_source).replace(/_/g, ' ');
				detailHtml += `<div class="match-detail-row"><span class="match-detail-label">Source</span><span class="match-detail-value">${escHtml(sourceLabel)}</span></div>`;
			}
			if (m.priority) {
				const priorityKey = String(m.priority);
				const priorityLabel = priorityKey.replace(/_/g, ' ');
				detailHtml += `<div class="match-detail-row"><span class="match-detail-label">Priority</span><span class="match-detail-value"><span class="priority-badge priority-${escHtml(priorityKey)}">${escHtml(priorityLabel)}</span></span></div>`;
			}
			if (m.candidate_evidence && m.candidate_evidence !== 'no_evidence' && m.candidate_evidence !== 'missing') {
				detailHtml += `<div class="match-detail-row"><span class="match-detail-label">Evidence</span><span class="match-detail-value">${escHtml(m.candidate_evidence)}</span></div>`;
			}
			detail.innerHTML = detailHtml;
			matchList.appendChild(detail);
		});

		// Render compound groups as collapsible sections
		groups.forEach((indices, parentId) => {
			const children = indices.map(i => matches[i]);
			const sourceText = children[0]?.source_text || children.map(c => c.requirement).join(' + ');
			const wrapper = document.createElement('details');
			wrapper.className = 'compound-group';
			const allHit = children.every(c => {
				const s = c.match_status || '';
				return s.includes('strong') || s === 'exceeds';
			});
			const anyMiss = children.some(c => c.match_status === 'no_evidence');
			const groupIcon = allHit ? '+' : anyMiss ? 'x' : '~';
			const groupClass = allHit ? 'hit' : anyMiss ? 'miss' : 'partial';
			wrapper.innerHTML = `<summary class="match-item compound-header">
				<span class="match-icon ${groupClass}">${groupIcon}</span>
				<span class="match-name">Compound: ${escHtml(sourceText)}</span>
				<span class="compound-count">${children.length} skills</span>
			</summary>`;
			children.forEach(child => {
				const cs = child.match_status || '';
				const cIcon = cs.includes('strong') || cs === 'exceeds' ? '+' : cs === 'no_evidence' ? 'x' : '~';
				const cClass = cs.includes('strong') || cs === 'exceeds' ? 'hit' : cs === 'no_evidence' ? 'miss' : 'partial';
				const cCat = categorizeSkill(child);
				const cMissing = cCat === 'missing';
				const cConf = child.confidence || 0;
				const cFill = cConf >= 0.75 ? 'high' : cConf >= 0.50 ? 'medium' : 'low';
				const childDiv = document.createElement('div');
				childDiv.className = 'match-item compound-child';
				childDiv.innerHTML = `
					<span class="match-icon ${cClass}">${cIcon}</span>
					<span class="match-name">${escHtml(child.requirement || '')}</span>
					<div class="conf-bar-wrap">
						<div class="conf-bar">
							<div class="conf-bar-fill ${cMissing ? '' : cFill}" style="width:${cMissing ? 0 : Math.round(cConf * 100)}%"></div>
						</div>
						<span class="conf-val">${cMissing ? '\u2014' : cConf.toFixed(2)}</span>
					</div>
					${cMissing ? '<span style="font-family:monospace;font-size:9px;color:#d1d5db">\u2014</span>' : `<span class="source-chip ${cCat}">${cCat}</span>`}
				`;
				wrapper.appendChild(childDiv);
			});
			matchList.appendChild(wrapper);
		});
		el('section-skills').classList.remove('hidden');

		// Compute and render confidence layer from full matches array
		const withEvidence = matches.filter(m => m.match_status !== 'no_evidence');
		const directCount = withEvidence.filter(m => categorizeSkill(m) === 'direct').length;
		const directPct = withEvidence.length
			? Math.round(directCount / withEvidence.length * 100) + '%'
			: '--';
		el('detail-direct-evid').textContent = directPct;
		_colorStat('row-direct-evid', withEvidence.length ? directCount / withEvidence.length : 0);

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

	// Unverified — hidden in v0.7 (sessions parked, section is misleading)
	const unverSection = el('section-unverified');
	if (unverSection) unverSection.classList.add('hidden');

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
	// Storage is per-URL — no cross-tab contamination.
	const [stored, lastAssessment, fullReady] = await Promise.all([
		getForUrl('posting', currentTabUrl),
		getForUrl('assessment', currentTabUrl),
		getForUrl('fullReady', currentTabUrl),
	]);
	const fresh = stored && stored.extractedAt && (Date.now() - stored.extractedAt) < POSTING_TTL_MS;

	if (fresh && lastAssessment && lastAssessment.data) {
		currentPosting = stored;

		// Stale profile detection
		const storedHashes = await getForUrl('profileHashes', currentTabUrl);
		try {
			const profileStatus = await sendToBackground({ action: 'getProfileStatus' });
			if (profileStatus && profileStatus.hashes && isProfileStale(storedHashes, profileStatus.hashes)) {
				const banner = el('stale-banner');
				if (banner) banner.classList.remove('hidden');
			}
		} catch (e) { /* non-critical */ }

		const cachedAid = lastAssessment.data.assessment_id;
		if (fullReady && fullReady.assessmentId === cachedAid && fullReady.data) {
			// Full assessment is ready — render it directly
			renderResults(fullReady.data);
		} else {
			// Show partial results, then poll for full
			renderResults(lastAssessment.data);

			if (cachedAid) sendToBackground({ action: 'startFullAssess', assessmentId: cachedAid, postingUrl: currentTabUrl });
			const pollInterval = setInterval(async () => {
				const ready = await getForUrl('fullReady', currentTabUrl);
				if (ready && ready.assessmentId === cachedAid && ready.data) {
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

	// Resolve posting (from per-URL cache or fresh extraction)
	let posting = null;
	if (fresh && stored && stored.description && stored.requirements && stored.requirements.length) {
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
				setForUrl('posting', currentTabUrl, posting);
			}
		}
	}

	// Gate: require extracted posting with requirements before proceeding
	if (!posting || !posting.description) { showState('no-job'); return; }
	if (!posting.requirements || !posting.requirements.length) {
		el('error-message').textContent =
			'Couldn\u2019t extract job requirements. Try refreshing the page and reopening the extension.';
		showState('error');
		return;
	}
	currentPosting = posting;

	const ac = el('assessing-company');
	if (ac) ac.textContent = posting.company
		? `${posting.title || 'Role'} at ${posting.company}`
		: posting.title || '';
	showState('assessing');

	removeForUrl('fullReady', currentTabUrl);
	const partial = await sendToBackground({ action: 'assessPartial', payload: posting });
	if (!partial.success && partial.error) {
		el('error-message').textContent = partial.error;
		showState('error');
		return;
	}

	// Cache assessment result for instant reopen
	setForUrl('assessment', currentTabUrl, { url: posting.url, data: partial });

	// Store profile hashes for stale detection
	try {
		const profileStatus = await sendToBackground({ action: 'getProfileStatus' });
		if (profileStatus && profileStatus.hashes) {
			setForUrl('profileHashes', currentTabUrl, profileStatus.hashes);
		}
	} catch (e) { /* non-critical */ }

	renderResults(partial);

	// Show deep analysis indicator
	const deepBanner = el('banner-deep-analysis');
	if (deepBanner) deepBanner.classList.remove('hidden');

	// Fire-and-forget: background.js runs the full assessment independently.
	const assessmentId = partial.assessment_id;
	sendToBackground({ action: 'startFullAssess', assessmentId, postingUrl: currentPosting?.url || '' });

	// Poll for completion (if popup stays open) — update in-place
	const currentAssessmentId = assessmentId;
	const pollInterval = setInterval(async () => {
		const ready = await getForUrl('fullReady', currentTabUrl);
		if (ready && ready.assessmentId === currentAssessmentId && ready.data) {
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

	const btnDismissStale = el('btn-dismiss-stale');
	if (btnDismissStale) btnDismissStale.addEventListener('click', () => {
		el('stale-banner').classList.add('hidden');
	});

	const btnReassess = el('btn-reassess');
	if (btnReassess) btnReassess.addEventListener('click', async () => {
		const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
		const url = activeTab?.url || '';
		await removeForUrl('assessment', url);
		await removeForUrl('fullReady', url);
		await removeForUrl('posting', url);
		el('stale-banner').classList.add('hidden');
		initialize();
	});

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

	const btnScreenshot = el('btn-screenshot');
	if (btnScreenshot) btnScreenshot.addEventListener('click', async () => {
		btnScreenshot.textContent = '...';
		btnScreenshot.disabled = true;

		const body = document.body;
		const footer = document.querySelector('.verdict-footer');

		// Save original styles to restore after capture
		const origMaxHeight = body.style.maxHeight;
		const origOverflow = body.style.overflow;
		const origHeight = body.style.height;
		const origFooterPosition = footer ? footer.style.position : '';

		try {
			// Expand body to full content height and un-sticky the footer
			body.style.maxHeight = 'none';
			body.style.overflow = 'visible';
			body.style.height = 'auto';
			body.style.paddingBottom = '16px';
			if (footer) footer.style.position = 'relative';

			// Hide the button row during capture
			const btnRow = document.querySelector('.btn-row');
			if (btnRow) btnRow.style.display = 'none';

			// Fix html2canvas gradient rendering: replace 'transparent' with '#ffffff'
			const lowConfItems = document.querySelectorAll('.match-item.low-conf');
			lowConfItems.forEach(item => {
				item.dataset.origBg = item.style.background || '';
				const computed = getComputedStyle(item).backgroundImage;
				if (computed.includes('transparent')) {
					item.style.background = computed.replace(/transparent/g, '#ffffff');
				}
			});

			// Force a layout pass so scrollHeight is accurate
			void body.scrollHeight;

			const canvas = await html2canvas(body, {
				scale: 2,
				useCORS: true,
				backgroundColor: '#ffffff',
				width: body.scrollWidth,
				height: body.scrollHeight,
			});

			// Restore button row and low-conf backgrounds
			if (btnRow) btnRow.style.display = '';
			lowConfItems.forEach(item => {
				item.style.background = item.dataset.origBg;
				delete item.dataset.origBg;
			});

			const blob = await new Promise(r => canvas.toBlob(r, 'image/png'));
			await navigator.clipboard.write([
				new ClipboardItem({ 'image/png': blob }),
			]);

			btnScreenshot.textContent = '\u2705';
			setTimeout(() => { btnScreenshot.textContent = '\u{1F4F7}'; }, 1500);
		} catch (err) {
			console.error('Screenshot failed:', err);
			btnScreenshot.textContent = '\u274C';
			setTimeout(() => { btnScreenshot.textContent = '\u{1F4F7}'; }, 2000);
		} finally {
			// Restore original styles
			body.style.maxHeight = origMaxHeight;
			body.style.overflow = origOverflow;
			body.style.height = origHeight;
			body.style.paddingBottom = '';
			if (footer) footer.style.position = origFooterPosition;
			btnScreenshot.disabled = false;
		}
	});

	initialize();
});
