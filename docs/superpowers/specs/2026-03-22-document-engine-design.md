# Document Engine — Design Spec

## Overview

The current system is good at generating resume and cover-letter content, but the
layout system is still too weak and too implicit. The model can produce useful
text, but the renderer is still mostly a template fill. That leaves too much
layout risk in the final output:

- cover letters can spill onto a second page
- resume density can vary too much across users
- styling choices are too static
- visual regressions are discovered after generation instead of being prevented
- the AI has no controlled way to influence document design beyond raw content

The goal of the document engine is to turn document generation into a deliberate,
deterministic pipeline:

1. the AI plans content
2. the AI selects from controlled design options
3. a deterministic compositor renders the document
4. a deterministic verifier checks layout constraints
5. a repair loop applies bounded fallback rules until the output is valid

This gives us variety without layout chaos.

## Product Direction

The service should not only generate strong content. It should generate complete,
visually intentional application documents with predictable quality.

That means:

- the AI should be able to choose a document theme and density intentionally
- the layout system must enforce page, spacing, and alignment constraints
- verification must be part of generation, not a manual afterthought
- the system should improve over time through reusable rules, regression fixtures,
  and visual review outputs

Long term, the document system should feel like its own specialized engine inside
the product, not a prompt that happens to end in a `.docx`.

## Core Principles

### 1. AI chooses, engine enforces

The model is allowed to choose from a controlled catalog:

- `theme_id`
- `layout_strategy`
- density level
- emphasis strategy
- section priority
- page budget

The model is not allowed to invent arbitrary visual structure or freeform layout
instructions. Layout must be produced by deterministic code.

### 2. Canonical layout must be deterministic

Given the same:

- `document_plan`
- `theme_id`
- user content
- page constraints

the engine must produce the same result every time.

### 3. No unsafe layout primitives

To minimize overlap and alignment bugs, the renderer should avoid:

- floating text boxes
- free-positioned shapes
- arbitrary element coordinates
- overlapping layers

Prefer stable primitives:

- paragraphs
- runs
- tables
- tab stops
- section margins
- bounded spacing rules

### 4. Verification is mandatory

Every generated document must pass automated checks before it is considered valid.

### 5. PDF is the visual truth

`DOCX` remains important as an editable export format, but the visual contract is
more reliable in `PDF`.

The engine should treat:

- `PDF` as the canonical visual output
- `DOCX` as the editable/export companion output

In the short term we can keep generating DOCX first, but the verification loop
must render to PDF for final checks.

## Scope

### In scope

- resume and cover-letter layout planning
- theme selection from a controlled catalog
- deterministic composition
- page-budget enforcement
- visual verification
- bounded repair rules
- reusable render/test tooling

### Out of scope for v1

- arbitrary custom user-designed themes
- full WYSIWYG editing
- multi-column magazine-style layouts
- graphics-heavy layouts that reduce ATS compatibility
- letting the model directly write Word formatting commands

## Current Implementation Status

The first production slice of the engine is now implemented in backend code.

Implemented now:

- deterministic `DocumentPlan` construction for `resume` and `cover_letter`
- approved theme catalog with:
  - `ats_minimal`
  - `classic_professional`
  - `technical_compact`
  - `executive_clean`
- deterministic `layout_strategy` support with:
  - `ats_safe`
  - `balanced`
  - `executive`
  - `compact`
- normalization and compaction rules for:
  - resume summary
  - resume skills
  - experience count and bullets
  - one-page cover-letter paragraph budgets
- heuristic verification metadata attached to each generated `DocumentPlan`
- bounded deterministic repair loop with observable repair history
- deterministic DOCX composition using safe flow-layout primitives
- local render verification tooling on macOS via LibreOffice -> PDF -> PNG
- named regression fixtures plus a local regression runner for fixture output generation
- backend contract that allows the model to select only approved `theme_id` values
- deterministic leadership-aware theme selection for balanced executive-style documents
- deterministic ATS-safe selection for simplicity-first roles and workflows
- theme-specific rendering differences that stay within safe flow-layout primitives

Not implemented yet:

- persisted intermediate layout model beyond the current plan payload
- backend-side rendered PDF/PNG verification during generation
- hard generation failure gates tied to rendered verification output
- canonical PDF-first rendering
- broader audited theme catalog and variants

This means the engine has moved from design-only into an initial controlled
production baseline. Planning, heuristic verification, and bounded repair are in
place; rendered verification and broader theme coverage are the next major phase.

## Engine Architecture

## Stage 0: Inputs

The engine starts from structured inputs:

- user profile memory
- job description / job analysis
- mode (`job_to_resume`, `find_jobs`)
- output request (`resume`, `cover_letter`, or both)
- optional user style preferences

## Stage 1: Content Planning

The model produces a structured `DocumentPlan`, not a final document.

Example responsibilities:

- choose the strongest experiences
- decide which bullets survive
- choose section order
- choose page budget
- assign priorities to sections
- assign target lengths

Example fields:

```json
{
  "doc_type": "resume",
  "page_budget": 1,
  "theme_candidates": ["executive_clean", "technical_compact"],
  "section_plans": [
    {
      "section_id": "summary",
      "priority": 100,
      "target_chars": 280
    },
    {
      "section_id": "experience",
      "priority": 100,
      "max_items": 3,
      "max_bullets_per_item": 2
    }
  ]
}
```

For cover letters, the planner should explicitly target:

- one page
- three concise body paragraphs
- one short closing paragraph

## Stage 2: Theme Selection

The model selects a theme from a finite catalog.

Theme choice should be based on:

- role type
- seniority
- user background
- job tone
- density requirements

But the available outputs are constrained to audited options, for example:

- `ats_minimal`
- `technical_compact`
- `executive_clean`
- `modern_minimal`
- `classic_professional`

Each theme has deterministic variants:

- `compact`
- `balanced`
- `spacious`

The model chooses from these; it does not invent a new theme in production.

When the exact theme should remain engine-controlled, the model can choose a
`layout_strategy` instead of a `theme_id`. For example:

- `ats_safe`
- `balanced`
- `executive`
- `compact`

The engine then resolves the concrete theme deterministically within that
strategy.

## Stage 3: Composition

The compositor turns a `DocumentPlan` into a deterministic intermediate layout
model and then into actual output files.

Suggested internal model:

```json
{
  "theme_id": "technical_compact",
  "page_size": "letter",
  "margins": { "top": 0.7, "right": 0.9, "bottom": 0.7, "left": 0.9 },
  "blocks": [
    { "type": "header_name", "content": "Avery Carter" },
    { "type": "header_title", "content": "Backend Engineer" },
    { "type": "section_heading", "content": "Summary" },
    { "type": "paragraph", "content": "..." }
  ]
}
```

This gives us a stable representation that can be rendered more than one way.

## Stage 4: Rendering

The engine should support multiple renderers over time:

### v1 renderer

- deterministic DOCX renderer
- PDF generated from DOCX and checked visually

### v2 target

- canonical PDF renderer
- DOCX companion renderer from the same layout model where possible

The important architectural point is this:

The content plan and the layout plan must be independent from the final file
format.

## Stage 5: Verification

Every generated document must be rendered and checked.

Verification inputs:

- produced PDF
- rendered page PNGs
- document metadata

Checks should include:

- page count within budget
- no unexpected blank pages
- no signature isolated on a new page
- no heading orphaned at page bottom
- no oversized whitespace gaps
- minimum font size respected
- section ordering valid
- visible content within margins

Short term verification can combine:

- deterministic metadata checks
- image-based checks
- targeted OCR/text checks when needed

## Stage 6: Repair Loop

If a document fails verification, the system should not immediately ask the user
to try again. It should apply bounded repair rules.

Examples:

- reduce summary target length
- reduce bullet count
- shorten the longest cover-letter paragraph
- switch to denser spacing variant
- switch to a denser compatible theme variant
- move low-priority content to page 2 only if allowed by page budget

The repair loop should be deterministic and observable. Every repair action should
be logged so we can learn which failures are common.

## Theme Catalog

The theme catalog should be data-driven, versioned, and audited.

Each theme should define:

- typography tokens
- color tokens
- spacing scale
- margins
- heading style
- section separators
- bullet style
- compact/balanced/spacious variants
- ATS-safety flags
- doc-type compatibility

Example:

```json
{
  "theme_id": "technical_compact",
  "supports": ["resume", "cover_letter"],
  "density_variants": ["compact", "balanced"],
  "tokens": {
    "body_font": "Calibri",
    "heading_color": "#4F81BD",
    "body_size_pt": 10.5,
    "heading_size_pt": 13,
    "line_spacing": 1.0
  }
}
```

Over time we can grow the catalog, but every new theme should pass the same
verification suite.

## Reliability Strategy

The engine must be tested with both synthetic and real-world fixtures.

### Fixture types

- short-entry resume
- dense senior resume
- academic-heavy resume
- job with weak user fit
- job with strong user fit
- short company name / long company name
- short title / long title
- remote / multi-location / location-heavy roles

### Regression assets

For each fixture:

- input JSON
- generated `DocumentPlan`
- chosen `theme_id`
- rendered PDF
- rendered PNG pages
- expected page count
- expected pass/fail status

This lets us visually compare engine behavior over time.

## Immediate Implementation Plan

### Phase 1: Stabilize the current pipeline

- keep current backend architecture
- add the render helper and visual review tooling
- tighten cover-letter compaction
- make one-page cover-letter output the default target

Status: in progress.

### Phase 2: Introduce `DocumentPlan`

- split generation into `content generation` and `layout planning`
- store structured planning artifacts
- stop treating `sections` as an unbounded freeform payload

### Phase 3: Introduce theme catalog

- create first audited themes
- let the model choose from a fixed theme set
- move spacing/margin choices out of prompts and into engine config

### Phase 4: Add verification + repair loop

- formalize layout checks
- retry with deterministic fallback rules
- record failure reasons

### Phase 5: Add visual regression suite

- script generation of fixture outputs
- render to PNG automatically
- review diffs over time

### Phase 6: Move toward canonical PDF

- treat PDF as the authoritative visual output
- keep DOCX as editable export where possible

## Acceptance Criteria

The engine is successful when:

- cover letters reliably stay on one page unless explicitly allowed otherwise
- resumes fit the declared page budget
- no overlapping or floating layout defects are possible in normal generation
- themes produce visibly distinct but still ATS-safe results
- visual verification is part of CI or a scripted local validation flow
- new themes can be added without rewriting the engine
- most layout failures are corrected automatically by bounded repair rules

## Current Decisions

- The current macOS render path should use LaunchServices (`open -a LibreOffice`)
  instead of calling the `soffice` binary directly.
- The repository should keep a local render script for repeatable visual checks.
- One-page cover letters are the default unless the user explicitly asks otherwise.
- The AI may choose a theme, but only from an approved catalog.
- Deterministic layout rules take priority over raw model verbosity.

## Next Steps

1. Add `DocumentPlan` models and persist them for generated docs.
2. Define the first theme catalog in code.
3. Refactor `generate_document` to consume a plan instead of unconstrained sections.
4. Add verification objects and failure reasons.
5. Create fixture-based visual regression scripts using the render helper.
