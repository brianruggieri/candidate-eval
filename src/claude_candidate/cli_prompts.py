"""CLI prompt helpers for interactive workflows.

This module is the designated home for interactive CLI prompts used by multiple
commands (e.g. both `sessions scan` and `whitelist setup`).
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from claude_candidate.session_scanner import ProjectSummary
	from claude_candidate.whitelist import WhitelistConfig


def _human_size(size_bytes: int) -> str:
	"""Format bytes as a human-readable size string."""
	value = float(size_bytes)
	for unit in ("B", "KB", "MB", "GB"):
		if value < 1024:
			if unit == "B":
				return f"{int(value)} B"
			return f"{value:.1f} {unit}"
		value /= 1024
	return f"{value:.1f} TB"


def _format_date(mtime: float) -> str:
	return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")


def interactive_whitelist_selection(
	projects: list[ProjectSummary],
	existing_whitelist: WhitelistConfig | None,
	hint_filter: str | None = None,
) -> WhitelistConfig:
	"""Present a numbered project table and prompt the user to select projects.

	Args:
		projects: All discovered projects (from discover_projects()).
		existing_whitelist: Current whitelist, or None if none exists.
		hint_filter: Optional substring filter on display_name (case-insensitive).

	Returns:
		A new WhitelistConfig with the selected projects.
	"""
	import click
	from claude_candidate.whitelist import WhitelistConfig

	if hint_filter:
		projects = [p for p in projects if hint_filter.lower() in p.display_name.lower()]
		if not projects:
			click.echo(f"No projects match filter '{hint_filter}'.")
			return existing_whitelist or WhitelistConfig()

	total_sessions = sum(p.session_count for p in projects)
	click.echo(f"\nFound {len(projects)} projects with {total_sessions} sessions\n")

	existing_hints: set[str] = set(existing_whitelist.projects) if existing_whitelist else set()

	# Table header
	click.echo(f"  {'#':>3}    {'Project':<30} {'Sessions':>8}  {'Size':>8}  Date range")
	click.echo(f"  {'':->3}    {'':->30} {'':->8}  {'':->8}  {'':-<23}")

	for i, proj in enumerate(projects, 1):
		# Mark if the project is currently whitelisted (exact match on canonical key)
		marker = "*" if proj.project_hint in existing_hints else " "
		oldest = _format_date(proj.oldest_mtime)
		newest = _format_date(proj.newest_mtime)
		size = _human_size(proj.total_size_bytes)
		click.echo(
			f"  {i:>3}  {marker} {proj.display_name:<30} {proj.session_count:>8}"
			f"  {size:>8}  {oldest} – {newest}"
		)

	click.echo()
	if existing_hints:
		click.echo(f"  * = currently whitelisted ({len(existing_hints)} projects)")
		click.echo()

	default_hint = "Enter=keep current" if existing_hints else "Enter=none"
	raw = click.prompt(
		f"Select projects (comma-separated numbers, 'all', 'none', {default_hint})",
		default="",
		show_default=False,
	).strip()

	if raw == "":
		if existing_whitelist and existing_whitelist.projects:
			click.echo("Keeping existing whitelist.")
			return existing_whitelist
		else:
			click.echo("No projects selected.")
			return WhitelistConfig()

	if raw.lower() == "all":
		selected = [p.project_hint for p in projects]
	elif raw.lower() == "none":
		selected = []
	else:
		selected = []
		for part in raw.split(","):
			part = part.strip()
			if not part.isdigit():
				click.echo(f"  Skipping invalid entry: '{part}'")
				continue
			idx = int(part)
			if 1 <= idx <= len(projects):
				selected.append(projects[idx - 1].project_hint)
			else:
				click.echo(f"  Skipping out-of-range: {idx}")

	# Confirmation summary
	click.echo(f"\nSelected {len(selected)} project(s):")
	for hint in selected:
		name = next((p.display_name for p in projects if p.project_hint == hint), hint)
		click.echo(f"  - {name}")

	if not click.confirm("\nSave this whitelist?", default=True):
		click.echo("Aborted.")
		raise SystemExit(0)

	return WhitelistConfig(projects=selected)
