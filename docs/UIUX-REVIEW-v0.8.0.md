# Shine Acquisition v0.8.0 — UI and usability update

This update helps Shine find a suitable company, assess the evidence, and edit an introduction with fewer decisions on each screen. It preserves the installed Python backend and delivery rules; the backend files were compared byte-for-byte with the installed v0.7.0 files, excluding the version marker.

## Main changes

- One clear starting action: Find companies. Example records are available under contextual help.
- Discovery groups the audience, ChatGPT research, and import into three separate cards. Research and import appear once a session exists.
- Industry checkboxes replace the Command-click multi-select. Each group has a heading and a selected count.
- The pipeline starts with active opportunities; closed or excluded records remain available through the status filter. Clear filters shows all records.
- Fit is labelled out of 100 and described as a screening signal. Message totals include both client introductions and applications.
- Drafts use subject and message fields. Verified evidence stays in the advanced JSON section. Existing backend validation still decides whether a draft can be saved.
- Leaving a changed draft opens Keep editing / Discard changes. Preferences keep edits during polling and have a Discard changes action. Closing the tab with unsaved text invokes the browser's unsaved-changes prompt.
- JSON import previews company names, checks the response shape and session limit, and keeps pasted text after queuing so failed validation does not lose the research.
- Task summaries use plain language. Technical results remain available under disclosure controls.
- Mobile opportunities use stacked cards with an exposed Review button.

## Nielsen's 10 heuristics

| Heuristic | Implementation in this update |
| --- | --- |
| Visibility of system status | Local connection indicator, configured-mode wording, queued-task feedback, pending button labels, activity summaries. Configured automatic mode is not presented as proof that a delivery worker is running. |
| Match with the real world | Find companies, subject, message, and visible audience choices replace the most prominent technical terms. |
| User control and freedom | Cancel and Escape respect unsaved draft edits; Keep editing and Discard changes are explicit. Preference edits can be discarded. |
| Consistency and standards | Shared buttons, form labels, status badges, spacing, headings, and native controls across views. |
| Error prevention | Required audience fields, required brand industry, JSON size/shape/limit checks, pending-action locks, and preserved import input. Server validation remains authoritative. |
| Recognition rather than recall | Industry checkboxes, a saved-session summary, labelled status filters, and subject/message fields keep relevant information visible. |
| Flexibility and efficiency | Search, type/status filters, saved sessions, keyboard navigation, and advanced JSON editing remain available. |
| Aesthetic and minimalist design | Three research groups, one primary dashboard action, compact headings, and technical details hidden until requested. |
| Error recognition and recovery | Errors appear beside the relevant form. JSON syntax errors include a concrete correction. Failed requests retain the user's text. |
| Help and documentation | Contextual workflow help, industry guidance, score explanations, import instructions, and this update guide. |

## Gestalt principles

| Principle | Application |
| --- | --- |
| Proximity | Labels stay near their fields; related filters and draft actions share a group. |
| Common region | Each discovery stage has its own bordered card; each mobile opportunity is a separate card. |
| Similarity | Consistent primary buttons identify main actions; repeated form and status styles communicate equivalent roles. |
| Continuity | Audience → research → import follows the order of the actual task. |
| Figure and ground | White working surfaces contrast with the paper background; the active navigation item has a distinct outline and fill. |
| Common purpose | Industry options are grouped by business category, and feedback appears with the task it concerns. |

## Accessibility work

- Skip-to-content link, main navigation label, current-page indication, and heading focus after navigation.
- Visible keyboard focus, native checkbox controls, persistent labels, named dialog, and return focus when it closes.
- Main interactive buttons aim for a 44px minimum height; checkboxes have a full label target.
- Error text accompanies color. Focus and error states have distinct borders.
- Error/status announcements are available without repeated live announcements on the connection poll.
- Reduced-motion and forced-colors overrides are included. No external fonts are required.
- The redesigned phone layout uses one-column forms and opportunity cards.

Calculated contrast ratios for selected final tokens:

| Pair | Ratio |
| --- | --- |
| Muted text #53645b on paper #f5f7f4 | 5.83:1 |
| Primary green #24583f with white | 8.26:1 |
| Navigation text #d0dfd4 on #15372d | 9.40:1 |
| Draft badge text #725018 on #fff3de | 6.65:1 |
| Error text #9e2424 on #fff2ef | 7.03:1 |
| Focus outline #005fcc against white | 5.98:1 |
| Input boundary #738773 against white | 3.86:1 |

These checks do not constitute a complete WCAG conformance assessment. VoiceOver, 200–400% zoom, actual phone testing, and testing with intended users remain necessary. Gestalt and heuristic review are design checks, not evidence that user testing has succeeded.

## Validation and limits

- JavaScript syntax check passed.
- Nine existing targeting tests passed.
- Two existing updater tests passed, including preservation of existing state, credentials and targeting.
- HTML checks found no duplicate IDs, missing literal JavaScript DOM hooks, inline event handlers, or hidden required controls.
- Desktop browser preview exercised navigation, required industry feedback, session creation, invalid JSON recovery, company import preview, readable draft fields, and the unsaved-edit guard.
- A 390px viewport was inspected separately with sample data.
- The loopback HTTP test suite could not run: this execution session blocks binding local server sockets. Its 21 errors were socket PermissionErrors, not successful HTTP checks. Full authenticated integration testing remains to be run after installation.
- The preview uses clearly labelled sample records and an in-memory API stub. It does not test Gmail, Notion, external research, or message delivery.
- The existing installation on port 8766 has not been modified. Installation requires stopping its panel/workers and running the included updater in the existing folder.

## Source guidance

- Nielsen Norman Group: https://www.nngroup.com/articles/ten-usability-heuristics/
- W3C WCAG 2.2 quick reference: https://www.w3.org/WAI/WCAG22/quickref/


## Logo update

The sidebar and mobile header use Shine’s supplied SHINE PNG unchanged, with its original transparency and 2:1 proportions. An accessible home-link label is provided. The image is embedded in the page, so it works with the existing asset routes and content security policy. The original artwork is also kept at `acquisition_agent/panel_assets/shine-logo.png`.
