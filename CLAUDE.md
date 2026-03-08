# CFES Governance Repository

LaTeX documents for CFES governance (constitution, bylaws, policies, etc.) in English and French.

## Project Structure

- `documents/` - LaTeX source files, organized by document type and language (e.g., `constitution/`, `constitution-fr/`)
- `shared/styles/` - Common LaTeX style files
- `utilities/` - Build and formatting scripts
- `build/` - Generated output (PDFs, diffs)

## Formatting LaTeX Documents

Use `utilities/format.sh` to format `.tex` files. It runs `latexindent` with the config in `utilities/format.yaml`.

To format specific document directories (preferred over formatting everything):

```sh
find documents/constitution documents/constitution-fr -name "*.tex" -type f -exec latexindent -s -w -l utilities/format.yaml -c=build/ -m {} \;
```

To format all documents:

```sh
./utilities/format.sh
```

## Building PDFs

Build documents using `latexmk` from the document's directory. Use `-jobname` to set the output PDF filename.

```sh
cd documents/<doc> && latexmk -xelatex -synctex=1 -interaction=nonstopmode -file-line-error -output-directory=../../build -jobname="<output name>" main.tex
```

Example — building both constitution documents:

```sh
# English
cd documents/constitution && latexmk -xelatex -synctex=1 -interaction=nonstopmode -file-line-error -output-directory=../../build -jobname="[EN] Constitution - CESS 2026" main.tex

# French
cd documents/constitution-fr && latexmk -xelatex -synctex=1 -interaction=nonstopmode -file-line-error -output-directory=../../build -jobname="[FR] Constitution - SCIP 2026" main.tex
```

English and French documents can be built in parallel since they are independent.

## Generating Diffs

Use `utilities/latex-diff.sh` to generate a visual diff PDF between two versions of a document. Deleted text appears in red strikethrough, added text in green.

### Comparing against a git ref (preferred)

Use `--git-ref` to automatically extract the old version from a git ref. This handles the full directory extraction so `\input` references resolve correctly.

```sh
./utilities/latex-diff.sh documents/<doc>/main.tex --git-ref origin/main --output "<output name>"
```

Example — diffing both constitution documents against origin/main:

```sh
# English
./utilities/latex-diff.sh documents/constitution/main.tex --git-ref origin/main --output "[EN] Constitution Changes - CESS 2026"

# French
./utilities/latex-diff.sh documents/constitution-fr/main.tex --git-ref origin/main --output "[FR] Constitution Changes - SCIP 2026"
```

### Comparing two explicit files

```sh
./utilities/latex-diff.sh old.tex new.tex --output my-diff
```

Output goes to `build/<output name>.pdf`.

English and French documents can be diffed in parallel since they are independent.
