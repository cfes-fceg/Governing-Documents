#!/bin/bash
# Format all LaTeX files in the repository

# Find all .tex files in documents/ directory
find documents -name "*.tex" -type f -exec latexindent -s -w -l utilities/format.yaml -c=build/ -m {} \;

# Normalize headings: join multi-line titles, split \label onto its own line
find documents -name "*.tex" -type f -print0 | xargs -0 python3 utilities/normalize-headings.py

echo "Formatting complete"
