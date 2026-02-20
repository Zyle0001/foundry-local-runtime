<script lang="ts">
	import { page } from '$app/stores';

	const navLinks = [
		{ href: '/', label: 'Home' },
		{ href: '/models', label: 'Models' },
		{ href: '/devices', label: 'Devices' },
		{ href: '/logs', label: 'Logs' }
	];
</script>

<style>
	:global(:root) {
		/* Layout */
		--bg-page: #05060a;
		--bg-surface: #0f1115;
		--bg-surface-alt: #151821;
		--border-subtle: #262a37;

		/* Text */
		--text-primary: #e6e9f2;
		--text-muted: #9ba0b5;

		/* Accents & states */
		--accent: #3b82f6;
		--accent-soft: #1d4ed8;
		--success: #22c55e;
		--danger: #f97373;

		/* Radii */
		--radius-sm: 0.35rem;
		--radius-md: 0.55rem;

		/* Spacing */
		--space-1: 0.25rem;
		--space-2: 0.5rem;
		--space-3: 0.75rem;
		--space-4: 1rem;
		--space-5: 1.5rem;

		color-scheme: dark;
	}

	:global(html),
	:global(body) {
		margin: 0;
		padding: 0;
		min-height: 100%;
		background-color: var(--bg-page);
		color: var(--text-primary);
		font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Ubuntu, Cantarell,
			'Helvetica Neue', Arial, sans-serif;
		line-height: 1.5;
	}

	:global(a) {
		color: var(--accent);
		text-decoration: none;
	}

	:global(a:hover) {
		color: #a5c7ff;
	}

	:global(h1),
	:global(h2),
	:global(h3) {
		color: var(--text-primary);
		margin: 0 0 var(--space-3);
	}

	:global(ul) {
		margin-left: 1.2em;
	}

	/* Status marks reused across pages */
	:global(.complete) {
		color: var(--success);
	}

	:global(.incomplete) {
		color: var(--danger);
	}

	/* Debug blocks */
	:global(pre) {
		background: #151820;
		color: #cdd6f4;
		padding: 0.75em;
		border-radius: 6px;
		overflow-x: auto;
		font-size: 0.9em;
	}

	/* ---- App shell ---- */

	.app-shell {
		min-height: 100vh;
		display: flex;
		background: radial-gradient(circle at top left, rgba(37, 99, 235, 0.18), transparent 55%),
			radial-gradient(circle at bottom right, rgba(16, 185, 129, 0.08), transparent 60%), var(--bg-page);
		color: var(--text-primary);
	}

	.app-nav {
		width: 230px;
		padding: var(--space-4);
		border-right: 1px solid var(--border-subtle);
		background: linear-gradient(to bottom, rgba(15, 17, 21, 0.96), rgba(7, 9, 13, 0.98));
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
	}

	.app-logo {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}

	.app-logo-mark {
		width: 28px;
		height: 28px;
		border-radius: 999px;
		background: radial-gradient(circle at 30% 20%, #4ade80, #22c55e 45%, #0f172a 80%);
		box-shadow: 0 0 0 1px rgba(34, 197, 94, 0.45), 0 8px 20px rgba(15, 23, 42, 0.9);
		display: inline-flex;
		align-items: center;
		justify-content: center;
		font-size: 0.75rem;
		color: #020617;
	}

	.app-logo-text {
		display: flex;
		flex-direction: column;
		gap: 0.1rem;
	}

	.app-logo-title {
		font-size: 0.95rem;
		font-weight: 600;
		letter-spacing: 0.03em;
		text-transform: uppercase;
	}

	.app-logo-subtitle {
		font-size: 0.75rem;
		color: var(--text-muted);
	}

	.app-nav-links {
		display: flex;
		flex-direction: column;
		gap: 0.15rem;
		margin-top: var(--space-2);
	}

	.app-nav-links a {
		display: block;
		padding: 0.45rem 0.6rem;
		border-radius: 0.45rem;
		color: var(--text-muted);
		font-size: 0.85rem;
		border: 1px solid transparent;
		transition: background 120ms ease, border-color 120ms ease, color 120ms ease, transform 80ms ease;
	}

	.app-nav-links a:hover {
		background: rgba(148, 163, 184, 0.08);
		color: var(--text-primary);
	}

	.app-nav-links a.active {
		background: radial-gradient(circle at top left, rgba(56, 189, 248, 0.35), rgba(37, 99, 235, 0.9));
		border-color: rgba(37, 99, 235, 0.85);
		color: #f9fafb;
		box-shadow: 0 0 0 1px rgba(15, 23, 42, 0.9), 0 8px 16px rgba(15, 23, 42, 0.75);
		transform: translateY(-0.5px);
	}

	.app-main {
		flex: 1;
		display: flex;
		justify-content: center;
	}

	.app-main-inner {
		width: 100%;
		max-width: 1120px;
		padding: var(--space-5);
	}

	/* ---- Shared UI primitives ---- */

	:global(.page-title-row) {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-3);
		margin-bottom: var(--space-4);
	}

	:global(.page-title-row h1) {
		margin: 0;
	}

	:global(.page-title-muted) {
		color: var(--text-muted);
		font-size: 0.9rem;
	}

	/* Buttons */
	:global(.btn) {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: 0.35rem;
		padding: 0.35rem 0.8rem;
		border-radius: var(--radius-sm);
		border: 1px solid var(--border-subtle);
		background: var(--bg-surface-alt);
		color: var(--text-primary);
		font-size: 0.85rem;
		line-height: 1.2;
		cursor: pointer;
		transition: background 120ms ease, border-color 120ms ease, color 120ms ease, transform 80ms ease,
			box-shadow 80ms ease;
	}

	:global(.btn:hover):not(:disabled) {
		background: #1f2937;
		border-color: rgba(148, 163, 184, 0.6);
		transform: translateY(-0.5px);
		box-shadow: 0 3px 8px rgba(15, 23, 42, 0.7);
	}

	:global(.btn:disabled) {
		opacity: 0.5;
		cursor: default;
		box-shadow: none;
		transform: none;
	}

	:global(.btn-primary) {
		background: linear-gradient(to right, #2563eb, #0ea5e9);
		border-color: #2563eb;
		color: #f9fafb;
	}

	:global(.btn-primary:hover):not(:disabled) {
		background: linear-gradient(to right, #1d4ed8, #0284c7);
		border-color: #1d4ed8;
	}

	:global(.btn-ghost) {
		background: transparent;
		border-color: transparent;
		color: var(--text-muted);
	}

	:global(.btn-ghost:hover):not(:disabled) {
		background: rgba(148, 163, 184, 0.12);
		border-color: rgba(148, 163, 184, 0.35);
		color: var(--text-primary);
	}

	/* Badges */
	:global(.badge) {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		padding: 0.1rem 0.55rem;
		border-radius: 999px;
		font-size: 0.72rem;
		font-weight: 500;
		border: 1px solid rgba(148, 163, 184, 0.3);
		background: rgba(15, 23, 42, 0.85);
		color: var(--text-muted);
	}

	:global(.badge-ok) {
		background: rgba(34, 197, 94, 0.14);
		border-color: rgba(34, 197, 94, 0.6);
		color: var(--success);
	}

	:global(.badge-missing),
	:global(.badge-error) {
		background: rgba(248, 113, 113, 0.12);
		border-color: rgba(248, 113, 113, 0.6);
		color: var(--danger);
	}

	:global(.badge-soft) {
		background: rgba(59, 130, 246, 0.14);
		border-color: rgba(59, 130, 246, 0.6);
		color: #bfdbfe;
	}

	:global(.badge-loaded) {
		background: rgba(168, 85, 247, 0.14);
		border-color: rgba(168, 85, 247, 0.6);
		color: #c084fc;
	}

	/* Alerts */
	:global(.alert) {
		position: relative;
		padding: 0.65rem 0.85rem;
		border-radius: var(--radius-md);
		border: 1px solid var(--border-subtle);
		background: rgba(15, 23, 42, 0.9);
		color: var(--text-muted);
		font-size: 0.85rem;
		margin-bottom: var(--space-3);
		display: flex;
		align-items: flex-start;
		gap: 0.5rem;
	}

	:global(.alert::before) {
		content: '';
		width: 3px;
		border-radius: 999px;
		background: rgba(148, 163, 184, 0.8);
		align-self: stretch;
	}

	:global(.alert-error) {
		border-color: rgba(248, 113, 113, 0.7);
		background: rgba(30, 7, 8, 0.95);
		color: var(--danger);
	}

	:global(.alert-error::before) {
		background: rgba(248, 113, 113, 0.95);
	}

	:global(.alert-title) {
		font-weight: 500;
		margin-bottom: 0.15rem;
	}

	:global(.alert-body) {
		color: inherit;
	}

	/* Basic responsiveness */
	@media (max-width: 768px) {
		.app-shell {
			flex-direction: column;
		}

		.app-nav {
			width: 100%;
			flex-direction: row;
			align-items: center;
			justify-content: space-between;
			padding: var(--space-3) var(--space-4);
			border-right: none;
			border-bottom: 1px solid var(--border-subtle);
		}

		.app-nav-links {
			flex-direction: row;
			gap: 0.25rem;
			margin-top: 0;
			overflow-x: auto;
		}

		.app-nav-links a {
			white-space: nowrap;
			padding-inline: 0.6rem;
			font-size: 0.8rem;
		}

		.app-main-inner {
			padding: var(--space-4);
		}
	}
</style>

<div class="app-shell">
	<aside class="app-nav">
		<div class="app-logo">
			<span class="app-logo-mark">AI</span>
			<div class="app-logo-text">
				<span class="app-logo-title">Local AI Runtime</span>
				<span class="app-logo-subtitle">Model host dashboard</span>
			</div>
		</div>

		<nav class="app-nav-links" aria-label="Primary">
			{#each navLinks as link}
				<a
					href={link.href}
					class:active={
						$page.url.pathname === link.href ||
						(link.href !== '/' && $page.url.pathname.startsWith(link.href))
					}
					aria-current={$page.url.pathname === link.href ? 'page' : undefined}
				>
					{link.label}
				</a>
			{/each}
		</nav>
	</aside>

	<main class="app-main">
		<div class="app-main-inner">
			<slot />
		</div>
	</main>
</div>
