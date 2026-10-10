Tournament Software - World Champs v8

Run on Windows: double-click START_TOURNAMENT.bat
URL: http://127.0.0.1:5069

V8 changes:
- collision-safe Tournament Draw layout with larger bracket typography
- A4-only Tournament Draw PDF with larger cards/type
- redesigned A4 Groups PDF (standings + matches side-by-side)
- redesigned A4 Schedule PDF with section bands instead of crossing rules
- README / Help page in the dashboard and tournament navigation
- existing Smart/Protected BYE, exact-placement and reseeding logic retained


## v9 additions
- Fixed creator credit displayed in the Dashboard, tournament view and every PDF page: `created by Michał Klimczak (klimczak.sc@gmail.com)`.
- New A4 Final Standings PDF export.


## v10 fixes
- Final Standings PDF now reports **FINAL** when all generated tournament matches are resolved, including BYEs.
- Exact placement inference now handles the terminal loser of odd-sized placement preliminaries (for example Places 9-11).
- The fixed creator credit renders the Polish letter **ł** without relying on external font files, eliminating the black missing-glyph square in PDFs.


## v11 footer fix
- PDF creator credit now uses a real system TrueType font with Polish glyph support (Arial/Segoe UI/Calibri on Windows; compatible system fallbacks elsewhere).
- The credit is right-aligned in the bottom-right corner of every PDF page.
- Tournament logo is positioned above the credit so footer elements do not overlap explanatory notes.
