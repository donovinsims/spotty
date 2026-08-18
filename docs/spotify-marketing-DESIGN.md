# Spotify — Marketing site Design Spec

> Source: spotify.com/us/premium (live DOM, computed styles), 2026-07-19. No CSS custom properties are published — every value is read from computed styles.
> Coverage: Premium marketing landing. `spotify.com` redirects to the `open.spotify.com` web player, so the marketing surface was captured at the Premium path. The web player (a distinct dark app shell) is **not** captured here.
> Note: the brand green is **`#1ED760`**, not the older `#1DB954` — the queue hint was out of date.

## 1. Visual Theme & Atmosphere

Spotify's marketing surface is a pure-black stage for one enormous typographic gesture. The hero headline runs at **128px in a variable display face at weight 900**, and one word of it flips to an oblique cut — a mixed roman/italic headline is the brand's most recognisable typographic move. Everything else gets out of the way: white text, a `#b3b3b3` muted grey, near-black `#121212`/`#242424` panels, and no borders. Spotify Green `#1ED760` appears in exactly one role — the filled pill CTA — while the wider brand palette (pinks, lilacs, blues, olives) is reserved for plan cards and editorial imagery. Weight is used as an expressive axis across the whole range, from 900 headlines down to **300** sub-headings, which is unusual and gives the page its editorial-poster feel. Feels: bold, black-stage, editorial, music-loud.

## 2. Color Palette & Roles

### Core

| Token | Hex | Role / usage |
|---|---|---|
| `green` | `#1ED760` | THE accent — the filled pill CTA, and only that |
| `black` | `#000000` | Page canvas and nav |
| `near-black` | `#121212` | Deep panel / text on green |
| `surface` | `#242424` | Card fill (most common panel) |
| `surface-2` | `#222326` | Circular icon button |
| `white` | `#FFFFFF` | Primary text |

### Text

| Token | Hex | Role / usage |
|---|---|---|
| `text` | `#FFFFFF` | Headlines and body |
| `muted` | `#B3B3B3` | Fine print, legal copy |
| `muted-2` | `#A7A7A7` | Secondary meta |
| `muted-3` | `#919496` | Tertiary meta |
| `faint` | `#D9DADC` | Near-white secondary |
| `on-green` | `#121212` / `#000000` | Text on the green pill |

### Borders &amp; overlays

| Token | Value | Role / usage |
|---|---|---|
| `border-outline` | `#7F7F7F` | The 1px outline-button border |
| `overlay-white-10` | `rgba(255,255,255,.10)` | Glass chip fill |
| `scrim` | `linear-gradient(rgba(0,0,0,0), rgba(0,0,0,0.75))` | Media legibility scrim |

### Plan / editorial palette (never chrome)

`pink #FFD2D7` &middot; `lilac #C4B1D4` &middot; `periwinkle #576DD6` &middot; `blue #0D72EA` &middot; `olive #5F8008` &middot; `violet #7358FF` &middot; `amber #FFC862` &middot; `mauve #A16387` &middot; `magenta #E4078B` &middot; `oxblood #701818`

**Rules.** Green is the CTA fill and nothing else — not a link colour, not a heading colour, not a background. Panels are flat `#242424` with no border. The plan/editorial hues colour plan cards and imagery only, never chrome.

## 3. Typography Rules

- Display: `SpotifyMixUITitleVariable, CircularSp-Arab` — a variable face used across an unusually wide weight range
- UI + body: `SpotifyMixUI, CircularSp-Arab`

| Role | Family | Size/Line | Weight | Tracking |
|---|---|---|---|---|
| Hero h1 | SpotifyMixUITitleVariable | 128/normal | **900** | normal |
| Section h2 | SpotifyMixUITitleVariable | 64/normal | 800 | normal |
| Editorial h2 | SpotifyMixUITitleVariable | 48/normal | **400** | normal |
| Lead paragraph | SpotifyMixUITitleVariable | 32/normal | **300** | normal |
| Sub-heading h3 | SpotifyMixUITitleVariable | 24/normal | **300** | normal |
| Sub-heading h3 (alt) | SpotifyMixUITitleVariable | 24/normal | 400 | normal |
| Body | SpotifyMixUI | 16/normal | 400 | normal |
| Fine print | SpotifyMixUI | 12/normal | 400 | normal (`#B3B3B3`) |
| Button label | SpotifyMixUI | 16 | 700 | normal |

Patterns: the display face spans **300 to 900** — the full variable range is in active use, and light weights (300) are deliberately paired against the 900 hero rather than a mid-weight. Line-height is left at `normal` throughout and tracking is `normal` at every size, including 128px. The signature detail is a **mixed roman/oblique headline**: one word of the hero is set in the italic cut for emphasis. Sentence case; no uppercase eyebrows.

## 4. Component Stylings

**Nav** — 72px, solid `#000000`, no border. Wordmark, then links at 16/700, a divider, and the green pill CTA at 38px.

**Buttons** — every button is a **9999px pill** with a 16/700 label and `8px 32px` padding:

| Variant | Fill | Text | Border | Radius | Height | Padding | Type |
|---|---|---|---|---|---|---|---|
| Primary (hero) | `#1ED760` | `#000000` | none | 9999px | 48px | 8px 32px | 16/700 |
| Primary (nav) | `#1ED760` | `#000000` | none | 9999px | 38px | 8px 32px | 16/700 |
| Outline | transparent | `#FFFFFF` | 1px `#7F7F7F` | 9999px | 48px | 8px 32px | 16/700 |
| Inverse | `#FFFFFF` | `#121212` | none | 500px | 32px | 16px 48px | 16/700 |
| Glass chip | `rgba(255,255,255,.10)` | `#FFFFFF` | none | 48px | 48px | 1px 6px | 13.33/400 |
| Icon button | `#222326` | `#FFFFFF` | none | 50% | 54px | 0 16px | — |

Transition: `background-color 0.15s cubic-bezier(0.3, 0, 0, 1)` — a sharp custom ease.

**Plan card** — `#242424` fill with split radii (`10px 10px 0 0` for the header band, `0 0 10px 10px` for the body), a coloured header drawn from the plan palette, and a green pill CTA at the foot. No border.

**Signature hero** — full-bleed photography under a `linear-gradient(rgba(0,0,0,0), rgba(0,0,0,0.75))` scrim, with the 128px/900 headline overlaid and one word in the oblique cut.

**Inputs** — not captured (no exposed form fields on the Premium landing page).

## 5. Layout Principles

A black page built from full-width bands: the photographic hero, then alternating editorial sections that pair a 64/800 heading with a 24/300 sub, then a plan-card grid. Content is left-aligned in the hero (not centered), which is what lets the 128px headline breathe across three lines. Radius census: `1px`, `6px 0`, `10px 10px 0 0`, `0 0 10px 10px`, `24px`, `48px`, `500px`, `9999px`, `50%`.

## 6. Depth & Elevation

Radius scale: `10px` (cards, split into top/bottom halves) / `24px` / `48px` / `500px` / `9999px` (all buttons) / `50%` (icon buttons).

Shadow recipes observed:

- `rgba(0, 0, 0, 0.15) 0px 5px 10px 0px`
- `rgba(0, 0, 0, 0.2) 0px 0px 18px 0px`
- `rgb(153, 153, 153) 0px 2px 10px -3px`

Shadows are rare — on a black canvas they read as glow rather than lift. Depth is really the surface step `#000000` &rarr; `#121212` &rarr; `#222326` &rarr; `#242424`, with **no borders on panels** (the only 1px border in the system is the outline button).

## 7. Motion

- `background-color 0.15s cubic-bezier(0.3, 0, 0, 1)` — the house curve on buttons
- `background-color 0.2s`
- `0.25s ease-in-out 0.25s` — a delayed reveal
- a general `all` transition

No scroll-jacking library detected; the hero motion is background video.

## 8. Backgrounds, Effects & WebGL

Photography and video over black. No WebGL, no canvas, no backdrop-filter, no grain. The single gradient is the legibility scrim `linear-gradient(rgba(0,0,0,0), rgba(0,0,0,0.75))`. Depth and atmosphere come from full-bleed imagery, not from CSS effects.

## 9. Do's and Don'ts

### Do
- Put everything on a pure `#000000` stage and step surfaces `#121212` &rarr; `#222326` &rarr; `#242424`.
- Set the hero at a genuinely enormous size (128px) at weight 900, left-aligned.
- Use the full variable weight range — pair 900 headlines with 300 sub-headings.
- Set one word of the hero in the oblique cut for the signature mixed-italic headline.
- Make every button a 9999px pill at 16/700 with `8px 32px` padding.
- Keep Spotify Green `#1ED760` to the filled CTA only.
- Leave line-height and tracking at `normal`, even at 128px.

### Don't
- Don't use `#1DB954` — that is the retired green; the current brand colour is `#1ED760`.
- Don't use green for links, headings or backgrounds.
- Don't add borders to panels; the only 1px border is the outline button.
- Don't use mid-weights where the system wants extremes (300 or 800/900).
- Don't put the plan/editorial hues into chrome.
- Don't centre the hero or add tracking to the display type.

## 10. Responsive Behavior

Not captured — no media-query census was resolved from the accessible stylesheets. The 128px hero is fluid in practice, but the exact breakpoint scale was not observed.

## 11. Agent Prompt Guide

- Canvas `#000000` · Panel `#242424` / `#121212` · Text `#FFFFFF` · Muted `#B3B3B3` · Outline border `#7F7F7F` · Accent `#1ED760`
- Font: SpotifyMixUITitleVariable (display, 300-900), SpotifyMixUI (UI/body) · Body: 16 · Radius: 9999px button / 10px card / 50% icon · Control height: 48px hero, 38px nav
- Focus: not captured · Hover: not captured · Transition `background-color 0.15s cubic-bezier(0.3, 0, 0, 1)`

<spotify_design_language>
A pure-black #000000 stage for one enormous typographic gesture. The hero runs at 128px in SpotifyMixUITitleVariable at weight 900, left-aligned across three lines, with ONE WORD set in the oblique cut — the mixed roman/italic headline is the signature move. The variable face is worked across its full range: 900 heroes, 800 section headings at 64px, and deliberately light 300 sub-headings at 24 and 32px, with SpotifyMixUI carrying 16px body and 12px fine print in #B3B3B3. Line-height and tracking stay at normal at every size, including 128px. Surfaces step #000000 to #121212 to #222326 to #242424 with NO borders on panels — the only 1px border in the system is the #7F7F7F outline button — and shadows are rare because on black they read as glow rather than lift. Spotify Green #1ED760 (not the retired #1DB954) is used in exactly one role: the filled pill CTA. Every button is a 9999px pill at 16/700 with 8px 32px padding, 48px in the hero and 38px in the 72px black nav, alongside a transparent outline twin and rgba(255,255,255,.10) glass chips. Plan cards are flat #242424 with split 10px radii — 10px 10px 0 0 for a coloured header band drawn from the editorial palette (pink #FFD2D7, lilac #C4B1D4, periwinkle #576DD6, blue #0D72EA, olive #5F8008, violet #7358FF) and 0 0 10px 10px for the body. Atmosphere is full-bleed photography and video under a linear-gradient(rgba(0,0,0,0), rgba(0,0,0,0.75)) scrim; there is no WebGL, canvas, backdrop-filter or grain. Motion is background-color 0.15s on the house curve cubic-bezier(0.3, 0, 0, 1). Feels: bold, black-stage, editorial, music-loud. Avoid: the retired #1DB954 green, green as a link/heading/background colour, borders on panels, mid-weights where the system wants 300 or 900, editorial hues in chrome, and centering or tracking the display type.
</spotify_design_language>
