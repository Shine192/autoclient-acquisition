# Visual direction and interaction notes

## Mobbin research

User reference: https://mobbin.com/apps/base-web-be80aae2-a0e3-40ef-a3e8-eb670b3eb156

Reviewed Base screens:
- Discover: https://mobbin.com/screens/54a9d37e-f506-441e-a095-3948604f9df1
  White sidebar, simple outline navigation icons, pale active navigation row,
  compact heading, broad white space, small blue accents.
- Account confirmation: https://mobbin.com/screens/98ffa113-57a2-4fe2-bd81-5ea4afad6973
  Restrained card borders, straightforward text hierarchy and clear actions.
- Email entry: https://mobbin.com/screens/758189a6-ec9c-47ea-96b3-0ddff9ddec5d
  Short title and helper text above one clearly bounded field.
- Profile: https://mobbin.com/screens/9e161b75-5c04-43f0-bd38-12db58d7ac33
  Consistent section spacing, quiet separators and aligned information.

No Mobbin screen images are redistributed in this package. The implementation
adapts the visual direction to the existing acquisition workflow.

## Implementation

Panel assets remain in acquisition_agent/panel_assets/. SVG icon paths are
local to app.js; no CDN, font download or new dependency is needed. The
v0.9 visual overrides are identified in style.css. Interface changes do not
alter delivery policy or automatically run discovery or sending.

Gestalt grouping: borders and spacing group fields, summary cards and table
rows; blue is reserved for primary actions, selected options and focus.
Consistent shape, icon stroke and typography connect related controls.

Visibility of status: loaders, request labels and background task state explain
what is happening without claiming a measurable completion percentage. Empty,
connection error and no-search-results states provide a next step. Existing
validation, review and unsaved-change protection remain.

Loading company data uses a request counter: results from a closed or superseded
review are ignored. Background refresh does not clear industry selections or
replace forms while the user edits them.

Manual follow-up checks: small-screen layout on the installed dashboard,
VoiceOver announcements, failed request recovery, draft loading completion,
and a complete keyboard journey using the actual local server.
