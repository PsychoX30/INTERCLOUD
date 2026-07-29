# Design Guidelines — Intercloud Portal

Loaded by the `taste-skill` (Leonxlnx/taste-skill v2) on 2026-02-25.
Full skill vendored at `/app/.taste-skill/SKILL.md`. This file is the
project-specific application of that skill.

---

## Scope split

| Surface | Scope |
|---|---|
| `/portal/admin/*` (dense admin dashboard) | **Out of scope** for taste-skill (Section 13). Keep existing shadcn/ui + Tailwind. |
| `/portal/*` (client dashboard) | Mixed — apply general rules (typography, contrast, dark mode, em-dash ban, motion motivated) but no landing-specific rules. |
| `/` (landing) | **In scope.** Full skill applies. |
| `/articles/<slug>`, `/status`, `/portal/login` | **In scope.** Full skill applies. |

## Design read for landing / articles

> **Reading this as: B2B ISP + Data-Center trust-first landing for
> Indonesian enterprise procurement panels + IT decision makers,
> with a serious-B2B / editorial-technical language, leaning toward
> Tailwind + shadcn/ui + Geist (or existing brand sans) + restrained motion.**

### Dials
- `DESIGN_VARIANCE: 5-6` (trust-first, not Awwwards)
- `MOTION_INTENSITY: 3-4` (hover + scroll-reveal, no scroll hijacks)
- `VISUAL_DENSITY: 3-4` (some data density for uptime/pricing, mostly spacious)

## Locked visual system (do not drift)

| Token | Value | Notes |
|---|---|---|
| Primary background | `#0a2350` (navy) | Existing brand — no override |
| Accent | `#f5b120` (kuning) | Color Consistency Lock (Section 4.2) — one accent page-wide |
| Off-black text | `#1a2233` | Never pure `#000000` |
| Neutral | Slate scale (`slate-50`…`slate-900`) | One neutral family |
| Radius | Existing shadcn defaults (soft, ~8-12px) | Shape Consistency Lock — pill only for interactive |
| Sans typeface | Existing system stack | Never Inter as default. Prefer Geist / Cabinet Grotesk / Satoshi when introducing new landing sections |
| Icons | `lucide-react` (existing dependency) | Skill discourages Lucide, but project already depends on it — override is honored. Do not mix families. |

## Non-negotiable rules for this project

1. **Zero em-dashes** (`—` and `–`) in ANY user-visible string — headlines,
   eyebrows, pills, body, quotes, buttons, alt text, PDF invoices, emails.
   Use regular hyphen `-` or restructure the sentence. This applies to
   backend-generated content too (email templates, PDF text, status
   labels). Audit before ship.
2. **One accent color** (`#f5b120`). No random blue CTA in section 7 of the
   landing.
3. **Hero fits viewport**: ≤ 2 lines headline, ≤ 20-word subtext, ≤ 4 text
   elements total, `pt-24` max top padding.
4. **No AI Tells** on landing: no section-number eyebrows
   (`01 · CAPABILITIES`), no locale strips (`Jakarta 14:23 · 32°C`), no
   scroll cues, no version footers, no photo-credit captions, no decoration
   text strips (`ISP · CLOUD · COLOCATION`).
5. **Real images only**. Use `image_selector_tool` for stock photos or
   `image_generation_tool` when user prefers custom. No div-based fake
   dashboards, no hand-rolled decorative SVGs.
6. **Motion motivated**. Every animation on landing/articles must have a
   one-sentence justification (hierarchy / storytelling / feedback / state
   transition). `MOTION_INTENSITY 3-4` means hover + scroll-reveal only —
   no GSAP scroll hijacks, no marquees, no magnetic buttons.
7. **Page Theme Lock**. Landing is light theme locked. Admin portal can
   remain light-locked too. No sections flip.
8. **Copy self-audit** before every landing ship: re-read every visible
   string, rewrite anything grammatically broken / AI-hallucinated / cute
   but wrong. Never ship a testimonial with placeholder attribution.
9. **CTA discipline**: primary CTA on landing is one label, reused in nav
   + hero + footer ("Konsultasi Gratis" or similar — pick ONE). No
   duplicate intent labels ("Hubungi Kami" + "Konsultasi" + "Mulai
   Sekarang" all on the same page = fail).
10. **Viewport stability**: `min-h-[100dvh]` for full-height sections,
    never `h-screen`.

## Preflight for landing / article changes

Run the Section 14 checklist in `/app/.taste-skill/SKILL.md` before
declaring landing work done. Focus on the ones flagged as **mandatory**:
em-dash ban, color/shape/theme locks, button contrast, hero discipline,
eyebrow restraint, zigzag cap, no image pill overlays, no photo credits,
copy self-audit, motion motivated.

## Admin portal exemption

For `/portal/admin/*` (dense dashboards, tables, forms), Section 13 of the
skill puts it OUT OF SCOPE. Continue using shadcn/ui as-is. General rules
that still apply everywhere:

- Em-dash ban (all surfaces including admin PDFs and email templates)
- WCAG AA contrast on buttons and forms
- No pure `#000000` / `#ffffff`
- Empty / loading / error states for all lists
- Icons from one family (lucide-react)
- No `useState` for continuous input (use Motion values)
- `min-h-[100dvh]` over `h-screen`
