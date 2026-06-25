# App Layout Components

## App shell

### Top bar
- Product identity.
- Current role and organization context.
- User menu with account/session actions.

### Side navigation (organizer views)
- Role-aware menu visibility.
- Current section highlight.
- Collapsible behavior for smaller screens.

### Main content frame
- Page header (title, subtitle, key actions).
- Body content (cards, tables, forms).
- Optional right-side contextual panel for quick details.

## Layout templates by role

### Participant template
- Minimal global chrome.
- Focus on event discovery and action clarity.
- Primary CTA near fold on event detail.

### Organizer Admin template
- Data-dense layout with metrics and operations sections.
- Persistent filtering controls for list-heavy screens.
- Quick links to audit and exports.

### Organizer Staff template
- Streamlined shell for rapid check-in.
- Reduced navigation complexity to avoid operational errors.

## Section-level layout components

- KPI summary strip.
- Filter bar.
- List/table region with pagination footer below content.
- Details drawer.
- Empty/failure fallback block.

Filter bar remains visible (sticky) while list rows scroll; pagination sits below the list region.

## Responsive rules

- Below tablet width: side navigation becomes overlay/drawer.
- Filter bar can collapse to a single "Filter" trigger.
- Wide tables switch to stacked rows with labeled fields.

## Layout anti-patterns to avoid

- Multiple primary buttons in the same visual hierarchy level.
- Hidden critical actions in overflow menus.
- Deep nesting of cards that obscures key status information.
