# Dashboard usability review — v0.14.0

Reviewed the running v0.13.1 Mac dashboard and implemented improvements in a separate v0.14.0 release. The current white, blue, rounded-card system and transparent Shine logo are retained. Sending rules and authorization are not changed by the UI work.

## Mobbin references examined

- [Programa grouped project lists](https://mobbin.com/screens/057a85b2-2598-4d36-9638-1437f9c5cf5b): grouping related work with clear section boundaries and restrained status treatment.
- [Bonsai overview](https://mobbin.com/screens/5ac492a4-c466-4a97-9adc-0c7341c4e123): clear dashboard overview, summary cards and recent activity.
- [Plane project overview](https://mobbin.com/screens/b40e6a3a-28da-4f4d-86ba-3bd593a9fdf0): visible progress and separation between primary work and supporting information.

These are pattern references, not copied branding or downloaded screenshots. Search did not return the previously supplied Base screen, so no Base-specific visual claims are made.

## Nielsen’s ten heuristics

| Heuristic | Finding and implemented change |
|---|---|
| System status | Configured automatic mode was not proof of a worker. A read-only lifetime-lock check now reports whether the Run-Shine worker is detected. Research progress is tied to its session; campaign attempts have a progress bar. |
| Real-world language | Removed the obsolete manual-only banner. Candidate research limits and sending targets are explained separately. |
| User control | Preserve pause, draft cancellation, removable industry selections and manual fallback. Added reconnect and unsaved campaign navigation protection. |
| Consistency | Shared control sizes, focus styles and status colors use the existing blue palette. The candidate input now matches the automatic pilot’s ten-candidate cap. |
| Error prevention | Disabled research retains its disabled state after pending operations; its setup explanation is attached to the control. Missing brand-industry selections open and focus the choice that needs attention. |
| Recognition | Saved audience summaries, selected industry chips and visible reasons for delivery holds reduce recall. |
| Efficiency | Pipeline counts filter results; sent/conversation has a dedicated filter. `/` focuses pipeline search outside editable fields and dialogs. |
| Minimalism | Earlier activity, technical details and long research sources are collapsed. Only the latest task is shown outside history. Industry categories begin collapsed. |
| Error recovery | Recovery steps stay available alongside preserved historical results. Reconnect remains available after the initial load. Existing exact-quote validation and repair workflows remain intact. |
| Help | Contextual next-step guidance, candidate help, API setup instructions, manual alternatives, installation and rollback guidance are included. |

## Gestalt principles

- **Proximity and common region:** audience controls, saved-session research, campaign setup and recent activity have distinct containers. Approval follows the message it approves.
- **Similarity:** repeated buttons, status badges and form fields share size, color and shape. Status is also expressed in words.
- **Hierarchy and figure/ground:** blue emphasizes the primary action and next-step card. Historical errors sit behind disclosure controls rather than competing with the current task.
- **Continuity:** the audience → research → review sequence remains visible; outcome state updates the journey. The overview links directly into the next action.

## Accessibility changes

Controls aim for at least 44 CSS px height. Labels and helper associations remain visible; validation appends error descriptions without losing existing help. External links announce a new tab. Keyboard focus has a visible 3 px outline. Smaller interface text has been enlarged. Status colors have stronger contrast. Reduced-motion and forced-color support remain in place. Disclosure state is retained when activity updates. Campaign edits participate in the existing leave-page warning.

## Verification

- 224 offline Python tests passed, including new tests for detecting an active worker, rejecting stale lock files as activity, and ensuring status checks do not create a lock or release another worker’s lock. The UI-update installer test also verifies exact preservation of policy, profile, approval and SQLite history after the v0.13 migration.
- JavaScript syntax check passed.
- Browser checks in an isolated workspace: Dubai/Agency session creation, missing-key disabled explanation and focus, saved session summary, collapsed industries, recent/history split, review dialog draft-before-approval order, metric filters, `/` search focus, and empty browser error log.
- Narrow-screen checks at requested viewport overrides 390 and 320 CSS px; no document horizontal overflow observed. Default browser sizing restored afterward.
- Existing tests cover queue duplication, retries, approval checks, reply stops and installer preservation. No paid research or production emails were triggered for this review.

This is an implementation review, not a WCAG conformance certification. Full VoiceOver testing, a complete contrast scan of every interaction state, and testing across all browsers remain future checks. Worker detection observes the combined Run-Shine runner only; it is not a promise that a message is eligible or that an independently launched worker is absent.

## Standards and guidance

- [Nielsen Norman Group: ten usability heuristics](https://www.nngroup.com/articles/ten-usability-heuristics/)
- [W3C: WCAG 2.2 quick reference](https://www.w3.org/WAI/WCAG22/quickref/)
