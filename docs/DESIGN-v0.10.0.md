# UI and product design — v0.10.0

Research references: Base https://mobbin.com/screens/ac189337-ac0e-4981-9551-9d67b6931364 and profile https://mobbin.com/screens/a2412de7-c6d5-45b0-b495-f934f2b45a5c. Adapted restrained navigation, white space, quiet dividers and blue actions to this existing product. No Mobbin images redistributed.

Sources: https://www.nngroup.com/articles/ten-usability-heuristics/ and https://www.w3.org/WAI/WCAG22/quickref/ . These guide the design; this is not a certification or complete accessibility audit.

| Heuristic | Implementation |
|---|---|
| Visibility of system status | Connection, task, loading and sending-mode labels |
| Match the real world | Company, audience, research, review and delivery language |
| User control and freedom | Clear filters, remove chips, dialog close and unsaved-change guard |
| Consistency and standards | Repeated button styles, native form controls, shared spacing and icons |
| Error prevention | City/country guard, required industries, validation before import, unchanged approval gates |
| Recognition rather than recall | Selected chips, saved sessions, audience summary and source evidence |
| Flexibility and efficiency | Search, location shortcuts and preserved audience choices per browser tab |
| Aesthetic and minimalist design | Grouped form sections, progressive disclosure and quiet surfaces |
| Recognize, diagnose and recover | Specific inline validation, retry connection, no-match guidance |
| Help and documentation | Contextual helper text, workflow explanation and included operations guide |

Gestalt: proximity and common regions group audience fields and review sections; similarity makes repeated actions recognizable; selected blue states provide figure/ground separation without relying on color alone; ordered research steps show continuity. Industry accordions reduce the initial scanning load while chips keep selections visible.

Accessibility: visible focus, skip navigation, field labels, fieldset grouping, dialog semantics and status announcements; selected states include text/checkbox state. Action targets are at least 44px where styled. Motion respects reduced-motion preferences; forced-color overrides retain borders. Main text colors are dark on white, with blue reserved for actions.

Validation performed on an isolated local backend without Gmail or Notion credentials: Chrome accessibility tree confirmed labelled controls, Dubai shortcut, filtered industry selection and a complete generated research prompt with the correct brief, source requirements and applicant portfolio. Loading and connected states were observed. Automated Python checks cover targeting, imports, drafts, exclusions, delivery retries and stop conditions; see release validation.

Remaining manual audit: VoiceOver spoken announcements, physical keyboard-only journey, small-screen device testing and full WCAG contrast/state audit. Do not claim WCAG conformance. The existing production installation must be updated by its owner before the new design appears there.
