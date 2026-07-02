---
name: neobrutalism-design-system
description: Applies Neobrutalism UI design system rules. Use when the user says 'neobrutalism design system', 'apply design system', or builds UI for HESD.
---

# Neobrutalism Design System

Act as a UI implementation guide. Every screen, component, and layout must follow the Neobrutalism design system at `{workflow.design_system_path}`. The modules describe what the UI looks like; you choose how to implement styles in the project's stack.

**Style:** hard offset shadows (no blur), 2–3px solid borders, sharp corners, saturated color, fast 100–150ms interactions, physical hover/press movement.

## Resolution rules

- Bare paths and `{skill-root}` resolve from this skill's installed directory.
- `{project-root}` → the project working directory.
- `{skill-name}` → the skill directory's basename.
- Design system modules resolve from `{workflow.design_system_path}/`.

## On Activation

1. Resolve customization: `uv run {project-root}/_bmad/scripts/resolve_customization.py --skill {skill-root} --key workflow`. On failure, read `{skill-root}/customize.toml` directly and use defaults.
2. Treat every entry in `{workflow.persistent_facts}` as foundational context (entries prefixed `file:` are loaded).
3. Read `references/module-index.md` for the full module list and `references/module-routing.md` to select which modules apply to the current UI task.
4. Load applicable module files from `{workflow.design_system_path}/` before writing UI code.

Run `{workflow.activation_steps_prepend}` and `{workflow.activation_steps_append}` if non-empty.

## Before Writing UI Code

1. Identify the screen or task type and load every applicable module from `references/module-routing.md`.
2. Do not write component markup until all relevant modules are loaded.
3. Cross-reference modules when components nest (card + button, form + alert, table + badge).

## Critical Rules

- **Tokens are agnostic, not framework classes.** Names like `neutral-primary-soft`, `heading`, and `border-default` are design tokens — not literal Tailwind classes. Map tokens in CSS or theme config; never assume `bg-neutral-primary-soft` exists.
- **Dark mode is automatic.** Use CSS custom properties with `prefers-color-scheme: dark`. Never manually swap light/dark colors per component.
- **Every interactive element** needs hover, focus, and disabled states defined in the relevant module.
- **Semantic HTML:** proper `h1`–`h6` hierarchy, `<button>` for actions, `<a>` for navigation, ARIA where needed.
- **No soft shadows or subtle borders.** Neobrutalism uses hard offset shadows and thick solid borders only.
- **No raw hex in component code.** Use design tokens from `colors.md`.
- **Typography:** Archivo Black for headings (`--font-head`), Space Grotesk for body (`--font-sans`). Do not override at component level.

## HESD Product Context

This project builds a mobile-web workshop attendance system (~100–150 students). Prioritize modules for: check-in forms (`inputs.md`, `buttons.md`, `alerts.md`), realtime dashboards (`tables.md`, `badges.md`, `tabs.md`), QR display screens (`cards.md`, `badges.md`), and status feedback (`alerts.md`, `badges.md`). Preserve product invariants from `project-context.md` regardless of visual styling.
