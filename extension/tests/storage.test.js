import { describe, it, expect, beforeEach } from 'vitest';
import { chrome, resetStore } from './chrome-mock.js';

// Make chrome global for utils.js
globalThis.chrome = chrome;

// Dynamic import so globalThis.chrome is set first
const { normalizeUrl, getForUrl, setForUrl, removeForUrl } = await import('../utils.js');

beforeEach(() => {
	resetStore();
});

describe('normalizeUrl', () => {
	it('strips tracking parameters', () => {
		const url = 'https://example.com/jobs/view/123?utm_source=google&trk=abc';
		expect(normalizeUrl(url)).toBe('https://example.com/jobs/view/123');
	});

	it('preserves non-tracking parameters', () => {
		const url = 'https://example.com/jobs?id=42&ref=apply';
		expect(normalizeUrl(url)).toContain('id=42');
	});

	it('strips hash fragments', () => {
		const url = 'https://example.com/jobs/123#section';
		expect(normalizeUrl(url)).toBe('https://example.com/jobs/123');
	});

	it('strips trailing slashes', () => {
		const url = 'https://example.com/jobs/123/';
		expect(normalizeUrl(url)).toBe('https://example.com/jobs/123');
	});

	it('sorts query parameters for stable keys', () => {
		const url1 = 'https://example.com/jobs?b=2&a=1';
		const url2 = 'https://example.com/jobs?a=1&b=2';
		expect(normalizeUrl(url1)).toBe(normalizeUrl(url2));
	});

	it('handles invalid URLs gracefully', () => {
		expect(normalizeUrl('not-a-url')).toBe('not-a-url');
	});

	it('handles empty/null input', () => {
		expect(normalizeUrl('')).toBe('');
		expect(normalizeUrl(null)).toBe('');
	});
});

describe('URL-keyed storage', () => {
	const url = 'https://example.com/jobs/view/123?utm_source=google';

	it('setForUrl + getForUrl roundtrip', async () => {
		await setForUrl('posting', url, { company: 'Acme' });
		const result = await getForUrl('posting', url);
		expect(result).toEqual({ company: 'Acme' });
	});

	it('different URLs get different values', async () => {
		await setForUrl('posting', 'https://example.com/job/1', { company: 'A' });
		await setForUrl('posting', 'https://example.com/job/2', { company: 'B' });
		expect(await getForUrl('posting', 'https://example.com/job/1')).toEqual({ company: 'A' });
		expect(await getForUrl('posting', 'https://example.com/job/2')).toEqual({ company: 'B' });
	});

	it('URLs differing only in tracking params share a key', async () => {
		await setForUrl('posting', 'https://example.com/job/1?utm_source=x', { company: 'A' });
		const result = await getForUrl('posting', 'https://example.com/job/1');
		expect(result).toEqual({ company: 'A' });
	});

	it('removeForUrl clears the value', async () => {
		await setForUrl('posting', url, { company: 'Acme' });
		await removeForUrl('posting', url);
		expect(await getForUrl('posting', url)).toBeNull();
	});

	it('getForUrl returns null for missing key', async () => {
		expect(await getForUrl('posting', url)).toBeNull();
	});

	it('different prefixes are independent', async () => {
		await setForUrl('posting', url, { company: 'Acme' });
		await setForUrl('assessment', url, { grade: 'A' });
		expect(await getForUrl('posting', url)).toEqual({ company: 'Acme' });
		expect(await getForUrl('assessment', url)).toEqual({ grade: 'A' });
	});
});
