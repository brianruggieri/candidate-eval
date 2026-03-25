/**
 * content.js — Raw page text grabber for LLM-based extraction.
 * No CSS selectors. No board detection. Grabs visible text and returns it.
 * Injected on-demand via chrome.scripting.executeScript from the popup.
 */
(function () {
	'use strict';

	const MAX_TEXT_LENGTH = 15000;

	function expandTruncatedContent() {
		// LinkedIn "...more" buttons that expand truncated job descriptions
		const selectors = [
			'button.show-more-less-html__button--more',
			'[data-tracking-control-name="public_jobs_show-more-html-btn"]',
			'a.show-more-less-html__button',
			'button[aria-label="Show more"]',
			'footer button', // generic "see more" in cards
		];
		for (const sel of selectors) {
			const btns = document.querySelectorAll(sel);
			btns.forEach(btn => {
				if (btn.offsetParent !== null) btn.click();
			});
		}
	}

	function grabPageText() {
		// Expand any truncated sections first
		expandTruncatedContent();

		const text = (document.body.innerText || '').substring(0, MAX_TEXT_LENGTH);
		return {
			url: window.location.href,
			title: document.title,
			text: text,
			extractedAt: Date.now(),
		};
	}

	function heuristicFallback() {
		const h1 = document.querySelector('h1');
		const title = h1 ? (h1.innerText || '').trim() : document.title;

		let best = '';
		const candidates = document.querySelectorAll('section, article, main, [role="main"], div');
		for (const el of candidates) {
			const t = (el.innerText || '').trim();
			if (t.length > best.length && t.length > 100 && t.length < MAX_TEXT_LENGTH) {
				best = t;
			}
		}

		return {
			company: '',
			title: title,
			description: best,
			url: window.location.href,
			source: 'heuristic',
			location: null,
			seniority: null,
			remote: null,
			salary: null,
		};
	}

	if (!chrome?.runtime?.onMessage) return; // extension context invalidated — tab needs reload

	chrome.runtime.onMessage.addListener(function (request, _sender, sendResponse) {
		try {
			if (request.action === 'extractJobPosting') {
				// Expand first, wait for DOM to update, then grab
				expandTruncatedContent();
				// Try again after a beat in case first click didn't register
				setTimeout(() => expandTruncatedContent(), 200);
				setTimeout(() => {
					const text = (document.body.innerText || '').substring(0, MAX_TEXT_LENGTH);
					sendResponse({ success: true, pageData: {
						url: window.location.href,
						title: document.title,
						text: text,
						extractedAt: Date.now(),
					}});
				}, 600);
				return true; // keep channel open for async response
			} else if (request.action === 'extractFallback') {
				const posting = heuristicFallback();
				sendResponse({ success: true, posting });
			} else {
				sendResponse({ success: false, error: 'Unknown action' });
			}
		} catch (err) {
			sendResponse({ success: false, error: err.message || 'Content script error' });
		}
		return false;
	});
})();
