#!/bin/bash
# Format all LaTeX files in the repository

# Find all .tex files in documents/ directory
find documents -name "*.tex" -type f -exec latexindent -s -w -l utilities/format.yaml -c=build/ -m {} \;

echo "Formatting complete"
