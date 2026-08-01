---
name: theme-factory
description: Select and apply a consistent color and typography theme to presentations, documents, reports, spreadsheets, PDFs, and HTML artifacts. Use when a user asks to theme, restyle, brand, or visually unify an artifact, or wants theme options.
---

> Modified from the supplied Apache-2.0 skill for General Agent compatibility.

# Theme factory

Use the theme files in `themes/` as reusable palettes and font pairings. Keep the
artifact's content, structure, and format-specific skill requirements intact.

## Choose a theme

If the user names a theme, use it. Otherwise choose the closest theme from the
artifact's subject, audience, and desired tone. Ask the user only when the choice
would materially change the result and the brief gives no useful direction.

When the user wants to compare options, copy `theme-showcase.pdf` into the current
chat directory, give them the resulting workspace path, and wait for their choice.
Do not modify the showcase itself.

## Available themes

The following 10 themes are available, each showcased in `theme-showcase.pdf`:

1. **Ocean Depths** - Professional and calming maritime theme
2. **Sunset Boulevard** - Warm and vibrant sunset colors
3. **Forest Canopy** - Natural and grounded earth tones
4. **Modern Minimalist** - Clean and contemporary grayscale
5. **Golden Hour** - Rich and warm autumnal palette
6. **Arctic Frost** - Cool and crisp winter-inspired theme
7. **Desert Rose** - Soft and sophisticated dusty tones
8. **Tech Innovation** - Bold and modern tech aesthetic
9. **Botanical Garden** - Fresh and organic garden colors
10. **Midnight Galaxy** - Dramatic and cosmic deep tones

## Apply the theme

1. Read only the selected file in `themes/`.
2. Map its palette to semantic roles: background, surface, primary text,
   secondary text, primary accent, and optional highlight.
3. Check contrast and use font fallbacks available to the output format.
4. Apply the theme consistently without flattening existing hierarchy or
   overwriting user-specified branding.
5. Follow the relevant document, presentation, spreadsheet, PDF, or frontend
   skill for creation and verification.

If no preset fits, create a small custom theme in the working artifact or its
builder: give it a descriptive name, define 4-6 colors and header/body fonts,
verify contrast, and show the result for review. Do not add a new built-in theme
file unless the user explicitly asks to extend this skill.
