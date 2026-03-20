# Design System Document: Milan Transit Intelligence

## 1. Overview & Creative North Star
**Creative North Star: "The Urban Cartographer"**

This design system transcends the utility of a standard data dashboard to become a high-end editorial experience. Inspired by the precision of Swiss design and the tactile elegance of Italian luxury, "The Urban Cartographer" treats transit data not as rows of numbers, but as a living narrative of Milan’s movement.

To break the "template" look, we reject the rigid, boxed-in grid. We utilize **intentional asymmetry**, where large-scale typography anchors the layout, and data visualizations float within generous "breathing rooms" (whitespace). Elements should feel layered rather than placed, creating a sense of depth that mimics a physical map spread across a studio table.

---

## 2. Colors: Tonal Atmosphere
Our palette moves beyond simple blacks and whites to a sophisticated range of "warm neutrals" and "high-visibility" accents.

### The Palette
* **Primary (#9F4200):** The deep "Terra Cotta" of Milanese rooftops, used for high-authority actions.
* **Primary Container (#F67A32):** The signature "Tram Orange," utilized for data highlights and active states.
* **Surface / Background (#FBF9F8):** An off-white, gallery-style base that feels warmer and more premium than pure #FFFFFF.
* **Secondary (#5F5E5E):** A muted slate for metadata and auxiliary information.

### The "No-Line" Rule
**Explicit Instruction:** Prohibit the use of 1px solid borders for sectioning. Boundaries must be defined solely through background color shifts. To separate the "Sidebar" from the "Main Map," use a shift from `surface` to `surface-container-low`. Lines are architectural scars; color shifts are natural horizons.

### Signature Textures & Glass
To provide "visual soul," apply a subtle linear gradient to main CTAs (transitioning from `primary` to `primary-container`). For floating modals or navigation bars, use **Glassmorphism**:
* **Background:** `surface` at 70% opacity.
* **Backdrop-blur:** 20px.
* **Effect:** This allows the vibrant colors of the tram lines to bleed through the UI, making the interface feel integrated with the data.

---

## 3. Typography: Editorial Authority
We utilize a single, high-performance typeface family (Inter/-apple-system) but vary the scale dramatically to create an editorial hierarchy.

* **Display (Display-LG, 3.5rem):** Used for singular, heroic statistics (e.g., "98% On-Time"). This is the "hook" of the page.
* **Headline (Headline-MD, 1.75rem):** Used for tram line identifiers (e.g., "Linea 15: Rozzano").
* **Body (Body-LG, 1rem):** The workhorse for descriptions. Increased line-height (1.6) is mandatory to maintain the "premium" feel.
* **Label (Label-SM, 0.6875rem):** All-caps, tracked out (+0.05em) for technical metadata and axis labels on charts.

**The Contrast Rule:** Pair `Display-LG` (Light weight) with `Label-SM` (Bold weight) in close proximity to create a sophisticated, high-contrast tension that screams "Custom Design."

---

## 4. Elevation & Depth: Tonal Layering
Traditional shadows are often a crutch for poor layout. We define hierarchy through a "Stacking Principle."

### The Layering Principle
Treat the UI as physical sheets of fine paper:
1. **Level 0 (Base):** `surface` (#FBF9F8) - The "desk" everything sits on.
2. **Level 1 (Section):** `surface-container-low` (#F6F3F2) - Defines a large content area.
3. **Level 2 (Card):** `surface-container-lowest` (#FFFFFF) - Creates a subtle "lift" for interactive data cards.

### Ambient Shadows
If an element must float (e.g., a detail pop-over), use an **Ambient Shadow**:
* **Blur:** 40px - 60px.
* **Opacity:** 4% - 6%.
* **Color:** Use a tint of `on-surface` (#1B1C1C) rather than pure black to keep the shadow "airy."

### The Ghost Border
If accessibility requires a container boundary, use a **Ghost Border**: `outline-variant` at 15% opacity. It should be felt, not seen.

---

## 5. Components

### Buttons & Interaction
* **Primary Button:** `primary-container` background with `on-primary-container` text. Large corner radius (`xl`: 1.5rem) to mimic Apple’s rounded-rect aesthetic.
* **Secondary/Tertiary:** No background. Use `body-lg` weight typography with a `primary` color text. Use `spacing-2` for horizontal padding.

### Cards & Data Modules
* **Rule:** Forbid divider lines.
* **Execution:** Separate header and body within a card using `spacing-4` (1.4rem) of vertical whitespace. If sub-sections are needed, use a subtle shift to `surface-container-high` for the header background.

### Tram Status Chips
* **Design:** Pill-shaped (`full` roundedness).
* **Logic:** Use `primary-fixed` for active lines and `secondary-fixed-dim` for inactive. No bold colors; let the "Tram Orange" be the only vibrant element on the page.

### Signature Component: The "Line-Trace" Progress Bar
Specifically for Milan tram data, use a thin `px` height track of `outline-variant` with a `primary` glowing indicator. This mimics the actual rail lines on a map.

---

## 6. Do's and Don'ts

### Do:
* **DO** use asymmetric margins. A wider left-hand margin for a title creates a sophisticated, "magazine" feel.
* **DO** use `surface-bright` for hover states on cards to create a "glow" effect.
* **DO** prioritize high-quality photography of Milan (Duomo, Brera streets) as background elements behind glass-morphic containers.

### Don't:
* **DON'T** use 100% black (#000000). Use `on-surface` (#1B1C1C) to maintain a soft, premium look.
* **DON'T** use standard 8px grids. Use our custom **Spacing Scale** (e.g., `spacing-10` for section gaps) to ensure a sense of "luxury volume."
* **DON'T** crowd the data. If a chart feels tight, increase the container size or decrease the number of data points. White space is a functional requirement, not a decoration.
