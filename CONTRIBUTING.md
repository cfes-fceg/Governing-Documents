# CFES Governance Documents

LaTeX source for Canadian Federation of Engineering Students governance documents.

## Repository Structure

- `shared/` - Common styles, templates, and assets used across all documents
  - `styles/` - LaTeX style packages (cfes-common.sty, cfes-headers.sty, ninecolors.sty)
  - `assets/logos/` - CFES logos (PNG format)
  - `templates/` - Template files for preamble and title pages
- `documents/` - Individual governance documents
  - `constitution/` - CFES Constitution
- `utilities/` - Build and formatting scripts
- `build/` - Temporary build artifacts (gitignored)

## Building Documents

### Prerequisites

- **XeLaTeX** (TeXLive 2024 or later recommended)
- **Arial font** (pre-installed on macOS, see installation notes for Linux)
- **latexindent** (for formatting, included in TeXLive)
- **latexmk** (for building, included in TeXLive)

### Build Single Document

```bash
cd documents/constitution
latexmk -xelatex main.tex
```

The PDF will be generated in the `build/` directory at the repository root.

### Build All Documents

```bash
./utilities/build-all.sh
```

## Development Setup

### VSCode Setup

1. Install required extensions:
   - LaTeX Workshop by James Yu
   - LaTeX Utilities (optional but recommended)

2. Open this repository in VSCode

3. Settings are preconfigured in `.vscode/settings.json`

4. To build: Open any `.tex` file and use the LaTeX Workshop sidebar or keyboard shortcuts

### Font Installation

**macOS**: Arial comes pre-installed.

**Linux**:
```bash
sudo apt install ttf-mscorefonts-installer
fc-cache -f
```

**Windows**: Arial comes pre-installed.

## Formatting

Format all LaTeX files using latexindent:

```bash
./utilities/format.sh
```

This ensures consistent formatting across all documents.

## Document List

- [Constitution](documents/constitution/) - CFES Constitution (English Edition)

## Converting from Google Docs

See [CONVERSION_GUIDE.md](CONVERSION_GUIDE.md) for detailed instructions on converting Google Docs to LaTeX format.

## Repository Structure Philosophy

This repository uses a **multi-document architecture** where each governance document is maintained separately in `documents/[doc-name]/`. All documents share:

- Common styling (CFES branding, fonts, spacing)
- Build infrastructure
- Formatting conventions

This allows:
- Independent versioning of documents
- Consistent visual identity across all materials
- Efficient maintenance and updates

## Contributing

1. Make changes to LaTeX source files
2. Test build locally: `cd documents/[doc] && latexmk -xelatex main.tex`
3. Format code: `./utilities/format.sh`
4. Commit with descriptive message
5. Push to repository

## Git Workflow

The repository follows these commit conventions:

- `feat: Add [feature/document]` - New documents or major sections
- `fix: Correct [issue] in [document]` - Corrections or bug fixes
- `style: Format [document]` - Formatting changes only
- `docs: Update [documentation]` - Documentation updates
- `build: Update build configuration` - Build system changes

## Troubleshooting

### Build Errors

**Missing logo error**: Add CFES logo files to `shared/assets/logos/`. See [shared/assets/logos/README.md](shared/assets/logos/README.md).

**Font not found**: Ensure Arial font is installed. Run `fc-list | grep Arial` to verify (Linux/macOS).

**Permission denied on scripts**: Make scripts executable: `chmod +x utilities/*.sh`

### Formatting Issues

If formatting changes code unexpectedly, check `utilities/format.yaml` configuration.

## License

Copyright © Canadian Federation of Engineering Students

## Contact

For questions about this repository or CFES governance documents, contact the CFES Board Chair through email at chair@cfes.ca.
