# Design System Basics

## Foundation rules

- Grid: 8px base spacing system.
- Layout breakpoints: mobile-first with desktop enhancement.
- Typography hierarchy: clear distinction between page title, section title, helper text, and metadata.
- Component density: default compact mode for organizer operational screens, comfortable mode for participant-facing pages.

## Visual principles

- Prioritize readability over decorative styling.
- Reserve strong color emphasis for domain status and blocking actions.
- Use neutral surfaces for data-heavy screens to reduce cognitive load.

## Component anatomy standard

Each interactive field/component should expose:
- Label.
- Optional helper text.
- Validation or status message slot.
- Required/optional signal when relevant.
- Focus-visible style and disabled style.

## Interaction conventions

- Primary action appears once per section to avoid ambiguity.
- Secondary actions are visually lower emphasis and spatially separated.
- Destructive actions require confirmation and explain downstream effects.
- Long-running actions require progress indication and retry path.

## Responsive behavior

- Participant pages prioritize vertical stacking and thumb-reachable CTAs.
- Organizer tables collapse to card/list alternatives on narrow screens.
- Filters become bottom sheet or drawer on mobile.

## Content and microcopy standards

- Use plain language status text (for example: "Waitlisted - You are in queue position 8").
- Error messages must contain a reason and recovery guidance.
- Avoid internal system jargon where user-facing terms can be clearer.

## Design QA checklist (system level)

- Components meet focus, hover, disabled, and error states.
- No critical action depends on hover-only interactions.
- Screen-level hierarchy remains understandable at 320px width.
- Common empty states provide at least one next action.
