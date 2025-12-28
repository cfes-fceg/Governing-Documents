# Google Docs to LaTeX Conversion Guide

This guide provides step-by-step instructions for converting CFES governance documents from Google Docs to LaTeX format.

## Prerequisites

- **pandoc** - Document conversion tool
  - macOS: `brew install pandoc`
  - Linux: `sudo apt install pandoc`
  - Windows: Download from https://pandoc.org/installing.html

## Step-by-Step Process

### 1. Export from Google Docs

1. Open the Google Docs document
2. Click **File > Download > Microsoft Word (.docx)**
3. Save to the root of this repository (e.g., `[EN] CFES Document.docx`)

### 2. Convert with Pandoc

```bash
pandoc "[EN] CFES Document.docx" -o /tmp/document-raw.tex --wrap=none
```

This creates a raw LaTeX file with pandoc's default formatting.

### 3. Clean LaTeX Output

Apply these cleanup steps to the converted file:

**Remove quote environments:**
```bash
# Using sed (macOS/Linux)
sed -i '' '/^.*\\begin{quote}.*$/d' /tmp/document-raw.tex
sed -i '' '/^.*\\end{quote}.*$/d' /tmp/document-raw.tex
```

**Remove label definitions:**
```bash
sed -i '' '/^.*\\def\\labelenumi.*/d' /tmp/document-raw.tex
```

**Fix label formatting:**
- Find: `}\label{`
- Replace: `}\n\label{`

Or use your text editor's find-and-replace with regex enabled.

### 4. Create Document Structure

```bash
# Create document directory
mkdir -p documents/[document-name]/sections

# Create main files
touch documents/[document-name]/main.tex
touch documents/[document-name]/preamble.tex
touch documents/[document-name]/title_page.tex
```

### 5. Analyze and Split into Sections

1. **Read the converted content** to identify major sections
2. **Identify natural breaks** - Look for `\section{}` commands in the converted file
3. **Create section files** with numbered prefixes:
   ```
   sections/01-introduction.tex
   sections/02-governance.tex
   sections/03-membership.tex
   ...
   ```

### 6. Populate Section Files

For each section identified:

1. Copy the section content from `/tmp/document-raw.tex`
2. Paste into the appropriate `sections/XX-topic.tex` file
3. Clean up formatting:
   - Remove unnecessary `\def\labelenumi` commands
   - Ensure proper `\label{}` placement
   - Fix enumerate environments

**Example section file:**
```latex
\section{Article 1 - General}
\label{article-1---general}

\subsection{Name of the Corporation}
\label{name-of-corporation}

\begin{enumerate}
 \item The name shall be "Canadian Federation of Engineering Students".
\end{enumerate}
```

### 7. Create Title Page

Copy and customize from template:

```bash
cp shared/templates/template-titlepage.tex documents/[document-name]/title_page.tex
```

Edit `title_page.tex`:
- Replace `[DOCUMENT_TITLE]` with actual title (e.g., "Constitution", "Bylaws")
- Verify logo path points to `../../shared/assets/logos/CFES_Logo`

**Example:**
```latex
\begin{titlepage}
 \begin{center}
  {\Huge \textbf{Canadian Federation of Engineering Students}}
  \newline
  {\Huge Constitution}
  \vfill
  \includegraphics[width=0.5\linewidth]{../../shared/assets/logos/CFES_Logo}
  \vfill
  \bigfont{Fédération canadienne des étudiants en génie}
 \end{center}
\end{titlepage}
```

### 8. Create Preamble

Edit `preamble.tex` with document-specific information:

```latex
\section*{English Edition}

\textbf{REVISION DATE:} 01/01/2025

\textbf{REVISED BY:} CFES Board

\vfill
```

### 9. Create Main File

Create `documents/[document-name]/main.tex`:

```latex
\documentclass[12pt]{article}

% Load CFES common styles
\usepackage{../../shared/styles/cfes-common}
\usepackage{../../shared/styles/cfes-headers}
\usepackage{../../shared/styles/ninecolors}

\begin{document}

% Title page
\input{title_page}

% Preamble
\input{preamble}
\newpage

% Setup headers/footers
\setupcfesheaders{Document Name}

% Table of contents
\tableofcontents
\newpage

% Include all sections
\input{sections/01-introduction}
\input{sections/02-governance}
% ... add all section inputs

\end{document}
```

### 10. Build and Test

```bash
cd documents/[document-name]
latexmk -xelatex main.tex
```

Check the generated PDF in `../../build/main.pdf`.

**Common build issues:**
- **Missing logo**: Add CFES logo to `shared/assets/logos/`
- **Font not found**: Install Arial font
- **Undefined references**: Run build twice (latexmk does this automatically)

### 11. Format Code

From repository root:

```bash
./utilities/format.sh
```

This applies consistent indentation and formatting.

### 12. Commit Changes

```bash
git add documents/[document-name]
git commit -m "feat: Add [document-name] converted from Google Docs"
```

## Section Organization Best Practices

### Naming Conventions

- **Section files**: `01-topic.tex`, `02-topic.tex` (zero-padded numbers)
- **Labels**: `\label{article-1---general}` (lowercase with hyphens)
- **Subsections**: Group related subsections in subdirectories if needed

### File Size Guidelines

- **Optimal**: 50-200 lines per section file
- **Too small**: < 20 lines (consider combining)
- **Too large**: > 300 lines (consider splitting)

### Hierarchy Mapping

Google Docs heading levels → LaTeX commands:

- **Heading 1** → `\section{}`
- **Heading 2** → `\subsection{}`
- **Heading 3** → `\subsubsection{}`
- **Heading 4** → `\paragraph{}`
- **Numbered lists** → `\begin{enumerate}...\end{enumerate}`

## Customization for Different Document Types

### Constitution/Bylaws

- Numbered articles: `\section{Article 1 - Topic}`
- Formal structure with subsections
- Include revision date in preamble

### Policy Manual

- Sections by policy area
- May need more subsection nesting
- Consider creating subdirectories for complex policy groups

### Handbooks

- Chapter-based structure
- More casual tone
- May include more images/diagrams

## Tips and Tricks

### Handling Tables

Pandoc converts tables to LaTeX, but formatting may need adjustment:

```latex
% Simple table with tabularray
\begin{tblr}{colspec={ll}}
Header 1 & Header 2 \\
\hline
Cell 1 & Cell 2 \\
Cell 3 & Cell 4 \\
\end{tblr}
```

### Handling Images

1. Extract images from Word document (unzip .docx file)
2. Copy images to document-specific folder
3. Update `\includegraphics{}` paths

### Cross-References

Use `\ref{}` and `\label{}` for internal links:

```latex
See Article \ref{article-4---membership} for details.
```

### Special Characters

Common conversions:
- **Quotes**: `''text''` (two single quotes)
- **Em-dash**: `---`
- **Apostrophes**: `students'` works as-is

## Troubleshooting

### Conversion Issues

**Problem**: Nested lists not converting properly

**Solution**: Manually adjust enumerate nesting:
```latex
\begin{enumerate}
 \item First level
  \begin{enumerate}
   \item Second level
  \end{enumerate}
\end{enumerate}
```

**Problem**: Special characters appearing incorrectly

**Solution**: Use XeLaTeX-compatible Unicode or LaTeX commands:
- `é` works directly with XeLaTeX
- Or use `\'e` for compatibility

**Problem**: Table of contents numbers incorrect

**Solution**: Ensure all sections have `\label{}` commands and rebuild twice

## Advanced: Automated Conversion Script

For bulk conversions, create a script:

```bash
#!/bin/bash
# convert-doc.sh

DOCX_FILE=$1
DOC_NAME=$2

# Convert
pandoc "$DOCX_FILE" -o /tmp/${DOC_NAME}-raw.tex --wrap=none

# Clean
sed -i '' '/^.*\\begin{quote}.*$/d' /tmp/${DOC_NAME}-raw.tex
sed -i '' '/^.*\\end{quote}.*$/d' /tmp/${DOC_NAME}-raw.tex
sed -i '' '/^.*\\def\\labelenumi.*/d' /tmp/${DOC_NAME}-raw.tex

echo "Converted to /tmp/${DOC_NAME}-raw.tex"
echo "Next: split into sections manually"
```

Usage:
```bash
chmod +x convert-doc.sh
./convert-doc.sh "[EN] CFES Bylaws.docx" bylaws
```

## Quality Checklist

Before committing a converted document:

- [ ] All sections split into logical files
- [ ] Labels added to all sections/subsections
- [ ] Title page customized
- [ ] Preamble contains correct revision info
- [ ] Main.tex includes all section inputs
- [ ] Document builds without errors
- [ ] PDF output reviewed for formatting
- [ ] Code formatted with `./utilities/format.sh`
- [ ] Cross-references work correctly
- [ ] Table of contents generated properly

## Getting Help

- **LaTeX errors**: Check the `.log` file in `build/` directory
- **Formatting questions**: Review `shared/styles/cfes-common.sty`
- **Build issues**: See main [README.md](README.md) troubleshooting section

## References

- [Pandoc Documentation](https://pandoc.org/MANUAL.html)
- [LaTeX Wikibook](https://en.wikibooks.org/wiki/LaTeX)
- [XeLaTeX Documentation](https://www.overleaf.com/learn/latex/XeLaTeX)
