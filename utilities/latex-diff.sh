#!/bin/bash
# Generate diff PDF between two LaTeX documents
#
# This script compares two versions of LaTeX documents and generates a visual
# diff with deleted text in red strikethrough and added text in green.
#
# Usage: latex-diff.sh OLD.tex NEW.tex [OPTIONS]
#
# Arguments:
#   OLD.tex          Path to the old version of the LaTeX file
#   NEW.tex          Path to the new version of the LaTeX file
#
# Options:
#   --output FILE    Output basename (default: diff)
#                    Files will be saved as FILE.tex and FILE.pdf
#   --keep-temp      Keep temporary files for debugging
#   --no-pdf         Generate only .tex file, skip PDF compilation
#   --help           Show this help message
#
# Examples:
#   # Basic usage - compare two versions of bylaws
#   ./utilities/latex-diff.sh documents/bylaws/main.tex documents/bylaws-v2/main.tex
#
#   # Custom output location
#   ./utilities/latex-diff.sh old.tex new.tex --output build/my-diff
#
#   # Keep temporary files for debugging
#   ./utilities/latex-diff.sh old.tex new.tex --keep-temp
#
#   # Generate only .tex without PDF compilation
#   ./utilities/latex-diff.sh old.tex new.tex --no-pdf

set -e  # Exit on error
set -u  # Exit on undefined variable

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
OUTPUT_BASE="diff"
KEEP_TEMP=0
NO_PDF=0
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OLD_FILE=""
NEW_FILE=""

# Function to print error message and exit
error() {
    echo -e "${RED}Error: $1${NC}" >&2
    exit 1
}

# Function to print info message
info() {
    echo -e "${BLUE}$1${NC}"
}

# Function to print success message
success() {
    echo -e "${GREEN}$1${NC}"
}

# Function to print warning message
warning() {
    echo -e "${YELLOW}$1${NC}"
}

# Function to show usage
usage() {
    sed -n '2,30p' "$0" | sed 's/^# \?//'
    exit 0
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --help|-h)
            usage
            ;;
        --output|-o)
            if [[ -z "${2:-}" ]]; then
                error "Option --output requires an argument"
            fi
            OUTPUT_BASE="$2"
            shift 2
            ;;
        --keep-temp)
            KEEP_TEMP=1
            shift
            ;;
        --no-pdf)
            NO_PDF=1
            shift
            ;;
        -*)
            error "Unknown option: $1"
            ;;
        *)
            if [[ -z "$OLD_FILE" ]]; then
                OLD_FILE="$1"
            elif [[ -z "$NEW_FILE" ]]; then
                NEW_FILE="$1"
            else
                error "Too many arguments. Expected OLD.tex and NEW.tex"
            fi
            shift
            ;;
    esac
done

# Validate required arguments
if [[ -z "$OLD_FILE" ]] || [[ -z "$NEW_FILE" ]]; then
    error "Missing required arguments. Usage: $0 OLD.tex NEW.tex [OPTIONS]
Run with --help for more information"
fi

# Validate prerequisites
info "Checking prerequisites..."
command -v latexdiff >/dev/null 2>&1 || error "latexdiff not found. Please install it (e.g., via TeX Live or MacTeX)"
command -v latexmk >/dev/null 2>&1 || error "latexmk not found. Please install it (e.g., via TeX Live or MacTeX)"

# Validate input files
if [[ ! -f "$OLD_FILE" ]]; then
    error "Old file not found: $OLD_FILE"
fi

if [[ ! -f "$NEW_FILE" ]]; then
    error "New file not found: $NEW_FILE"
fi

if [[ "$OLD_FILE" != *.tex ]]; then
    error "Old file must be a .tex file: $OLD_FILE"
fi

if [[ "$NEW_FILE" != *.tex ]]; then
    error "New file must be a .tex file: $NEW_FILE"
fi

# Convert to absolute paths
OLD_FILE="$(cd "$(dirname "$OLD_FILE")" && pwd)/$(basename "$OLD_FILE")"
NEW_FILE="$(cd "$(dirname "$NEW_FILE")" && pwd)/$(basename "$NEW_FILE")"

# Create temp directory
TEMP_DIR=$(mktemp -d -t latex-diff-XXXXXX)
if [[ "$KEEP_TEMP" != "1" ]]; then
    trap 'rm -rf "$TEMP_DIR"' EXIT
fi

info "Temporary directory: $TEMP_DIR"

# Set up paths
DIFF_FILE="$TEMP_DIR/diff.tex"
DIFF_RAW="$TEMP_DIR/diff-raw.tex"

# Run latexdiff
info "Running latexdiff..."
info "  Old: $OLD_FILE"
info "  New: $NEW_FILE"

# Change to repo root for proper path resolution
cd "$REPO_ROOT"

# Run latexdiff with proper options (without custom preamble to avoid option clashes)
if ! latexdiff \
    --flatten \
    --type=UNDERLINE \
    --encoding=utf8 \
    "$OLD_FILE" "$NEW_FILE" > "$DIFF_RAW" 2>"$TEMP_DIR/latexdiff.log"; then
    warning "latexdiff completed with warnings. Check $TEMP_DIR/latexdiff.log"
fi

# Post-process the diff file to customize colors
# Replace the default DIF commands with our custom red strikethrough and green highlighting
info "Customizing diff markup..."

# Create a sed script to modify the preamble commands
# We need to override the DIFadd and DIFdel commands that latexdiff generates
sed -e 's/\\DIFaddtex{/\\DIFadd{/g' \
    -e 's/\\DIFdeltex{/\\DIFdel{/g' \
    "$DIFF_RAW" > "$DIFF_FILE.tmp"

# Now add our custom command definitions after the preamble
# Find the line with "DIF END PREAMBLE" and insert our commands before it
# Also fix relative paths to shared/styles/ to use absolute paths from REPO_ROOT
awk -v repo_root="$REPO_ROOT" '
/DIF END PREAMBLE/ {
    print "% Custom diff color overrides"
    print "\\renewcommand{\\DIFadd}[1]{{\\protect\\color{green!70!black}#1}}"
    print "\\renewcommand{\\DIFdel}[1]{{\\protect\\color{red}\\sout{#1}}}"
    print "\\renewcommand{\\DIFaddbegin}{\\protect\\color{green!70!black}}"
    print "\\renewcommand{\\DIFaddend}{\\protect\\color{black}}"
    print "\\renewcommand{\\DIFdelbegin}{\\protect\\color{red}}"
    print "\\renewcommand{\\DIFdelend}{\\protect\\color{black}}"
    print "\\renewcommand{\\DIFaddFL}[1]{{\\protect\\color{green!70!black}#1}}"
    print "\\renewcommand{\\DIFdelFL}[1]{{\\protect\\color{red}\\sout{#1}}}"
    print "%DIF END PREAMBLE"
    next
}
{
    # Replace relative paths to shared/styles with absolute paths
    gsub(/\.\.\/\.\.\/shared\//, repo_root "/shared/")
    print
}
' "$DIFF_FILE.tmp" > "$DIFF_FILE"

rm "$DIFF_FILE.tmp"

# Check if diff file was created
if [[ ! -f "$DIFF_FILE" ]]; then
    error "Failed to generate diff file"
fi

success "Diff file generated successfully"

# Determine output paths
if [[ "$OUTPUT_BASE" = /* ]]; then
    # Absolute path
    OUTPUT_DIR="$(dirname "$OUTPUT_BASE")"
    OUTPUT_NAME="$(basename "$OUTPUT_BASE")"
else
    # Relative path - output to build directory
    OUTPUT_DIR="$REPO_ROOT/build"
    OUTPUT_NAME="$OUTPUT_BASE"
fi

# Create output directory if it doesn't exist
mkdir -p "$OUTPUT_DIR"

# Copy .tex file to output location
OUTPUT_TEX="$OUTPUT_DIR/${OUTPUT_NAME}.tex"
cp "$DIFF_FILE" "$OUTPUT_TEX"
success "Saved diff LaTeX file: $OUTPUT_TEX"

# Compile to PDF if requested
if [[ "$NO_PDF" != "1" ]]; then
    info "Compiling to PDF..."

    # Copy diff file to temp directory with output name for compilation
    COMPILE_FILE="$TEMP_DIR/${OUTPUT_NAME}.tex"
    cp "$DIFF_FILE" "$COMPILE_FILE"

    # Compile from repo root to preserve relative paths to shared/ directory
    cd "$REPO_ROOT"

    # Note: We use -f flag to force compilation despite package option warnings
    # and || true to continue even if latexmk exits with warnings
    # Use absolute path to compile file and output directory
    latexmk -xelatex \
        -f \
        -synctex=1 \
        -interaction=nonstopmode \
        -file-line-error \
        -output-directory="$TEMP_DIR" \
        "$COMPILE_FILE" >"$TEMP_DIR/compile.log" 2>&1 || true

    # Copy PDF to output location (check if it was actually generated)
    if [[ -f "$TEMP_DIR/${OUTPUT_NAME}.pdf" ]]; then
        OUTPUT_PDF="$OUTPUT_DIR/${OUTPUT_NAME}.pdf"
        cp "$TEMP_DIR/${OUTPUT_NAME}.pdf" "$OUTPUT_PDF"
        success "Saved diff PDF: $OUTPUT_PDF"

        # Check if there were warnings
        if grep -q "LaTeX Error\|Fatal error" "$TEMP_DIR/compile.log"; then
            warning "PDF was generated but compilation had errors"
            warning "Check $TEMP_DIR/compile.log for details"
        fi
    else
        error "PDF file was not generated. Check $TEMP_DIR/compile.log for details"
    fi
fi

# Print summary
echo ""
success "=== Diff generation complete ==="
echo -e "${GREEN}Output files:${NC}"
echo "  LaTeX: $OUTPUT_TEX"
if [[ "$NO_PDF" != "1" ]]; then
    echo "  PDF:   $OUTPUT_PDF"
fi

if [[ "$KEEP_TEMP" == "1" ]]; then
    echo ""
    info "Temporary files kept at: $TEMP_DIR"
    echo "  latexdiff.log - latexdiff output"
    if [[ "$NO_PDF" != "1" ]]; then
        echo "  compile.log   - PDF compilation output"
    fi
fi

echo ""
success "Done!"
