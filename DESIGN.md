---
name: SONIQUEO
description: Personalized music discovery that learns what you enjoy and what you might love next.
colors:
  background: "#10110f"
  background-secondary: "#191b18"
  surface: "#22251f"
  surface-hover: "#2b2f27"
  surface-elevated: "#30342b"
  border: "#34372f"
  fg: "#f4f2ea"
  fg-secondary: "#a6a79d"
  fg-muted: "#9a9d93"
  accent: "#d7f36a"
  accent-hover: "#e4ff83"
  accent-muted: "#303b1d"
  on-accent: "#10110f"
  success: "#8ccb83"
  warning: "#e8b96a"
  error: "#e77b78"
typography:
  display:
    fontFamily: "Manrope, Inter, ui-sans-serif, sans-serif"
    fontSize: "clamp(2.25rem, 1.55rem + 2.4vw, 3rem)"
    fontWeight: 700
    lineHeight: 1.05
    letterSpacing: "-0.01em"
  headline:
    fontFamily: "Manrope, Inter, ui-sans-serif, sans-serif"
    fontSize: "2rem"
    fontWeight: 700
    lineHeight: 1.15
    letterSpacing: "-0.01em"
  title:
    fontFamily: "Manrope, Inter, ui-sans-serif, sans-serif"
    fontSize: "1.375rem"
    fontWeight: 700
    lineHeight: 1.25
    letterSpacing: "-0.01em"
  card-title:
    fontFamily: "Manrope, Inter, ui-sans-serif, sans-serif"
    fontSize: "1rem"
    fontWeight: 600
  body:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 400
    lineHeight: 1.55
  support:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 400
  meta:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 400
  label:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 600
    letterSpacing: "0.05em"
  button:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 600
rounded:
  button-sm: "8px"
  button: "10px"
  card: "14px"
  card-lg: "18px"
  modal: "18px"
  full: "9999px"
spacing:
  gutter-mobile: "16px"
  gutter-tablet: "24px"
  gutter-desktop: "40px"
  section-gap: "40px"
  grid-gap: "16px"
  card-padding: "12px"
  dialog-padding: "24px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.on-accent}"
    typography: "{typography.button}"
    rounded: "{rounded.button}"
    padding: "0 16px"
    height: "40px"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
  button-primary-lg:
    rounded: "{rounded.button}"
    padding: "0 24px"
    height: "48px"
  button-primary-sm:
    rounded: "{rounded.button-sm}"
    padding: "0 12px"
    height: "32px"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.fg}"
    typography: "{typography.button}"
    rounded: "{rounded.button}"
    padding: "0 16px"
    height: "40px"
  button-secondary-hover:
    backgroundColor: "{colors.surface-hover}"
  button-ghost:
    textColor: "{colors.fg-secondary}"
    typography: "{typography.button}"
    rounded: "{rounded.button}"
    padding: "0 16px"
    height: "40px"
  button-ghost-hover:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.fg}"
  button-icon:
    rounded: "{rounded.full}"
    size: "40px"
  button-icon-sm:
    rounded: "{rounded.full}"
    size: "32px"
  button-danger:
    backgroundColor: "{colors.error}"
    textColor: "{colors.on-accent}"
    rounded: "{rounded.button}"
    height: "40px"
  input:
    backgroundColor: "{colors.background-secondary}"
    textColor: "{colors.fg}"
    typography: "{typography.body}"
    rounded: "{rounded.button}"
    padding: "0 14px"
    height: "44px"
  search-field:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.fg}"
    rounded: "{rounded.full}"
    padding: "0 16px 0 40px"
    height: "40px"
  pill:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.fg-secondary}"
    typography: "{typography.meta}"
    rounded: "{rounded.full}"
    padding: "2px 10px"
  pill-active:
    backgroundColor: "{colors.accent-muted}"
    textColor: "{colors.accent}"
  track-card:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.card}"
    padding: "{spacing.card-padding}"
  track-card-hover:
    backgroundColor: "{colors.surface-hover}"
  mood-card:
    textColor: "{colors.fg}"
    rounded: "{rounded.card-lg}"
    padding: "16px"
  nav-item:
    textColor: "{colors.fg-secondary}"
    typography: "{typography.button}"
    rounded: "{rounded.button}"
    padding: "10px 12px"
  nav-item-active:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.fg}"
  tab-list:
    backgroundColor: "{colors.background-secondary}"
    rounded: "{rounded.full}"
    padding: "4px"
  tab-active:
    backgroundColor: "{colors.surface-hover}"
    textColor: "{colors.fg}"
    rounded: "{rounded.full}"
    padding: "6px 16px"
  menu:
    backgroundColor: "{colors.surface-elevated}"
    rounded: "{rounded.card}"
    padding: "6px"
  dialog:
    backgroundColor: "{colors.surface-elevated}"
    rounded: "{rounded.modal}"
    padding: "{spacing.dialog-padding}"
  player-bar:
    backgroundColor: "{colors.background-secondary}"
    height: "72px"
---

# Design System: SONIQUEO

## Overview

**Creative North Star: "The Liner Notes"**

SONIQUEO looks like the inside of a record sleeve read late at night: olive-black stock, type the
colour of bone, and one Signal Lime stroke marking what matters. Liner notes exist to tell you why
a record sounds the way it does. Here every recommended track carries its reason, and that line is
part of the layout, not hidden in a tooltip. The mood is **nocturnal, warm and assured**: warm,
olive-tinted darks rather than cold blue-black, confident Manrope headlines, and no hedging in the
hierarchy.

It is an app people work in. A sidebar, a header search, rows of track cards and a persistent
player make up the frame, and the frame stays quiet so the music can be loud. Colour beyond the
lime comes from artwork: Cover Art Archive covers where they exist, and deterministic generated
covers (dusk gradients with concentric rings) everywhere else. Depth is tonal: surfaces get lighter
as they rise, with soft dark shadows that seat each layer. A lime glow is kept for things that are
live.

Components feel **playful and springy** to the touch. They have soft corners, pill-shaped controls,
cards that lift on hover and play buttons that rise into view. The current build uses quick
ease-out transitions (150–200 ms), and new interaction work should lean springier from there. The
system is dark-only (`color-scheme: dark`), and there is no light theme.

**Key Characteristics:**

- Dark-only. Olive-tinted neutrals step up in lightness as surfaces rise.
- One accent, Signal Lime, for action, selection, focus, live state and discovery badges.
- Manrope for headlines and titles; Inter for body text, controls and metadata.
- A visible reason line under every recommended pick.
- Artwork carries the colour, and generated covers fill every gap.
- Soft, rounded shapes. Pills for chips, tabs, icon buttons and search. Artists are circles.
- Tonal depth with soft shadows to seat each layer. Glow only for live things.

## Colors

A warm olive-black ladder with bone-coloured type and a single Signal Lime voice. The status
colours are softened so they sit comfortably on the dark.

### Primary

- **Signal Lime** (`accent`): the one accent. It fills primary buttons, the skip link and the brand
  mark's tile. It colours the active nav icon, the active mobile tab, pressed feedback toggles, link
  buttons, the slider range and thumb ring, the checked switch thumb and chart bars. It is also the
  global focus ring, the eyebrow label above detail-page titles, the selected segment of the
  exploration control, and the text of the "New artist" discovery badge.
- **Signal Lime Bright** (`accent-hover`): the hover state for anything filled or tinted lime.
- **Signal Lime Shade** (`accent-muted`): a dark lime tint behind active pills, the selected
  segment, text selection and the checked switch track. It is also the first stop of the hero panel gradient.
- **Ink on Lime** (`on-accent`): text and icons on lime and danger fills. It is the same value as
  Olive Black.

### Neutral

- **Olive Black** (`background`): the page canvas, the html background and the browser theme
  colour.
- **Shadowed Olive** (`background-secondary`): the sidebar, the mobile tab bar and the player bar
  (both at 95% with backdrop blur), text inputs and the tab track.
- **Olive Charcoal** (`surface`): cards, secondary buttons, the search field, the active nav item,
  resting pills and the skeleton base.
- **Lit Olive** (`surface-hover`): hover for cards and rows, the active tab, slider and switch
  tracks, and the skeleton shimmer peak.
- **Raised Olive** (`surface-elevated`): dialogs, dropdown menus and the queue popover.
- **Olive Rule** (`border`): every 1px border. That includes inputs, secondary and outline buttons,
  the sidebar edge, the header's bottom edge (at 60%), dividers, dashed empty states and the
  dashed hidden-track notice.
- **Bone** (`fg`): primary text.
- **Weathered Bone** (`fg-secondary`): descriptions, artist lines, labels, inactive nav and ghost
  buttons.
- **Ash Bone** (`fg-muted`): placeholders, hints, durations, track numbers, reasons and the sidebar
  group label. It was lifted from the spec's #74776d so small text passes 4.5:1 on every surface.
  That leaves it close to Weathered Bone, so the two never separate a hierarchy on their own.

### Status

- **Fern** (`success`): verified-address and reliable-signal checks.
- **Amber** (`warning`): the offline banner icon, provider-limit pills and low-confidence signals.
- **Clay Red** (`error`): field errors, error-state borders (30%) and washes (5%), and the danger
  button (90% at rest, full on hover).
- `--color-info` (#82b8d9) is defined in `globals.css` but not used in the interface. Its hue
  appears only as one of the generated-cover glows.

### Named Rules

**The One Signal Rule.** Signal Lime marks what is actionable, selected, focused or live, plus
discovery badges ("New artist") and at most one eyebrow label or phrase per hero. If an element is
none of those, it is not lime. A discovery badge is always the tinted active pill (Signal Lime Shade
fill, lime text), never a solid lime fill, so it never competes with an action.

**The Artwork Carries Colour Rule.** Any hue beyond lime comes from covers, real or generated,
never from the interface. Surfaces stay on the olive ladder.

**The Warm Dark Rule.** Every neutral carries the olive tint (OKLCH hue around 125–135). Pure black
appears only as a translucent overlay: the dialog scrim (60%), artwork gradients (70–80%) and the
play-on-hover veil (50%).

## Typography

**Display Font:** Manrope (with Inter, ui-sans-serif)
**Body Font:** Inter (with ui-sans-serif, system-ui)

**Character:** Manrope's broad, geometric bold gives headlines the presence of an album title.
Inter keeps dense lists, reasons and controls crisp at 11–15px. Headings at the h1–h3 level take a
slight negative tracking (-0.01em).

### Hierarchy

- **Display** (Manrope 700, fluid 36→48px, 1.05): hero titles such as "Your mix", artist, track,
  mood and playlist headers (tightened to a line height of 1 there), the auth statement, the
  onboarding welcome and the 404 numeral.
- **Headline** (Manrope 700, 32px, 1.15): page titles, auth form titles, onboarding steps and large
  stat figures.
- **Title** (Manrope 700, 22px, 1.25): section headers, dialog titles and mood card titles.
- **Card Title** (Manrope 600, 16px): track and playlist card titles, artist names and empty-state
  titles.
- **Body** (Inter 400, 15px, 1.55): running text. Descriptions are held to about 36–42rem.
- **Support** (Inter 400, 13px): artist lines, section descriptions, field labels (500), hints and
  errors.
- **Meta** (Inter 400, 12px): reasons, durations and dropdown labels. Pills use 500.
- **Label** (Inter 600, 12px, 0.05em, uppercase): the eyebrow above detail-page titles (artist,
  track, mood, playlist; Signal Lime) and the sidebar "Library" label (Ash Bone). The Home hero
  carries no eyebrow.
- **Button** (Inter 600, 14px): buttons and nav items. Small buttons are 13px, large are 15px, and
  mobile tab labels are 11px.

### Named Rules

**The Reason Is Typeset Rule.** On every recommendation surface, the "why" line is set in Meta,
Ash Bone. It is clamped to two lines on cards (with the full text in a `title`) and one line in
rows. Never drop it to tidy a layout.

**The Tabular Figures Rule.** Track numbers, durations, queue positions and stat figures use
tabular numerals, so columns of numbers line up.

## Layout

The signed-in app fills the viewport (`100dvh`) and scrolls inside `main`. From 1024px up, a fixed
256px sidebar sits on the left. A sticky header (Olive Black at 85% with backdrop blur, Olive Rule
bottom edge at 60%) holds the search field and the account menu. Below 1024px, the sidebar becomes
a five-item bottom tab bar (at least 56px tall, padded for the safe area). The player bar (72px)
sits on top of that tab bar on mobile and at the bottom edge on desktop. The main area adds bottom
padding so content always clears both.

- **Page container:** centered, max width 1440px. Gutters are 16px, 24px and 40px at the base,
  640px and 1024px breakpoints. There is 24px above the first section, 40px below the last and 40px
  between sections.
- **Section header:** title (plus an optional description) on the left, the action on the right,
  bottoms aligned, 16px above the content.
- **Carousels:** horizontal snap rows. Items are 44vw (capped at 220px) on phones and 210px from
  640px, with a 16px gap. Scroll arrows sit above the row on the right from 640px.
- **Track rows:** a four-column grid (number 2rem, 48px art, text, actions). The number hides below
  640px and the duration appears from 768px.
- **Auth:** split 1.1fr / 1fr from 1024px. The left side is a 3×3 wall of generated covers fading
  into Olive Black, with the brand statement over it; the form is on the right. Below 1024px there
  is only the form.
- **Density:** compact but not cramped: 12px card padding, 16px grid gaps, 8–12px between controls.
- **Guarantee:** no horizontal page scroll at any width from 360 to 1920px.

**The Bleed Rule.** Carousels bleed past the page gutter to the viewport edge at every breakpoint
(negative margin equal to the gutter). Nothing else does.

## Elevation & Depth

Depth is tonal first, and shadow seats it. Layers step up the olive ladder (Olive Black, Shadowed
Olive, Olive Charcoal, Lit Olive, Raised Olive), so a higher layer is always a lighter one. Shadows
are dark, soft and low-contrast. They keep a layer seated rather than making it float. Translucent
chrome (header, tab bar, player) uses backdrop blur over the scrolling content. The dialog scrim is
black at 60% with a 2px blur.

### Shadow Vocabulary

- **Card** (`box-shadow: 0 1px 2px rgb(0 0 0 / 0.35), 0 4px 14px rgb(0 0 0 / 0.25)`): track,
  playlist, mood and genre cards, and the home hero panel, at rest.
- **Elevated** (`box-shadow: 0 2px 4px rgb(0 0 0 / 0.4), 0 10px 30px rgb(0 0 0 / 0.35)`): dropdown
  menus, the queue popover and the floating play button on cards.
- **Modal** (`box-shadow: 0 24px 60px rgb(0 0 0 / 0.55)`): dialogs.
- **Glow** (`box-shadow: 0 0 0 1px rgb(215 243 106 / 0.6), 0 0 28px rgb(215 243 106 / 0.22)`): the
  now-playing cover in the player and the slider thumb.

### Named Rules

**The Live Glow Rule.** The lime glow means "live": the track playing now, or the control under
the listener's thumb. It never decorates a static card, heading or hero.

## Shapes

Corners are soft, and the radius grows with the size of the object: 8px for small buttons, menu
items and row artwork; 10px for buttons, inputs, nav items and artwork tiles; 14px for cards, menus
and popovers; 18px for large cards, the hero panel, empty and error states, the auth cover wall and
dialogs. Chips, tabs, icon buttons, the search field, switches, slider tracks, avatars and artist
images are full pills or circles. Borders are 1px Olive Rule. Empty states use a dashed border.

Artwork has fixed proportions. Track, album and playlist art is square, mood cards are 4:5
portrait (4:3 landscape in the compact mood row on Home), and genre cards are short 96px bands. The recurring geometry is the generated cover's set
of concentric rings: two to four hairline circles around a seeded point, fading outward.

**The Circle Means Person Rule.** Artists are round. Tracks, albums, playlists, moods and genres
are rounded rectangles.

## Components

Playful and springy to the touch: soft, rounded and quick to respond. Today's motion is eased.
The direction for new interaction work is springier.

### Buttons

- **Shape:** gently rounded (10px; 8px at the small size). Icon buttons are circles (40px; 32px
  small). Icons are 16px with an 8px gap.
- **Primary:** Signal Lime fill with Ink on Lime text, 14px semibold. Medium is 40px tall with 16px
  sides, large is 48px with 24px, small is 32px with 12px.
- **Hover / Focus:** the fill brightens to Signal Lime Bright over 150ms. Focus is the global 2px
  Signal Lime outline at a 2px offset. Disabled is 50% opacity.
- **Secondary:** Olive Charcoal with a 1px Olive Rule border and Bone text. Hover is Lit Olive.
- **Ghost:** Weathered Bone text with no fill. Hover is Olive Charcoal with Bone text. Used for
  player controls, feedback toggles and the mobile search button.
- **Outline:** border only. Hover moves the border to Ash Bone and adds an Olive Charcoal fill.
- **Danger:** Clay Red at 90% with Ink on Lime text, full strength on hover.
- **Link:** Signal Lime text, underlined on hover with a 4px offset.
- **Feedback toggles** (like, dislike, save): small ghost icon buttons that turn Signal Lime when
  pressed (`aria-pressed`). The icon pops from 0.7 to 1 scale in 150ms.

### Chips

- **Style:** full pill, 1px border, 12px medium text, 2px by 10px padding. At rest: Olive Charcoal
  fill, Olive Rule border, Weathered Bone text.
- **Active:** Signal Lime Shade fill, Signal Lime text, lime border at 40%. Example: the "New
  artist" badge, which sits blurred over card artwork.
- **Variants:** source badges use the resting style. Provider-limit pills swap to an Amber border
  and text. The player's "listen on" links are outline pills with a trailing external-link icon.

### Cards / Containers

- **Corner Style:** 14px for track, playlist and genre cards; 18px for mood cards, the hero panel
  and states.
- **Background:** Olive Charcoal, moving to Lit Olive on hover. Artwork-backed cards (mood, genre)
  sit on a generated cover under a black gradient.
- **Shadow Strategy:** the Card shadow at rest (see Elevation & Depth).
- **Border:** none on content cards. Dashed Olive Rule on empty states and hidden-track notices.
  Clay Red at 30% on error states.
- **Internal Padding:** 12px on track and playlist cards, 16px on mood cards, 20px (32px from
  640px) on the hero panel.
- **Hover:** cards scale to 1.02 over 200ms and the fill lightens.

### Hidden Track Notice

What a disliked track collapses to on pages that hide on dislike (Home). It takes the place of the
track card or row: no fill, a 1px dashed Olive Rule border, 13px Weathered Bone text, a 16px Ash
Bone eye-off icon and "Hidden: <title>" with the title in Bone. Its actions are a small secondary
"Undo" and, when the artist is known, a small ghost "Exclude <Artist>". As a row it keeps the 10px
radius with 8px by 12px padding and the actions on the right; as a card it keeps the 14px radius,
12px padding and at least 160px height, with the actions at the bottom. It fades in over 200ms on
the soft ease-out curve, and focus moves to Undo so the listener can reverse at once.

### Inputs / Fields

- **Style:** 44px tall, 10px radius, Shadowed Olive fill, 1px Olive Rule border, 15px Bone text,
  Ash Bone placeholder, 14px horizontal padding. The label is 13px medium Weathered Bone, 6px above
  the field.
- **Focus:** the border turns Signal Lime, and fields show no outline. Hover moves the border to
  Ash Bone.
- **Error / Disabled:** the border turns Clay Red and a 13px Clay Red message appears below
  (`role="alert"`). Hints use the same slot in Ash Bone.
- **Search field:** a pill on Olive Charcoal, 40px tall, with a 16px Ash Bone search icon on the
  left.
- **Slider:** a 6px Lit Olive track with a lime range. The thumb is 20px, filled Olive Black, with
  a 2px lime ring and the Glow. It grows to 1.1 scale on hover.
- **Switch:** a 44×24 pill. When checked, the track becomes Signal Lime Shade with a lime border,
  and the thumb turns lime and slides 20px.

### Segmented Control

A single choice among a few named options, written as a radio group (the exploration control on
Home: Familiar, Balanced, Discoveries). The track is a full pill on Shadowed Olive with a 1px Olive
Rule border, a 4px inset and 4px gaps between equal-width segments. Each segment is at least 44px
tall, 14px semibold, Weathered Bone, moving to Bone on hover. The selected segment is the active
pill (Signal Lime Shade fill, lime border at 40%, Signal Lime text), and that pill slides between
segments on the toggle spring. Focus is the global lime outline around the segment. A 13px
Weathered Bone line underneath states what the choice means, with tabular figures.

### Navigation

- **Sidebar (1024px and up):** a 256px Shadowed Olive column with an Olive Rule right edge. Top to
  bottom: the brand mark, then the main nav (Home, Discover, Mood Mix, Search, Create), then the
  "Library" label, Playlists, Your taste and up to 20 playlist links (13px), with Settings at the
  bottom.
- **Nav item:** 14px semibold with a 20px icon, 10px by 12px padding, 10px radius. Inactive items
  are Weathered Bone, with an Olive Charcoal fill at 60% on hover. The active item gets an Olive
  Charcoal fill, Bone text and a Signal Lime icon.
- **Header:** sticky and blurred. It holds the search field (an icon button below 640px) and the
  account menu, a circular secondary button showing the user's initial.
- **Mobile tab bar (below 1024px):** Home, Discover, Search, Playlists and Your taste, each an icon
  over an 11px label. The active tab turns Signal Lime.
- **Tabs:** a pill track on Shadowed Olive with a 4px inset. The active tab is a Lit Olive pill with
  Bone text.
- **Menus:** Raised Olive, 14px radius, 6px padding, Elevated shadow. Items have an 8px radius,
  Weathered Bone text, and a Lit Olive highlight with Bone text.

### Brand Mark

The wordmark is "SONIQUEO" in capitals, set in Manrope ExtraBold (800) with tight tracking. It is
preceded by a 28px Signal Lime tile (8px radius) holding a waves glyph in Ink on Lime.

### Generated Cover

This is the signature component. It turns a seed into the same art every time: a linear gradient
between a dark base and a mid tone at a seeded angle, a soft radial glow, two to four concentric
hairline rings at 40% opacity, and optional initials in Manrope bold (white at 85%). Its eight dusk
palettes (lime, blue, magenta, amber, mint, violet, coral, sage) all have dark, desaturated bases
and one luminous glow. It sits under every cover image as the loading and fallback layer, and it is
the artwork for moods, genres, artists without images, and the auth wall.

### Persistent Player

A 72px bar in Shadowed Olive at 95% with backdrop blur. It shows the current cover (48px, with the
Glow), the title and artist, and ghost previous, next and shuffle buttons. From 768px it adds the
plain-spoken note "SONIQUEO does not play audio yet. Listen on", followed by "listen on" pills
(Spotify and YouTube searches). The queue toggle opens a Raised Olive popover with a numbered list, and the current item is
Signal Lime. The player shows no progress bar, elapsed time or waveform.

### Motion

- **Page enter:** fade with a 6px rise, 180ms, `cubic-bezier(0.22, 1, 0.36, 1)`.
- **Dialog:** fade, scale 0.97 to 1, 200ms on the same curve. The scrim fades in over 200ms.
- **Touch:** colour transitions are 150ms. The card hover scale (1.02) takes 200ms, and the play
  button rises 4px as it fades in.
- **Loading:** the skeleton shimmer sweeps Olive Charcoal to Lit Olive over 1.4s.
- **Reduced motion:** a global rule collapses every animation and transition to near zero.
- **Toggle spring** (`springToggle`: stiffness 500, damping 34, mass 1; damping ratio about 0.76):
  settles with one small overshoot. It is the first recorded spring, set by the segmented control's
  sliding selection. Press, toggle and reveal responses move to springs (physics springs through
  Motion), starting from this one. Page-level transitions stay short and eased. Motion honours
  reduced motion globally (`MotionConfig reducedMotion="user"`).

## Do's and Don'ts

### Do:

- **Do** keep every surface on the olive ladder (#10110f to #30342b) and every piece of text on
  Bone, Weathered Bone or Ash Bone.
- **Do** keep Signal Lime for action, selection, focus and live state, plus discovery badges (as
  the tinted active pill) and at most one eyebrow or phrase per hero (The One Signal Rule).
- **Do** show the reason line, in Meta and Ash Bone, on every recommended track.
- **Do** put a Generated Cover under every image, so no artwork slot is ever blank.
- **Do** make artists round and everything else a rounded rectangle.
- **Do** use tabular numerals for track numbers, durations, queue positions and stats.
- **Do** keep focus as the 2px Signal Lime outline at a 2px offset, and the field focus as a lime
  border.
- **Do** make new press, toggle and reveal responses springier, starting from the toggle spring
  (`springToggle`), with a reduced-motion fallback.

### Don't:

- **Don't** add a second accent hue to the interface. Extra colour comes from artwork.
- **Don't** use pure black or cool blue-black surfaces. Black appears only as a translucent overlay
  (50–80%).
- **Don't** put the lime glow on static content. It means "now playing" or "under your thumb".
- **Don't** imitate playback in the player: no progress bars, timers or animated waveforms.
- **Don't** rely on Weathered Bone versus Ash Bone alone to separate two text levels. Change size or
  weight too.
- **Don't** bring the unused info blue (#82b8d9) into the interface without a new, named need.
- **Don't** add light-theme styles inside a component. The system is dark-only, and a light theme
  would be a system-level decision.
