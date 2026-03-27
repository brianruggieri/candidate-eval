/**
 * dashboard.js — Batch assessment results dashboard + shortlist view
 */

let currentResults = [];
let sortCol = 'percentage';
let sortDir = -1; // -1 = descending

let shortlistItems = [];
let slSortCol = 'added';
let slSortDir = -1; // -1 = descending (newest first)

const STATUS_OPTIONS = ['shortlisted', 'applied', 'interviewing', 'offer', 'rejected'];

const SERVER = 'http://localhost:7429';

function escapeHtml(str) {
	const div = document.createElement('div');
	div.textContent = str || '';
	return div.innerHTML;
}

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

// Column header click to sort (assessments tab)
document.querySelectorAll('th[data-sort]').forEach(th => {
	th.addEventListener('click', () => sortResults(th.dataset.sort));
});

// Column header click to sort (shortlist tab)
document.querySelectorAll('th[data-sl-sort]').forEach(th => {
	th.addEventListener('click', () => sortShortlist(th.dataset.slSort));
});

// --- Tab navigation ---
document.querySelectorAll('.tab-btn').forEach(btn => {
	btn.addEventListener('click', () => {
		document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
		btn.classList.add('active');

		document.querySelectorAll('.tab-panel').forEach(p => p.classList.add('hidden'));
		document.getElementById('tab-' + btn.dataset.tab).classList.remove('hidden');

		if (btn.dataset.tab === 'shortlist') {
			loadShortlist();
		}
	});
});

// --- Shortlist functions ---

function gradeValue(grade) {
	if (!grade) return 0;
	const map = { 'A+': 12, 'A': 11, 'A-': 10, 'B+': 9, 'B': 8, 'B-': 7, 'C+': 6, 'C': 5, 'C-': 4, 'D+': 3, 'D': 2, 'D-': 1, 'F': 0 };
	return map[grade] ?? 0;
}

function sortShortlist(col) {
	if (slSortCol === col) {
		slSortDir *= -1;
	} else {
		slSortCol = col;
		slSortDir = (col === 'added' || col === 'grade') ? -1 : 1;
	}

	shortlistItems.sort((a, b) => {
		let va, vb;
		if (col === 'grade') {
			va = gradeValue(a.assessment_grade || a.overall_grade);
			vb = gradeValue(b.assessment_grade || b.overall_grade);
		} else if (col === 'added') {
			va = a.added_at || '';
			vb = b.added_at || '';
		} else if (col === 'salary') {
			va = a.salary || '';
			vb = b.salary || '';
		} else {
			va = a[col] || '';
			vb = b[col] || '';
		}
		if (typeof va === 'number' && typeof vb === 'number') return (va - vb) * slSortDir;
		return String(va).localeCompare(String(vb)) * slSortDir;
	});

	renderShortlist(shortlistItems);

	// Update sort arrows
	document.querySelectorAll('th[data-sl-sort]').forEach(th => {
		const arrow = th.querySelector('.sort-arrow');
		if (th.dataset.slSort === col) {
			arrow.textContent = slSortDir > 0 ? '\u25B2' : '\u25BC';
		} else {
			arrow.textContent = '';
		}
	});
}

async function loadShortlist() {
	try {
		const resp = await fetch(SERVER + '/api/shortlist/enriched?limit=200');
		if (!resp.ok) {
			console.log('Shortlist fetch failed:', resp.status);
			return;
		}
		const items = await resp.json();
		shortlistItems = items || [];
		renderShortlist(shortlistItems);
	} catch (e) {
		console.log('Could not load shortlist:', e);
	}
}

function formatDate(isoStr) {
	if (!isoStr) return '--';
	try {
		const d = new Date(isoStr);
		return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
	} catch {
		return '--';
	}
}

function formatSalary(item) {
	// Backend returns salary as a single string (e.g. "$120k-$160k", "120000")
	const raw = item.salary;
	if (!raw || (typeof raw === 'string' && !raw.trim())) return '--';
	return raw;
}

function renderShortlist(items) {
	const tbody = document.getElementById('shortlist-body');
	const table = document.getElementById('shortlist-table');
	const empty = document.getElementById('shortlist-empty');

	// Update summary stats
	const total = items.length;
	const applied = items.filter(i => i.status === 'applied').length;
	const interviewing = items.filter(i => i.status === 'interviewing').length;

	document.getElementById('sl-stat-total').textContent = total;
	document.getElementById('sl-stat-applied').textContent = applied;
	document.getElementById('sl-stat-interviewing').textContent = interviewing;

	// Average grade
	const graded = items.filter(i => i.assessment_grade || i.overall_grade);
	if (graded.length > 0) {
		const avg = graded.reduce((s, i) => s + gradeValue(i.assessment_grade || i.overall_grade), 0) / graded.length;
		// Convert back to letter
		const letters = ['F', 'D-', 'D', 'D+', 'C-', 'C', 'C+', 'B-', 'B', 'B+', 'A-', 'A', 'A+'];
		document.getElementById('sl-stat-avg-grade').textContent = letters[Math.round(avg)] || '--';
	} else {
		document.getElementById('sl-stat-avg-grade').textContent = '--';
	}

	if (items.length === 0) {
		table.classList.add('hidden');
		empty.classList.remove('hidden');
		tbody.innerHTML = '';
		return;
	}

	table.classList.remove('hidden');
	empty.classList.add('hidden');
	tbody.innerHTML = '';

	items.forEach(item => {
		const tr = document.createElement('tr');
		tr.className = 'clickable';

		const grade = item.assessment_grade || item.overall_grade || '?';

		// Grade badge
		const tdGrade = document.createElement('td');
		tdGrade.innerHTML = '<span class="grade-badge ' + gradeClass(grade) + '">' + escapeHtml(grade) + '</span>';
		tr.appendChild(tdGrade);

		// Company
		const tdCompany = document.createElement('td');
		tdCompany.innerHTML = '<strong>' + escapeHtml(item.company_name || item.company || 'Unknown') + '</strong>';
		tr.appendChild(tdCompany);

		// Role
		const tdRole = document.createElement('td');
		tdRole.textContent = item.role || item.job_title || 'Unknown';
		tr.appendChild(tdRole);

		// Status dropdown
		const tdStatus = document.createElement('td');
		const select = document.createElement('select');
		select.className = 'status-select status-' + (item.status || 'shortlisted');
		STATUS_OPTIONS.forEach(opt => {
			const option = document.createElement('option');
			option.value = opt;
			option.textContent = opt.charAt(0).toUpperCase() + opt.slice(1);
			if (opt === (item.status || 'shortlisted')) option.selected = true;
			select.appendChild(option);
		});
		select.addEventListener('change', async (e) => {
			e.stopPropagation();
			const newStatus = select.value;
			select.className = 'status-select status-' + newStatus;
			try {
				await fetch(SERVER + '/api/shortlist/' + item.id, {
					method: 'PATCH',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({ status: newStatus }),
				});
				item.status = newStatus;
			} catch (err) {
				console.log('Failed to update status:', err);
			}
		});
		select.addEventListener('click', (e) => e.stopPropagation());
		tdStatus.appendChild(select);
		tr.appendChild(tdStatus);

		// Location
		const tdLoc = document.createElement('td');
		tdLoc.textContent = item.location || '--';
		tr.appendChild(tdLoc);

		// Salary
		const tdSalary = document.createElement('td');
		tdSalary.textContent = formatSalary(item);
		tr.appendChild(tdSalary);

		// Added date
		const tdDate = document.createElement('td');
		tdDate.className = 'date-cell';
		tdDate.textContent = formatDate(item.added_at || item.created_at);
		tr.appendChild(tdDate);

		// Delete button
		const tdDel = document.createElement('td');
		const btnDel = document.createElement('button');
		btnDel.className = 'btn-delete';
		btnDel.textContent = '\u2715';
		btnDel.title = 'Remove from shortlist';
		btnDel.addEventListener('click', async (e) => {
			e.stopPropagation();
			try {
				await fetch(SERVER + '/api/shortlist/' + item.id, { method: 'DELETE' });
				loadShortlist();
			} catch (err) {
				console.log('Failed to delete shortlist item:', err);
			}
		});
		tdDel.appendChild(btnDel);
		tr.appendChild(tdDel);

		// Row click opens posting URL
		tr.addEventListener('click', () => {
			if (item.posting_url) window.open(item.posting_url, '_blank');
		});

		tbody.appendChild(tr);
	});
}

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
		const resp = await fetch(SERVER + '/api/assessments?limit=200');
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
