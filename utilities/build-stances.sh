#!/bin/bash
# Build the Document of Stances / Cahier des positions and their 11 individual
# stance PDFs, writing straight into the git-tracked pdf/ folder that GitHub
# Pages serves.
#
# Usage:
#   utilities/build-stances.sh           # build both languages
#   utilities/build-stances.sh en        # English only
#   utilities/build-stances.sh fr        # French only
#   utilities/build-stances.sh en fr     # both (explicit)
#
# Outputs:
#   en -> pdf/Document of Stances.pdf   + pdf/stances/<Title>.pdf
#   fr -> pdf/Cahier des positions.pdf  + pdf/stances-fr/<Titre>.pdf
#
# Run from anywhere; paths are resolved relative to this script.
set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PDF_DIR="${REPO_ROOT}/pdf"

# Map a section basename (minus the NN- prefix) to its published title, per lang.
title_for() {
  local lang="$1" slug="$2"
  case "$lang" in
    en)
      case "$slug" in
        engineering-accreditation)   echo "Engineering Accreditation" ;;
        language-electives)          echo "Language Electives" ;;
        mental-health-workload)      echo "Mental Health and Student Workload" ;;
        quality-internships)         echo "Quality of Engineering Internships" ;;
        sustainability)              echo "Sustainability" ;;
        equity-diversity-inclusion)  echo "Equity, Diversity, and Inclusion" ;;
        iron-ring-ceremony)          echo "The Iron Ring Ceremony" ;;
        indigenous-education)        echo "Indigenous Education and Practices" ;;
        bilingualism)                echo "Bilingualism of Canadian Official Languages" ;;
        online-accessibility)        echo "Online Accessibility and Academic Accommodations" ;;
        experiential-learning)       echo "Experiential Learning in Engineering Education" ;;
        *)                           echo "" ;;
      esac ;;
    fr)
      case "$slug" in
        accreditation-ingenieurs)     echo "L'accréditation des ingénieurs" ;;
        cours-facultatifs-langues)    echo "Les cours facultatifs de langues" ;;
        sante-mentale-charge-travail) echo "La santé mentale et la charge de travail des étudiants" ;;
        qualite-stages)               echo "La qualité des stages en ingénierie" ;;
        developpement-durable)        echo "Le développement durable" ;;
        equite-diversite-inclusion)   echo "L'équité, la diversité et l'inclusion" ;;
        ceremonie-jonc)               echo "La cérémonie du jonc" ;;
        education-autochtones)        echo "L'éducation et les pratiques autochtones" ;;
        bilinguisme)                  echo "Le bilinguisme des langues officielles canadiennes" ;;
        accessibilite-en-ligne)       echo "L'accessibilité en ligne et les accommodations éducatifs" ;;
        apprentissage-pratique)       echo "L'apprentissage pratique en ingénierie" ;;
        *)                            echo "" ;;
      esac ;;
  esac
}

build_lang() {
  local lang="$1"
  local doc_dir combined_name stances_subdir combined_label
  case "$lang" in
    en)
      doc_dir="${REPO_ROOT}/documents/stances"
      combined_name="Document of Stances"
      stances_subdir="stances"
      combined_label="Document of Stances" ;;
    fr)
      doc_dir="${REPO_ROOT}/documents/stances-fr"
      combined_name="Cahier des positions"
      stances_subdir="stances-fr"
      combined_label="Cahier des positions" ;;
    *)
      echo "Unknown language '${lang}' (expected 'en' or 'fr')" >&2
      return 1 ;;
  esac

  if [ ! -f "${doc_dir}/main.tex" ]; then
    echo "Skipping ${lang}: ${doc_dir}/main.tex not found" >&2
    return 0
  fi

  local stance_pdf_dir="${PDF_DIR}/${stances_subdir}"
  mkdir -p "$stance_pdf_dir"

  cd "$doc_dir"
  local aux_dir="${doc_dir}/.build"
  mkdir -p "$aux_dir"

  echo "Building combined ${combined_label}..."
  latexmk -xelatex -synctex=1 -interaction=nonstopmode -file-line-error \
    --aux-directory="$aux_dir" main.tex >/dev/null
  # latexmk writes the PDF next to the source; aux/log clutter goes to .build/.
  cp "main.pdf" "${PDF_DIR}/${combined_name}.pdf"
  echo "  -> pdf/${combined_name}.pdf"

  # One PDF per stance section (skips 00-preamble/preambule and 01-nomenclature).
  local sec slug title wrapper
  for sec in sections/[0-1][0-9]-*.tex; do
    case "$sec" in
      sections/00-*|sections/01-*) continue ;;
    esac
    slug=$(basename "$sec" .tex | sed -E 's/^[0-9]+-//')
    title=$(title_for "$lang" "$slug")
    if [ -z "$title" ]; then
      echo "  Warning: no title mapping for ${slug}, skipping"
      continue
    fi
    echo "Building stance: ${title}..."
    # latexmk won't take a \def on the command line, so write a tiny wrapper.
    wrapper=".wrapper-${slug}.tex"
    printf '\\def\\stancefile{%s}\\input{standalone}\n' "${sec%.tex}" > "$wrapper"
    latexmk -xelatex -interaction=nonstopmode -file-line-error \
      --aux-directory="$aux_dir" -jobname="${slug}" "$wrapper" >/dev/null
    rm -f "$wrapper"
    cp "${slug}.pdf" "${stance_pdf_dir}/${title}.pdf"
    echo "  -> pdf/${stances_subdir}/${title}.pdf"
  done

  # Remove the intermediate PDFs left in the source dir (the published copies
  # live in pdf/; everything here is gitignored anyway).
  rm -f main.pdf
  for sec in sections/[0-1][0-9]-*.tex; do
    case "$sec" in sections/00-*|sections/01-*) continue ;; esac
    slug=$(basename "$sec" .tex | sed -E 's/^[0-9]+-//')
    rm -f "${slug}.pdf" "${slug}.synctex.gz"
  done
  rm -rf "$aux_dir"

  echo "${combined_label}: PDFs written to pdf/ and pdf/${stances_subdir}/"
}

# Default to both languages when no argument is given.
langs=("$@")
if [ ${#langs[@]} -eq 0 ]; then
  langs=(en fr)
fi

for lang in "${langs[@]}"; do
  build_lang "$lang"
done

echo "Done."
