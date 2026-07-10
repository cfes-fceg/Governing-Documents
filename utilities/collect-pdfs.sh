#!/usr/bin/env bash
# Collect all PDFs and rename them with their document titles

set -e

# Create output directory
mkdir -p pdf

echo "Collecting PDFs..."

# Function to get title for a document
get_title() {
  case "$1" in
    "bylaws")          echo "Bylaws" ;;
    "bylaws-fr")       echo "Les Statuts" ;;
    "constitution")    echo "Constitution" ;;
    "constitution-fr") echo "La Constitution" ;;
    "policies")        echo "Policy Manual" ;;
    "policies-fr")     echo "Le Manuel de politiques" ;;
    *)                 echo "" ;;
  esac
}

for doc_dir in documents/*/; do
  if [ -f "${doc_dir}main.pdf" ]; then
    doc_name=$(basename "$doc_dir")
    title=$(get_title "$doc_name")

    if [ -n "$title" ]; then
      echo "  ${doc_name}/main.pdf -> pdf/${title}.pdf"
      cp "${doc_dir}main.pdf" "pdf/${title}.pdf"
    else
      echo "  Warning: No title mapping for ${doc_name}, skipping"
    fi
  fi
done

# The Document of Stances / Cahier des positions also produce individual
# per-stance PDFs, handled by their own build script which writes straight
# into pdf/, pdf/stances/, and pdf/stances-fr/.
if [ -f utilities/build-stances.sh ]; then
  echo "Building stance PDFs..."
  bash utilities/build-stances.sh
fi

echo "PDFs collected in pdf/"
ls -la pdf/
