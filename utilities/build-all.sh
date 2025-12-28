#!/bin/bash
# Build all governance documents

set -e

for doc_dir in documents/*/; do
  if [ -f "${doc_dir}main.tex" ]; then
    doc_name=$(basename "$doc_dir")
    echo "Building ${doc_name}..."
    cd "$doc_dir"
    latexmk -xelatex -synctex=1 -interaction=nonstopmode -file-line-error --aux-directory=../../build main.tex
    cd ../..
    echo "${doc_name} built successfully"
  fi
done

echo "All documents built successfully"
