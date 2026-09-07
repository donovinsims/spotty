---
name: Obsidian Flux
colors:
  surface: '#131313'
  surface-dim: '#131313'
  surface-bright: '#3a3939'
  surface-container-lowest: '#0e0e0e'
  surface-container-low: '#1c1b1b'
  surface-container: '#201f1f'
  surface-container-high: '#2a2a2a'
  surface-container-highest: '#353534'
  on-surface: '#e5e2e1'
  on-surface-variant: '#bccbb9'
  inverse-surface: '#e5e2e1'
  inverse-on-surface: '#313030'
  outline: '#869585'
  outline-variant: '#3d4a3d'
  surface-tint: '#53e076'
  primary: '#53e076'
  on-primary: '#003914'
  primary-container: '#1db954'
  on-primary-container: '#004118'
  inverse-primary: '#006e2d'
  secondary: '#f5fff5'
  on-secondary: '#003920'
  secondary-container: '#00ffa3'
  on-secondary-container: '#007146'
  tertiary: '#c8c6c5'
  on-tertiary: '#313030'
  tertiary-container: '#a3a1a1'
  on-tertiary-container: '#383838'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#72fe8f'
  primary-fixed-dim: '#53e076'
  on-primary-fixed: '#002108'
  on-primary-fixed-variant: '#005320'
  secondary-fixed: '#52ffac'
  secondary-fixed-dim: '#00e290'
  on-secondary-fixed: '#002111'
  on-secondary-fixed-variant: '#005231'
  tertiary-fixed: '#e5e2e1'
  tertiary-fixed-dim: '#c8c6c5'
  on-tertiary-fixed: '#1c1b1b'
  on-tertiary-fixed-variant: '#474646'
  background: '#131313'
  on-background: '#e5e2e1'
  surface-variant: '#353534'
typography:
  display-lg:
    fontFamily: Inter
    fontSize: 48px
    fontWeight: '700'
    lineHeight: '1.1'
    letterSpacing: -0.04em
  headline-md:
    fontFamily: Inter
    fontSize: 32px
    fontWeight: '600'
    lineHeight: '1.2'
    letterSpacing: -0.02em
  headline-md-mobile:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: '1.2'
  reader-pane:
    fontFamily: JetBrains Mono
    fontSize: 18px
    fontWeight: '400'
    lineHeight: '1.6'
    letterSpacing: -0.01em
  body-ui:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: '1.5'
  label-caps:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: '700'
    lineHeight: '1'
    letterSpacing: 0.1em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  base: 8px
  container-margin: 40px
  gutter-lg: 32px
  sidebar-width: 280px
  reader-max-width: 800px
---

## Brand & Style

The design system is engineered for deep focus and high-velocity information processing. It targets power listeners, researchers, and content creators who require a premium, distraction-free environment. 

The aesthetic is **Futuristic High-Contrast**, blending the utility of a developer tool with the sleekness of a luxury media player. It utilizes a "Dark Mode First" philosophy where deep obsidian surfaces provide a void-like backdrop, allowing content to "pop" with neon vibrance. Key characteristics include:

- **Refined Modularism:** Every element exists within a clearly defined, purpose-driven container.
- **Atmospheric Depth:** Usage of glassmorphism for secondary navigation layers to maintain spatial awareness.
- **Kinetic Feedback:** Subtle micro-interactions and neon glows that signal AI-driven processing and real-time transcription status.

## Colors

The palette is anchored in **Deep Obsidian (#050505)** to maximize OLED efficiency and minimize eye strain. 

- **Primary Accent:** The iconic Spotify Green (#1DB954) is used for primary actions and brand recognition.
- **Neon Flux:** A secondary vibrant mint (#00FFA3) is introduced for transcription highlights and "active state" neon glows, creating a sense of 2026 technological advancement.
- **Glass Surfaces:** Semi-transparent layers use a blur-heavy black (rgba(0,0,0,0.4)) with a 1px stroke of #FFFFFF (10% opacity) to define edges.
- **High-Contrast Text:** Pure White (#FFFFFF) is reserved for critical reading content, while muted grays handle metadata.

## Typography

This design system employs a dual-font strategy:
1. **Inter:** Used for all structural UI elements, buttons, and navigation. It provides a neutral, highly legible framework.
2. **JetBrains Mono:** Used exclusively for the transcription reader pane and code-like metadata. The monospaced nature helps users track words with precision during high-speed playback.

**Hierarchy Rules:**
- Large display text uses tight letter-spacing for a modern, "compact" editorial look.
- The reader pane uses generous line-height (1.6) to prevent fatigue during long-form reading.
- Labels and timestamps use JetBrains Mono in uppercase to distinguish technical data from narrative content.

## Layout & Spacing

The layout is a **Hybrid Modular Grid**. It features a fixed-width collapsible sidebar on the left and a fluid transcription pane centered in the viewport.

- **Desktop:** The transcription reader is constrained to a max-width of 800px to maintain optimal reading line lengths. 
- **The "Void" Philosophy:** Side margins are intentionally large (40px+) to create a focused "theatrical" center stage for the content.
- **Rhythm:** All spacing is based on an 8px baseline. Gutters between cards or modules are set to 32px to provide significant "breathable" room.
- **Mobile:** The sidebar collapses into a bottom-sheet navigation or a hamburger glass overlay. Margins reduce to 16px.

## Elevation & Depth

Hierarchy is achieved through **Luminance and Blur** rather than traditional drop shadows.

- **Level 0 (Base):** Deep Obsidian (#050505) background.
- **Level 1 (Modules):** Surface color #121212 with a 1px subtle border (#FFFFFF at 5% opacity).
- **Level 2 (Glassmorphism):** Floating sidebars and modals use a backdrop-filter (blur: 20px) and a semi-transparent black fill.
- **Interaction Highlights:** Active states (like a playing word in the transcript) use a "Neon Underglow"—a soft, primary-colored box-shadow (0px 0px 15px rgba(29, 185, 84, 0.3)).

## Shapes

The design system uses a **Rounded (8px-24px)** shape language to soften the high-contrast tech aesthetic.

- **Standard UI (Buttons/Inputs):** 8px (rounded-md) for a precise, modern feel.
- **Containers/Cards:** 16px (rounded-lg) to create a distinct modular look.
- **Sidebar/Full-Height Panels:** 24px (rounded-xl) on inner-facing corners to create a "nested" look within the viewport.
- **Pill Elements:** Search bars and status tags utilize fully rounded (capsule) ends for maximum organic flow.

## Components

### Buttons
- **Primary:** Spotify Green fill, black text, 8px radius. On hover, apply a neon green outer glow.
- **Secondary:** Ghost style. White 1px border, white text. Fill with 10% white on hover.

### Transcription Reader
- **Active Word:** White text with a mint-green underline and a subtle glow.
- **Inactive Text:** #A7A7A7 (60% opacity) to keep the focus on the current timestamp.

### Input Fields
- Dark grey (#1A1A1A) fill with no border. On focus, a 1px Spotify Green border appears with a subtle inner glow.

### Sidebar (Glassmorphic)
- 20px backdrop blur, 40% black opacity. Vertical navigation items use JetBrains Mono for a "terminal-lite" aesthetic.

### Progress Bars
- 4px height. The background is #333, and the active progress is a gradient from Spotify Green to Neon Mint.