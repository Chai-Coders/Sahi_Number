# Design system

## Direction

Sahi Number uses a restrained civic-service desk visual world: warm paper surfaces, crisp ink, numbered receipt details, and one verification-green action colour. It should feel like a trustworthy public-interest utility used under pressure, not a fintech dashboard or security alarm.

## Surface mode

Operate. Familiar controls, immediate task entry, evidence-first hierarchy, and minimal motion.

## Tokens

- Paper: `#f6f1e7`; raised paper: `#fffdf7`; ink: `#17231d`; muted ink: `#536158`.
- Verification green: `#176b48`; deep green: `#0d4d34`; vermilion warning: `#a43f2d`.
- Borders are ink-tinted, shadows are soft with a small vertical offset, and radii stay 12–16px.
- System sans is intentional for an operational interface; tabular receipt IDs use the same family with tabular numerals.

## Composition

The first viewport begins with the question and the check form, not a marketing hero. A narrow top ledger carries the product name, mode, and language control. Results are a vertical evidence docket: reference strip first, then distinct number records with verdict icon/text, surfaces, history, and evidence link.

## Interaction

The single authored motion is the status docket settling into its completed state. Controls use standard affordances with explicit hover, focus, active, disabled, loading, and error treatments. Reduced-motion users receive immediate state changes.

## Responsive behavior

The mobile layout is the authority. At wider widths the form and explanatory copy share the first row; evidence remains readable rather than becoming a dense dashboard grid.

