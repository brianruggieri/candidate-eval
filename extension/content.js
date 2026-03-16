/**
 * content.js — Job board extractor content script
 * Runs at document_idle on supported job board URLs.
 * Detects the board, extracts job data, stores to chrome.storage.local,
 * and responds to 'extractJobPosting' messages from the popup.
 */
(function () {
	'use strict';

	// ─── Utilities ────────────────────────────────────────────────────────────

	/** Return trimmed inner text of the first matching selector, or null. */
	function queryText(selectors) {
		for (const sel of selectors) {
			const el = document.querySelector(sel);
			if (el) {
				const text = el.innerText || el.textContent || '';
				if (text.trim()) return text.trim();
			}
		}
		return null;
	}

	/** Return trimmed text content of the first matching selector, or null. */
	function queryContent(selectors) {
		for (const sel of selectors) {
			const el = document.querySelector(sel);
			if (el) {
				const text = (el.innerText || el.textContent || '').trim();
				if (text) return text;
			}
		}
		return null;
	}

	// ─── LinkedIn ─────────────────────────────────────────────────────────────

	/**
	 * Find text content by looking for a heading containing specific text,
	 * then grabbing the content that follows it.
	 */
	function getTextAfterHeading(headingText) {
		const headings = document.querySelectorAll('h1, h2, h3, h4, [role="heading"]');
		for (const h of headings) {
			if (h.textContent.trim().toLowerCase().includes(headingText.toLowerCase())) {
				// Get the parent section/container, or walk siblings
				const parent = h.closest('section, article, div[class]');
				if (parent) {
					const text = parent.innerText || parent.textContent || '';
					if (text.trim().length > 50) return text.trim();
				}
				// Fallback: collect sibling text
				let text = '';
				let sibling = h.nextElementSibling;
				while (sibling) {
					const tag = sibling.tagName.toLowerCase();
					if (tag === 'h1' || tag === 'h2' || tag === 'h3') break;
					text += (sibling.innerText || sibling.textContent || '') + '\n';
					sibling = sibling.nextElementSibling;
				}
				if (text.trim().length > 50) return text.trim();
			}
		}
		return null;
	}

	function extractLinkedIn() {
		// Title — try specific selectors, then any h1
		const title = queryText([
			'.jobs-unified-top-card__job-title',
			'.jobs-details-top-card__job-title',
			'h1.job-title',
			'h1[class*="job-title"]',
			'.t-24.t-bold',
			'h1',
		]);

		// Company — try specific selectors, then look near the title
		const company = queryText([
			'.jobs-unified-top-card__company-name',
			'.jobs-details-top-card__company-info a',
			'.jobs-unified-top-card__subtitle-primary-grouping a',
			'[data-test-employer-name]',
			'.jobs-top-card__company-info a',
			'a[href*="/company/"]',
		]);

		// Description — try selectors first, then heading-based fallback
		let description = queryContent([
			'.jobs-description__content',
			'.jobs-box__html-content',
			'.description__text',
			'[class*="job-description"]',
			'#job-details',
			'.jobs-description',
		]);

		// Heading-based fallback: find "About the job" section
		if (!description || description.length < 50) {
			description = getTextAfterHeading('About the job');
		}

		// Last resort: grab the largest text block on the page
		if (!description || description.length < 50) {
			const candidates = document.querySelectorAll('section, article, main, [role="main"]');
			let best = '';
			for (const el of candidates) {
				const text = (el.innerText || '').trim();
				if (text.length > best.length && text.length > 100) {
					best = text;
				}
			}
			if (best.length > 100) description = best;
		}

		return {
			title: title || document.title,
			company: company || '',
			description: description || '',
			url: window.location.href,
			source: 'linkedin',
		};
	}

	// ─── Greenhouse ───────────────────────────────────────────────────────────

	function extractGreenhouse() {
		const title = queryText([
			'h1.app-title',
			'.job-post h1',
			'h1[class*="job"]',
			'h1',
		]);

		const company = queryText([
			'.company-name',
			'[class*="company-name"]',
			'.header--cobranded .company',
		]) || (document.title.split(' at ')[1] || '').trim() || '';

		const description = queryContent([
			'#content',
			'.job-post-description',
			'[class*="job-description"]',
			'.section-wrapper',
			'#app',
		]);

		return {
			title: title || document.title,
			company,
			description: description || '',
			url: window.location.href,
			source: 'greenhouse',
		};
	}

	// ─── Lever ────────────────────────────────────────────────────────────────

	function extractLever() {
		const title = queryText([
			'.posting-headline h2',
			'h2[data-qa="job-title"]',
			'.posting-header h2',
			'h2',
		]);

		const company = queryText([
			'.main-header-logo img[alt]',
		]) || (() => {
			const logoImg = document.querySelector('.main-header-logo img');
			return logoImg ? (logoImg.alt || '') : '';
		})();

		// Lever company name is sometimes embedded in the page title "Role - Company"
		const companyFromTitle = (() => {
			const parts = document.title.split(' - ');
			return parts.length > 1 ? parts[parts.length - 1].trim() : '';
		})();

		const description = queryContent([
			'.posting-description',
			'.posting-requirements',
			'[class*="posting"]',
			'.section-wrapper',
		]);

		return {
			title: title || document.title,
			company: company || companyFromTitle || '',
			description: description || '',
			url: window.location.href,
			source: 'lever',
		};
	}

	// ─── Indeed ───────────────────────────────────────────────────────────────

	function extractIndeed() {
		const title = queryText([
			'h1.jobsearch-JobInfoHeader-title',
			'.jobsearch-JobInfoHeader-title',
			'[data-testid="jobsearch-JobInfoHeader-title"]',
			'h1[class*="jobTitle"]',
			'.icl-u-xs-mb--xs.icl-u-xs-mt--none',
		]);

		const company = queryText([
			'.jobsearch-InlineCompanyRating-companyHeader a',
			'[data-testid="inlineHeader-companyName"]',
			'.jobsearch-CompanyAvatar-companyName',
			'.icl-u-lg-mr--sm.icl-u-xs-mr--xs',
			'[class*="companyName"]',
		]);

		const description = queryContent([
			'#jobDescriptionText',
			'.jobsearch-JobComponent-description',
			'[class*="jobDescription"]',
			'.jobsearch-jobDescriptionText',
		]);

		return {
			title: title || document.title,
			company: company || '',
			description: description || '',
			url: window.location.href,
			source: 'indeed',
		};
	}

	// ─── Generic Fallback ─────────────────────────────────────────────────────

	function extractGeneric() {
		const title = queryText([
			'h1',
			'.job-title',
			'[class*="job-title"]',
			'[class*="jobTitle"]',
			'[itemprop="title"]',
		]) || document.title;

		const company = queryText([
			'[class*="company"]',
			'[class*="employer"]',
			'[itemprop="hiringOrganization"]',
		]) || '';

		const description = queryContent([
			'[class*="job-description"]',
			'[class*="jobDescription"]',
			'[class*="description"]',
			'main',
			'article',
		]) || '';

		return {
			title,
			company,
			description,
			url: window.location.href,
			source: 'generic',
		};
	}

	// ─── Board Detection ──────────────────────────────────────────────────────

	function detectBoard() {
		const host = window.location.hostname;
		if (host.includes('linkedin.com')) return 'linkedin';
		if (host.includes('greenhouse.io')) return 'greenhouse';
		if (host.includes('lever.co')) return 'lever';
		if (host.includes('indeed.com')) return 'indeed';
		return 'generic';
	}

	function extractPosting() {
		const board = detectBoard();
		switch (board) {
			case 'linkedin':
				return extractLinkedIn();
			case 'greenhouse':
				return extractGreenhouse();
			case 'lever':
				return extractLever();
			case 'indeed':
				return extractIndeed();
			default:
				return extractGeneric();
		}
	}

	// ─── Auto-extract & Store ─────────────────────────────────────────────────

	function autoExtract() {
		try {
			const posting = extractPosting();
			if (posting && (posting.title || posting.description)) {
				chrome.storage.local.set({
					currentPosting: {
						...posting,
						extractedAt: Date.now(),
					},
				});
			}
		} catch (err) {
			// Silently ignore auto-extract failures
		}
	}

	// Run auto-extract after a short delay to allow dynamic content to render
	setTimeout(autoExtract, 1500);

	// ─── Message Listener ─────────────────────────────────────────────────────

	chrome.runtime.onMessage.addListener(function (request, _sender, sendResponse) {
		if (request.action === 'extractJobPosting') {
			try {
				const posting = extractPosting();
				if (posting && (posting.title || posting.description)) {
					// Store with timestamp
					const stored = { ...posting, extractedAt: Date.now() };
					chrome.storage.local.set({ currentPosting: stored });
					sendResponse({ success: true, posting: stored });
				} else {
					sendResponse({ success: false, error: 'No job content found on this page' });
				}
			} catch (err) {
				sendResponse({ success: false, error: err.message || 'Extraction failed' });
			}
			return true; // keep message channel open for async
		}
	});
})();
