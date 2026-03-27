import { describe, it, expect } from 'vitest';

const { isProfileStale } = await import('../utils.js');

describe('isProfileStale', () => {
	it('returns false when hashes match', () => {
		const stored = { candidate: 'abc', curated_resume: 'def', repo_profile: 'ghi' };
		const current = { candidate: 'abc', curated_resume: 'def', repo_profile: 'ghi' };
		expect(isProfileStale(stored, current)).toBe(false);
	});

	it('returns true when any hash changes', () => {
		const stored = { candidate: 'abc', curated_resume: 'def', repo_profile: 'ghi' };
		const current = { candidate: 'abc', curated_resume: 'CHANGED', repo_profile: 'ghi' };
		expect(isProfileStale(stored, current)).toBe(true);
	});

	it('returns true when a new profile type appears', () => {
		const stored = { candidate: 'abc' };
		const current = { candidate: 'abc', repo_profile: 'new' };
		expect(isProfileStale(stored, current)).toBe(true);
	});

	it('returns false when stored is null (first assessment)', () => {
		expect(isProfileStale(null, { candidate: 'abc' })).toBe(false);
	});

	it('returns false when current is empty', () => {
		const stored = { candidate: 'abc' };
		expect(isProfileStale(stored, {})).toBe(false);
	});
});
