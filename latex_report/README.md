# LaTeX report (UIR) — how to compile

From this folder:

```bash
cd /Users/info/Desktop/new_project/sonasid_project/latex_report
pdflatex -interaction=nonstopmode main.tex
pdflatex -interaction=nonstopmode main.tex
```

Requirements: a full TeX distribution (MacTeX, TeX Live, MiKTeX).

## Contents

- `main.tex` — master document
- `preamble.tex` — packages and layout
- `front/` — title page, dedication, acknowledgements, abstract, summary, abbreviations
- `chapters/` — Chapters 1–6 (English, aligned with your PDF structure)

## Completing the report

Your original PDF is ~65 pages. This LaTeX is a **structured, compilable base**: paste remaining paragraphs, figures (`figs/`), and bibliography entries from your Word/PDF export into the matching chapter files or add `\input{chapters/...}` fragments.

## Optional: figures directory

Create `latex_report/figs/` and use:

```latex
\begin{figure}[htbp]
  \centering
  \includegraphics[width=0.85\textwidth]{figs/architecture.pdf}
  \caption{System architecture overview.}
\end{figure}
```
