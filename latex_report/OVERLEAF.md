# Overleaf — fix “\usepackage before \documentclass”

## What went wrong

In LaTeX, **every** root file must start with:

```latex
\documentclass[...]{...}
```

All `\usepackage{...}` must come **after** `\documentclass` and **before** `\begin{document}` (this block is called the *preamble*).

If `main.tex` starts with `% --- preamble` or `\usepackage{inputenc}` **without** `\documentclass` first, you get exactly:

> `LaTeX Error: \usepackage before \documentclass.`

So you probably pasted **`preamble.tex`** into **`main.tex`**, or overwrote `main.tex`.

---

## Correct layout (this project)

Upload **the whole folder** `latex_report/` into Overleaf (same structure):

```
latex_report/
  main.tex          ← ROOT: must contain \documentclass + \begin{document}
  preamble.tex      ← only \usepackage ... (no \documentclass here)
  front/
  chapters/
```

In Overleaf, set the **main document** to **`main.tex`** (Menu → Main document).

`main.tex` must begin like this (first lines):

```latex
\documentclass[12pt,a4paper,openany]{report}
\input{preamble}
...
\begin{document}
```

`preamble.tex` must **not** be compiled alone; it is only `\input` by `main.tex`.

---

## Quick fix in Overleaf

1. Open `main.tex`.
2. **Before** the first `\usepackage`, insert:

```latex
\documentclass[12pt,a4paper,openany]{report}
\input{preamble}
```

3. **Remove** from `main.tex` all the duplicate `\usepackage` lines that are already in `preamble.tex` (or delete everything and copy the real `main.tex` from this repo).

4. Ensure the file ends with `\end{document}` and that `\begin{document}` appears once after the preamble block.

---

## If you prefer a single file

Merge manually: copy the **entire** contents of `preamble.tex` **below** the `\documentclass` line in `main.tex`, then remove the line `\input{preamble}`. Do **not** put packages above `\documentclass`.
