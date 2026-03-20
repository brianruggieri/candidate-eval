/**
 * dashboard.js — Batch assessment results dashboard
 */

let currentResults = [];
let sortCol = 'percentage';
let sortDir = -1; // -1 = descending

function gradeClass(grade) {
	if (!grade) return 'grade-F';
	const letter = grade.charAt(0);
	if (letter === 'A') return 'grade-A';
	if (letter === 'B') return 'grade-B';
	if (letter === 'C') return 'grade-C';
	return 'grade-D';
}

function pctClass(pct) {
	if (pct >= 70) return 'pct-high';
	if (pct >= 50) return 'pct-mid';
	return 'pct-low';
}

function renderTable(results) {
	const tbody = document.getElementById('results-body');
	tbody.innerHTML = '';

	results.forEach(r => {
		const tr = document.createElement('tr');
		if (r.error) {
			tr.className = 'error';
			const td = document.createElement('td');
			td.colSpan = 6;
			td.textContent = '\u26A0 ' + (r.url ? r.url.substring(0, 60) : 'Unknown') + ' \u2014 ' + r.error;
			tr.appendChild(td);
		} else {
			tr.className = 'clickable';
			tr.addEventListener('click', () => window.open(r.url, '_blank'));

			const cells = [
				{ html: true, content: `<span class="grade-badge ${gradeClass(r.grade)}">${r.grade || '?'}</span>` },
				{ cls: `pct-cell ${pctClass(r.percentage)}`, text: (r.percentage || 0).toFixed(1) + '%' },
				{ html: true, content: `<strong>${r.company || 'Unknown'}</strong>` },
				{ text: r.title || 'Unknown' },
				{ cls: 'strongest', text: r.strongest || '--' },
				{ cls: 'gap', text: r.biggest_gap || '--' },
			];

			cells.forEach(c => {
				const td = document.createElement('td');
				if (c.cls) td.className = c.cls;
				if (c.html) {
					td.innerHTML = c.content;
				} else {
					td.textContent = c.text;
				}
				tr.appendChild(td);
			});
		}
		tbody.appendChild(tr);
	});
}

function updateSummary(results) {
	const successful = results.filter(r => !r.error);
	document.getElementById('stat-total').textContent = successful.length;

	if (successful.length > 0) {
		const top = successful[0];
		document.getElementById('stat-top').textContent = top.company + ' (' + top.grade + ')';

		const avg = successful.reduce((s, r) => s + (r.percentage || 0), 0) / successful.length;
		document.getElementById('stat-avg').textContent = avg.toFixed(0) + '%';

		const ab = successful.filter(r => r.grade && (r.grade.startsWith('A') || r.grade.startsWith('B'))).length;
		document.getElementById('stat-ab').textContent = ab;
	}
}

function sortResults(col) {
	if (sortCol === col) {
		sortDir *= -1;
	} else {
		sortCol = col;
		sortDir = col === 'percentage' ? -1 : 1;
	}

	const successful = currentResults.filter(r => !r.error);
	const errors = currentResults.filter(r => r.error);

	successful.sort((a, b) => {
		const va = a[col] || '';
		const vb = b[col] || '';
		if (typeof va === 'number' && typeof vb === 'number') return (va - vb) * sortDir;
		return String(va).localeCompare(String(vb)) * sortDir;
	});

	currentResults = [...successful, ...errors];
	renderTable(currentResults);

	// Update sort arrows
	document.querySelectorAll('th[data-sort]').forEach(th => {
		const arrow = th.querySelector('.sort-arrow');
		if (th.dataset.sort === col) {
			arrow.textContent = sortDir > 0 ? '\u25B2' : '\u25BC';
		} else {
			arrow.textContent = '';
		}
	});
}

// Column header click to sort
document.querySelectorAll('th[data-sort]').forEach(th => {
	th.addEventListener('click', () => sortResults(th.dataset.sort));
});

// Poll for live batch results from chrome.storage
function pollResults() {
	chrome.storage.local.get(['batchProgress', 'batchResults'], (data) => {
		const progress = data.batchProgress;
		const results = data.batchResults;

		if (progress) {
			const pct = progress.total > 0 ? (progress.done / progress.total * 100) : 0;
			document.getElementById('progress-fill').style.width = pct + '%';
			document.getElementById('progress-text').textContent =
				progress.done >= progress.total
					? 'Completed \u2014 ' + progress.total + ' jobs assessed'
					: 'Assessing ' + (progress.done + 1) + '/' + progress.total + ': ' + (progress.current || '...');

			if (progress.done >= progress.total) {
				document.getElementById('progress-text').classList.remove('loading');
			}

			document.getElementById('subtitle').textContent =
				progress.done + '/' + progress.total + ' jobs processed';
		}

		if (results && results.length > 0) {
			currentResults = results;
			sortResults(sortCol);
			updateSummary(results);

			document.getElementById('results-table').classList.remove('hidden');
			document.getElementById('summary-row').classList.remove('hidden');
			document.getElementById('empty-state').classList.add('hidden');
		}

		// Keep polling until done
		if (!progress || progress.done < progress.total) {
			setTimeout(pollResults, 1000);
		}
	});
}

// Load existing assessments from server API as baseline
async function loadFromServer() {
	try {
		const resp = await fetch('http://localhost:7429/api/assessments?limit=200');
		if (!resp.ok) return;
		const assessments = await resp.json();
		if (!assessments || assessments.length === 0) return;

		// Deduplicate by posting_url (keep highest score)
		const byUrl = {};
		for (const a of assessments) {
			const d = a.data || a;
			const url = d.posting_url || d.assessment_id;
			const score = d.overall_score || 0;
			if (!byUrl[url] || score > (byUrl[url].overall_score || 0)) {
				byUrl[url] = d;
			}
		}

		const serverResults = Object.values(byUrl).map(d => ({
			url: d.posting_url || '',
			company: d.company_name || 'Unknown',
			title: d.job_title || 'Unknown',
			percentage: (d.partial_percentage != null) ? d.partial_percentage : ((d.overall_score || 0) * 100),
			grade: d.overall_grade || '?',
			strongest: d.strongest_match || '',
			biggest_gap: d.biggest_gap || '',
		}));

		if (serverResults.length > 0 && currentResults.length === 0) {
			currentResults = serverResults;
			sortResults(sortCol);
			updateSummary(serverResults);
			document.getElementById('results-table').classList.remove('hidden');
			document.getElementById('summary-row').classList.remove('hidden');
			document.getElementById('empty-state').classList.add('hidden');
			document.getElementById('progress-section').classList.add('hidden');
			document.getElementById('subtitle').textContent = serverResults.length + ' assessments loaded from history';
		}
	} catch (e) {
		console.log('Could not load from server:', e);
	}
}

// Load server data first, then poll for live batch updates
loadFromServer();
pollResults();
