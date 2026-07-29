---
name: design-taste-frontend
description: Anti-slop frontend skill (Leonxlnx/taste-skill v2). Loaded into
  /app/.taste-skill/SKILL.md on 2026-02-25 for the Intercloud Portal project.
  Full text (verbatim, unabridged) from
  https://github.com/Leonxlnx/taste-skill/blob/main/skills/taste-skill/SKILL.md
---

# tasteskill: Anti-Slop Frontend Skill

> Landing pages, portfolios, and redesigns. Not dashboards, not data tables, not multi-step product UI.
> Every rule below is **contextual**. None of it fires automatically. First read the brief, then pull only what fits.

---

## 0. BRIEF INFERENCE (Read the Room Before Anything Else)
Before touching code or tweaking dials, **infer what the user actually wants**. Most LLM design output is bad because the model jumps to a default aesthetic instead of reading the room.

### 0.A Read these signals first
1. **Page kind** - landing / portfolio / redesign / editorial.
2. **Vibe words** ("minimalist", "Linear-style", "Awwwards", "brutalist", "premium consumer", "Apple-y", "playful", "serious B2B", "editorial", "agency-y", "glassy", "dark tech").
3. **Reference signals** - URLs, screenshots, competitor brands.
4. **Audience** - B2B panel vs design-conscious consumer vs recruiter.
5. **Brand assets that exist** - logo, color, type, photography.
6. **Quiet constraints** - a11y, public-sector, regulated, trust-first, kids.

### 0.B Output a one-line "Design Read" before generating
Before any code: *"Reading this as: <page kind> for <audience>, with a <vibe> language, leaning toward <stack + typographic direction>."*

### 0.C If the brief is ambiguous, ask ONE question, do not guess.
### 0.D Anti-Default Discipline
No AI-purple gradients, no centered hero over dark mesh, no three equal feature cards, no generic glassmorphism on everything, no infinite-loop micro-animations everywhere, no Inter + slate-900 by default.

---

## 1. THE THREE DIALS
Baseline: `DESIGN_VARIANCE 8 / MOTION_INTENSITY 6 / VISUAL_DENSITY 4`.

### 1.A Dial inference table
| Signal | VARIANCE | MOTION | DENSITY |
|---|---|---|---|
| minimalist / calm / Linear-style | 5-6 | 3-4 | 2-3 |
| premium consumer / Apple-y | 7-8 | 5-7 | 3-4 |
| playful / Awwwards | 9-10 | 8-10 | 3-4 |
| landing page (default) | 7-9 | 6-8 | 3-5 |
| trust-first / public-sector | 3-4 | 2-3 | 4-5 |
| redesign preserve | match | +1 | match |
| redesign overhaul | +2 | +2 | match |

### 1.B Use-case presets
| Use case | V | M | D |
|---|---|---|---|
| Landing SaaS mainstream | 7 | 6 | 4 |
| Landing agency/creative | 9 | 8 | 3 |
| Landing premium consumer | 7 | 6 | 3 |
| Portfolio designer | 8 | 7 | 3 |
| Portfolio developer | 6 | 5 | 4 |
| Editorial / Blog | 6 | 4 | 3 |
| Public-sector | 3 | 2 | 5 |

Variables are exact: DESIGN_VARIANCE / MOTION_INTENSITY / VISUAL_DENSITY. Never alias.

---

## 2. BRIEF → DESIGN SYSTEM MAP

### 2.A Official packages (when applicable)
- Microsoft/enterprise SaaS → @fluentui/react-components
- Google/Material product → @material/web + M3 tokens
- IBM/analytics → @carbon/react
- Shopify apps → polaris.js
- Atlassian/Jira → @atlaskit/*
- GitHub devtool → @primer/css or @primer/react-brand
- UK public-sector → govuk-frontend
- US public-sector → uswds
- Local-business MVP → Bootstrap 5.3
- Modern accessible React → @radix-ui/themes
- Own-your-code SaaS → shadcn/ui (npx shadcn@latest add)
- Tailwind indie/AI → Tailwind v4 + dark: variant

Honesty rule: reach for the OFFICIAL package. One system per project.

### 2.B When the brief is an aesthetic, not a system
Glassmorphism, Bento, Brutalism, Editorial, Dark tech, Aurora, Kinetic type, Apple-Liquid-Glass approximation → native CSS + Tailwind + maintained component library. Label as approximation.

---

## 3. DEFAULT ARCHITECTURE & CONVENTIONS

### 3.A Stack
- React or Next.js. Default Server Components (RSC).
- RSC safety: global state only in Client Components. Wrap providers in `'use client'`.
- Interactivity isolation: any Motion / scroll listener / pointer physics = isolated leaf with `'use client'` at top.
- Styling: Tailwind v4 (default). For v4, do NOT use `tailwindcss` in postcss.config.js; use `@tailwindcss/postcss` or the Vite plugin.
- Animation: Motion (`import { motion } from 'motion/react'`). `framer-motion` still works as legacy alias.
- Fonts: `next/font` or self-host with `@font-face` + `font-display: swap`. No Google Fonts `<link>` in production.

### 3.B State
- Local `useState`/`useReducer` for isolated UI.
- Global state ONLY to avoid deep prop drilling — Zustand/Jotai/Context.
- **Never** `useState` for continuous input (mouse position, scroll progress, magnetic hover). Use Motion's `useMotionValue`/`useTransform`/`useScroll`.

### 3.C Icons
- Allowed (priority): @phosphor-icons/react, hugeicons-react, @radix-ui/react-icons, @tabler/icons-react.
- Discouraged: lucide-react (only if user asks or project already depends).
- **Never hand-roll SVG icons.** If missing, install a second library.
- One family per project. Standardize `strokeWidth` globally (e.g. 1.5 or 2.0).

### 3.D Emoji Policy
Discouraged by default. Use icon-library glyphs. Override only when user asks for playful/chat/social vibe.

### 3.E Responsiveness & Layout Mechanics
- Breakpoints: sm 640 / md 768 / lg 1024 / xl 1280 / 2xl 1536.
- Contain layouts: `max-w-[1400px] mx-auto` or `max-w-7xl`.
- Viewport stability: NEVER `h-screen` for Hero. ALWAYS `min-h-[100dvh]`.
- Grid over flex-math: NEVER `w-[calc(33%-1rem)]`. ALWAYS `grid grid-cols-1 md:grid-cols-3 gap-6`.

### 3.F Dependency verification
Before importing ANY 3rd-party lib, check package.json. Output install command first if missing.

---

## 4. DESIGN ENGINEERING DIRECTIVES

### 4.1 Typography
- Display default: `text-4xl md:text-6xl tracking-tighter leading-none`.
- Body: `text-base text-gray-600 leading-relaxed max-w-[65ch]`.
- Sans: Discouraged default = Inter. Pick Geist / Outfit / Cabinet Grotesk / Satoshi first. Inter allowed only for neutral/Linear-style/public-sector.
- **Serif discipline** (very discouraged default). Only when brief literally names a serif OR aesthetic is genuinely editorial/luxury/publication/manuscript/heritage AND you can articulate why.
- Emphasis rule: italic/bold in the SAME font, never inject random serif into sans headline.
- **Banned defaults**: Fraunces, Instrument_Serif.
- If serif justified, rotate: PP Editorial New, GT Sectra Display, Cardinal Grotesque, Reckless Neue, Tiempos Headline, Recoleta, Cormorant Garamond, Playfair Display, EB Garamond, IvyPresto, Migra, Editorial Old, Saol Display, Söhne Breit Kursiv, Domaine Display, Canela, Schnyder, Tobias, NB Architekt, ITC Galliard.
- **Italic descender clearance**: italic display word with y/g/j/p/q needs `leading-[1.1]` min + `pb-1`/`mb-1`.

### 4.2 Color Calibration
- Max 1 accent color. Saturation < 80% default.
- **LILA RULE**: AI Purple / Blue glow discouraged. Neutral bases (Zinc/Slate/Stone) + high-contrast singular accents (Emerald, Electric Blue, Deep Rose, Burnt Orange).
- One palette per project.
- **Color Consistency Lock**: one accent locked page-wide.
- **Premium-consumer palette ban**: warm beige/cream + brass/clay/oxblood/ochre + espresso is BANNED as default reach. Rotate: Cold Luxury / Forest / Black+Tan / Cobalt+Cream / Terracotta+Slate / Olive+Brick+Paper / pure mono + single pop.

### 4.3 Layout Diversification
- Anti-center bias: no centered hero when DESIGN_VARIANCE > 4. Force Split, Asymmetric, or scroll-pinned.
- Override: centered OK for editorial/manifesto/launch briefs.

### 4.4 Materiality, Shadows, Cards
- Cards only when elevation communicates real hierarchy. Otherwise `border-t`, `divide-y`, or negative space.
- Shadow tinted to bg hue. No pure-black drop shadows on light.
- Density > 7: no generic card containers.
- **Shape Consistency Lock**: one corner-radius scale — all-sharp OR all-soft (12-16px) OR all-pill.

### 4.5 Interactive UI States
- Loading: skeletal matching final shape. No generic spinners.
- Empty: composed, indicates how to populate.
- Error: clear, inline for forms, toasts only for transient.
- Tactile: `:active` → `-translate-y-[1px]` or `scale-[0.98]`.
- **Button Contrast Check**: WCAG AA 4.5:1 body / 3:1 large text ≥18px. Ghost buttons on photos need backdrop/scrim/stroke.
- **CTA button wrap ban**: label ≤ 1 line at desktop; shorten (≤3 words primary CTA) or widen.
- **No Duplicate CTA Intent**: "Get in touch" + "Let's talk" + "Contact us" = same intent → pick ONE label page-wide.
- **Form Contrast Check**: inputs/placeholders/focus/labels all pass WCAG AA.

### 4.6 Data & Form Patterns
- Label ABOVE input. Helper text present. Error text BELOW. `gap-2`.
- No placeholder-as-label. Ever.

### 4.7 Layout Discipline (Hard Rules)
- **Hero fits initial viewport.** Headline ≤ 2 lines desktop, subtext ≤ 20 words AND ≤ 3-4 lines, CTAs visible without scroll.
- **Hero font-scale discipline.** Default `text-4xl md:text-5xl lg:text-6xl`. `text-6xl md:text-7xl` only for 3-5 word headlines.
- **Hero top padding cap**: max `pt-24` at desktop.
- **Hero stack max 4 text elements**: (eyebrow OR brand strip) + headline + subtext + CTAs (1 primary + ≤1 secondary). Banned in hero: tiny tagline below CTAs, trust micro-strip, pricing teaser, feature bullets, avatar row.
- "Trusted by" logo wall lives UNDER hero, not inside.
- Navigation ONE line at desktop, height ≤ 80px (default 64-72px).
- Bento with rhythm; bento cell count == item count exactly.
- Section-Layout-Repetition Ban: any layout family max once per page. 8 sections → ≥ 4 different families.
- **Zigzag alternation cap**: max 2 consecutive image+text-splits; 3rd = Pre-Flight Fail.
- **Eyebrow restraint**: max 1 eyebrow per 3 sections (hero counts as 1). Mechanical count of `uppercase tracking` labels.
- **Split-Header Ban**: "left big headline + right small explainer paragraph" banned as default. Stack vertically.
- **Bento background diversity**: ≥ 2-3 cells with real visual variation.
- Mobile collapse explicit per section (`< 768px`).

### 4.8 Image & Visual Asset Strategy
Priority: (1) image-generation tool first, (2) real web images (`https://picsum.photos/seed/{descriptive}/{w}/{h}`, real stock/brand URLs, Unsplash/Pexels), (3) last resort labeled `<placeholder>` slots and tell the user.
- Even minimalist sites need real images (≥ 2-3).
- Real SVG logos via Simple Icons (`https://cdn.simpleicons.org/{slug}/ffffff`) or devicon. Made-up brand → generate simple monogram SVG.
- **Logo-only rule**: logo wall = logos only, NO industry/category labels beneath.
- Hand-rolled decorative SVGs strongly discouraged (only single geometric marks + brief-mandated).
- **Div-based fake screenshots BANNED.**
- Hero needs a real visual.

### 4.9 Content Density
- Section shape: headline ≤ 8 words + subtext ≤ 25 words + one visual OR one CTA.
- No data-dump sections. Long lists → different UI (2-col split, card grid, tabs/accordion, scroll-snap pills, carousel, marquee).
- Spec sheets specifically: 2-col card grid / scroll-snap pills / grouped chunks / featured-vs-rest disclosure.
- **Copy self-audit** before ship: re-read every visible string; rewrite grammatically broken / hallucinated / cute-but-wrong copy.
- Fake-precise numbers flagged unless real data or mock-labeled.
- One copy register per page.

### 4.10 Quotes & Testimonials
- Max 3 lines of quote body.
- No em-dashes inside quotes (see 9.G).
- Attribution: name + role + optional company. Never name only.
- Typographic quotes " " or none. Not straight ASCII " ".

### 4.11 Page Theme Lock
- ONE theme per page (light, dark, or auto). No section flips.
- Exception: deliberate "Color Block Story" / "Theme Switch on Scroll" once per page.
- Set theme ONCE in layout.tsx / page root when using theming system.

---

## 5. CONTEXT-AWARE PROACTIVITY (tools, not defaults)
- Liquid Glass / Glassmorphism: premium consumer / Apple-adjacent / luxury / media-overlay. Inner border `border-white/10` + inner shadow `shadow-[inset_0_1px_0_rgba(255,255,255,0.1)]`. Solid-fill fallback for `prefers-reduced-transparency`.
- Magnetic micro-physics: MOTION > 5 + premium/playful/agency. Motion's `useMotionValue`/`useTransform`, NEVER `useState`.
- Perpetual micro-interactions: MOTION > 5 + section benefits from motion. Spring physics (`type:"spring", stiffness:100, damping:20`).
- **Motion claimed = motion shown**: MOTION > 4 requires actual motion (entry transitions, scroll-reveal, hover physics). Otherwise drop dial to 3.
- **Motion must be motivated**: articulate purpose (hierarchy / storytelling / feedback / state transition) in one sentence.
- **Marquee max one per page**.

### 5.A Canonical GSAP sticky-stack skeleton, and 5.B horizontal-pan skeleton, 5.C scroll-reveal — see full source at github.com/Leonxlnx/taste-skill/blob/main/skills/taste-skill/SKILL.md when needed.

---

## 6-7. (See source repo — dashboard density, sections 6/7 focus on specialized use cases.)

---

## 8. DARK MODE PROTOCOL
- Tailwind `dark:` variant OR CSS variables (shadcn/Radix). Pick one.
- Enforce: contrast (WCAG AA body / AAA hero), hierarchy parity, brand fidelity, NO pure #000000/#ffffff (use off-black/off-white).
- Respect `prefers-color-scheme` unless brand insists; add manual toggle if either mode loses brand.
- Test in BOTH modes before finishing.

---

## 9. AI TELLS (Forbidden Patterns)

### 9.A Visual & CSS
- NO neon/outer glows default.
- NO pure black `#000000` (off-black/zinc-950).
- NO oversaturated accents.
- NO excessive gradient text on large headers.
- NO custom mouse cursors.

### 9.B Typography
- AVOID Inter as default.
- NO oversized H1s that scream.
- Serif for editorial/luxury/publication only.

### 9.C Layout & Spacing
- Mathematically perfect padding banned.
- NO 3-column equal feature cards. Use 2-col zig-zag / asymmetric / scroll-pinned / horizontal scroll.

### 9.D Content ("Jane Doe" effect)
- NO generic names (John Doe, Sarah Chan). Use realistic, locale-appropriate.
- NO generic egg avatars.
- NO fake-perfect numbers (99.99%, 50%, 1234567). Use organic messy (47.2%, +1 312 847-1928).
- NO startup-slop names (Acme, Nexus, SmartFlow, Cloudly).
- NO filler verbs (Elevate, Seamless, Unleash, Next-Gen, Revolutionize).

### 9.E Resources
- NO hand-rolled SVG icons.
- NO div-based fake screenshots.
- NO broken Unsplash. Use picsum-seed or generated.
- shadcn/ui NEVER in default state — customize.

### 9.F Production-Test Tells (hard bans)
- NO version labels in hero (V0.6, BETA, INVITE-ONLY) unless launch brief.
- NO "Brand · No. 01" sub-eyebrows.
- NO section-number eyebrows (`00 / INDEX`, `001 · Capabilities`).
- NO `01 / 4` pagination on images/bento tiles.
- NO `Scroll · 001 Capabilities` scroll cues.
- NO "Index of Work, 2018-2026" range labels.
- Middle-dot `·` rationed (max 1 per line).
- NO decorative colored status dots.
- NO `<br>`-broken italicized headlines as default.
- NO vertical rotated text (agency cliché).
- NO crosshair/hairline grid decoration.
- NO div-based fake product UI in hero.
- NO fake version footers ("v0.6.2-rc.1").
- NO "Quietly in use at" social-proof headers.
- NO "From the field / Field notes / Currently on the bench" poetic labels.
- NO "We respect the French ones" mock-humble copy.
- NO weather/locale strips ("LIS 14:23 · 18°C") unless global studio brief.
- NO micro-meta sentences under eyebrows.
- NO generic step labels ("Stage 1 / Stage 2", "Phase 01").
- NO pills/labels overlaid on images.
- NO photo-credit captions as decoration.
- NO version footers on marketing pages.
- NO "Reservation 412 of 800" live counters unless real limited-run.
- NO decoration text strip at hero bottom (`BRAND. MOTION. SPATIAL.`).
- NO floating top-right sub-text in section headings.
- NO `border-t + border-b` on every row of long list/spec table.
- NO scoring/progress bars with filled bg tracks as landing decoration.
- Locale/city/time/weather strips banned 99% of briefs.
- Scroll cues banned (`Scroll`, `↓ scroll`, `Scroll to explore`).
- Zero decorative status dots default.

### 9.G EM-DASH BAN (single most-violated Tell)
**Em-dash `—` COMPLETELY BANNED** page-wide. No headlines, no eyebrows, no pills, no body, no quotes, no attribution, no captions, no buttons, no alt text. En-dash `–` also banned as separator. Only permitted: regular hyphen `-`, minus sign in math. If output contains a single `—` or `–` visible to user, output fails.

---

## 10. REFERENCE VOCABULARY (pattern names)
Hero: Asymmetric Split / Editorial Manifesto / Video Mask / Kinetic-Type / Curtain-Reveal / Scroll-Pinned.
Nav: Mac OS Dock Magnification / Magnetic Button / Gooey Menu / Dynamic Island / Radial / Speed Dial / Mega Menu.
Layout: Bento Grid / Masonry / Chroma Grid / Split-Screen Scroll / Sticky-Stack.
Cards: Parallax Tilt / Spotlight Border / Glassmorphism Panel / Holographic Foil / Tinder Swipe Stack / Morphing Modal.
Scroll: Sticky Stack / Horizontal Hijack / Locomotive Sequence / Zoom Parallax / Scroll Progress Path / Liquid Swipe.
Gallery: Dome / Coverflow / Drag-to-Pan / Accordion Slider / Hover Trail / Glitch.
Type: Kinetic Marquee / Text Mask Reveal / Scramble Effect / Circular Path / Gradient Stroke / Kinetic Type Grid.
Micro: Particle Explosion / Liquid Pull-to-Refresh / Skeleton Shimmer / Directional Hover / Ripple Click / SVG Line Drawing / Mesh Gradient / Lens Blur Depth.
Animation library: Motion (motion/react) default; GSAP+ScrollTrigger for scrolltelling; Three.js/WebGL for canvas/3D. NEVER mix GSAP/Three with Motion in the same tree.

---

## 11. REDESIGN PROTOCOL
### 11.A Detect mode: Greenfield / Preserve / Overhaul. Ask ONCE if ambiguous.
### 11.B Audit first: brand tokens, IA, content blocks, patterns preserve/retire, dial reading of existing, SEO baseline.
### 11.C Preserve: IA, brand color override (LILA rule respects existing purple), copy voice, a11y wins, analytics event names.
### 11.D Modernisation levers priority: typography → spacing → color recalibration → motion → hero/key-section recomposition → block replacement.
### 11.E Decision tree: sound IA/content/SEO → targeted evolution (70% value / 40% risk). Structural debt → full redesign + strict content preservation. Brand changing → greenfield.
### 11.F Never change silently: URL structure, nav labels, form field names/order, brand logo, legal/consent copy.

---

## 12. BLOCK LIBRARY (contract)
Schema: `skills/taste-skill/blocks/{category}/{name}.md` with frontmatter (name, category, dial_compatibility, when_to_use, not_for, stack) + body (visual sketch, Props API, code sketch, mobile fallback, motion variants per dial band, dark-mode notes, anti-patterns, references).

---

## 13. OUT OF SCOPE
This skill is NOT for: dashboards / dense product UI / admin panels (use Fluent, Carbon, Atlassian, Polaris) / data tables (TanStack / AG Grid) / multi-step forms / code editors (Monaco, CodeMirror) / native mobile (HIG, Material) / realtime collab UIs.

---

## 14. FINAL PRE-FLIGHT CHECK (mandatory)

- [ ] Design read one-liner declared.
- [ ] Dial values explicit and reasoned.
- [ ] Design system chosen or aesthetic labeled honestly.
- [ ] Redesign mode + audit if applicable.
- [ ] ZERO em-dashes anywhere.
- [ ] Page Theme Lock: one theme.
- [ ] Color Consistency Lock: one accent.
- [ ] Shape Consistency Lock: one radius system.
- [ ] Button Contrast Check WCAG AA.
- [ ] No CTA wrap at desktop.
- [ ] Form Contrast Check.
- [ ] Serif discipline (no Fraunces/Instrument_Serif default).
- [ ] Premium-consumer palette check.
- [ ] Italic descender clearance.
- [ ] Hero fits viewport (≤ 2 lines headline / ≤ 20 words subtext / CTA visible).
- [ ] Hero top padding ≤ pt-24.
- [ ] Hero stack ≤ 4 text elements.
- [ ] Eyebrow count ≤ ceil(sectionCount / 3).
- [ ] Split-Header banned.
- [ ] Zigzag alternation cap (max 2 consecutive).
- [ ] No Duplicate CTA Intent.
- [ ] Logo wall = logo only.
- [ ] Bento background diversity ≥ 2-3 varied cells.
- [ ] Logo wall UNDER hero, real SVG logos.
- [ ] Copy Self-Audit passed.
- [ ] Motion motivated (each animation justified).
- [ ] Marquee max one per page.
- [ ] Nav ONE line, ≤ 80px.
- [ ] Section layout repetition check ≥ 4 families across 8 sections.
- [ ] Bento cell count == item count exactly.
- [ ] Long lists use right UI component.
- [ ] Real images (gen tool / picsum-seed / labeled slots) — no div-fake, no hand SVG, no pure-text minimalism.
- [ ] No image pill overlays.
- [ ] No decorative photo credits.
- [ ] No marketing version footers.
- [ ] No micro-meta sentences under eyebrows.
- [ ] No hero-bottom decoration strip.
- [ ] No floating top-right section header sub-text.
- [ ] No progress bar bg tracks as landing decoration.
- [ ] No locale / city / time / weather strips.
- [ ] No scroll cues.
- [ ] No hero version labels unless launch.
- [ ] No section-number eyebrows.
- [ ] No decorative status dots.
- [ ] No border-t+border-b every-row spec tables.
- [ ] Content density sane (no 20-row tables, ≤ 25-word subs default).
- [ ] Quotes ≤ 3 lines, clean attribution (no em-dash).
- [ ] Motion claimed = motion shown.
- [ ] GSAP sticky-stack / horizontal-pan follows canonical skeleton.
- [ ] No `window.addEventListener('scroll')` — use Motion useScroll / ScrollTrigger / IntersectionObserver / CSS scroll-driven only.
- [ ] Reduced motion wrapped for MOTION > 3.
- [ ] Dark mode tokens tested in both modes.
- [ ] Mobile collapse explicit.
- [ ] Viewport stability `min-h-[100dvh]`.
- [ ] `useEffect` animations have strict cleanup.
- [ ] Empty / loading / error states provided.
- [ ] Cards omitted in favor of spacing where possible.
- [ ] Icons from allowed library only, no hand SVG.
- [ ] Motion isolated in `'use client'` leaf components, memoized.
- [ ] No AI Tells (Inter default, AI-purple, three equal cards, Jane Doe, Acme, "Quietly in use at").
- [ ] Core Web Vitals plausibly hit (LCP < 2.5s, INP < 200ms, CLS < 0.1).
- [ ] One design system per project.

**If any box cannot honestly be ticked, the page is not done.**

---

## APPENDICES
Install commands, canonical docs, and Apple Liquid Glass honest web approximation — see:
- https://github.com/Leonxlnx/taste-skill/blob/main/skills/taste-skill/SKILL.md
- Appendix A: install commands (Material Web, Fluent UI, Carbon, Radix, shadcn, Primer, GOV.UK, USWDS, Atlassian, Bootstrap, Polaris).
- Appendix B: canonical source doc URLs per system.
- Appendix C: `liquid-glass-web-approx` CSS skeleton with `prefers-reduced-transparency` fallback.

---

# Project note (Intercloud Portal, this repo)
- Portal `/portal/admin/*` = dense admin dashboard → **OUT OF SCOPE for this skill** per Section 13. Keep current shadcn/ui + Tailwind stack.
- Landing (`/`), articles (`/articles/<slug>`), status (`/status`), portal login = IN SCOPE. Apply this skill on those pages.
- Design read baseline for landing: "B2B ISP + Data-Center trust-first landing" → DESIGN_VARIANCE 5-6, MOTION 3-4, DENSITY 3-4. Serif discouraged (not editorial). Palette: navy `#0a2350` + kuning aksen `#f5b120` already locked — respect Color Consistency Lock. No em-dashes anywhere going forward.
