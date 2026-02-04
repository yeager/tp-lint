# Changelog

## [1.6.0] - 2026-02-04

### Changed
- **Linting is now default** when language is specified
- `tp-lint sv` now lints all Swedish PO files (was just download)
- Added `--no-lint` flag to download without linting
- `-d/--domain` now filters packages during linting

### Removed
- `-L/--lint` flag (linting is now default)

## [1.5.8] - 2026-02-04

### Added
- **`-L` short flag** for `--lint` (easier to type)
- **Domain filter with lint**: `-L -d coreutils sv` lints only coreutils
- **Examples in help**: `--help` now shows common usage examples

### Changed
- `-d/--domain` works with `-L/--lint` to filter which packages to lint

## [1.5.7] - 2026-02-04

### Added
- **`--lint` flag**: Explicitly run l10n-lint on downloaded PO files
- **l10n-lint check**: Shows warning at startup if l10n-lint is not installed

### Changed
- Linting is now optional (use `--lint` to enable)
- Without `--lint`, tp-lint only downloads files and shows summary

## [1.5.6] - 2026-02-04

### Changed
- Updated man pages to version 1.5.6

## [1.5.5] - 2026-02-04

### Changed
- **HTML reports**: Completely redesigned with modern styling
  - Card-based layout with CSS variables
  - Progress bars for coverage visualization
  - Responsive design for mobile
  - Links to TP domain/team pages
- **Footer**: Now includes generator info, version, copyright and links
- **Swedish translation**: 100% complete, fixed incorrect translations

## [1.5.4] - 2026-02-04

### Added
- **Translated man pages**: Man pages now available in 37 languages
  - Section headers translated (NAME, DESCRIPTION, OPTIONS, etc.)
  - Installed to `/usr/share/man/<lang>/man1/`

## [1.5.3] - 2026-02-04

### Added
- **Man page**: `man tp-lint` now available
  - Installed to `/usr/share/man/man1/tp-lint.1.gz`

## [1.5.2] - 2026-02-04

### Changed
- **Debian policy compliance**: Packages now follow Debian packaging guidelines
  - Locale files installed to `/usr/share/tp-lint/locale/`
  - Added `/usr/share/doc/tp-lint/copyright`
  - Fixed locale lookup path in script

### Fixed
- **Debian package**: Rebuilt with correct ar format and structure

## [1.5.1] - 2026-02-04

### Fixed
- **Debian package**: Rebuilt with correct ar format (was using macOS BSD format)
  - Package now installs correctly on Debian/Ubuntu systems

## [1.5.0] - 2026-02-04

### Added
- 📄 **Report generation** - Create translation status reports
  - `--report` for global report, `--report LANG` for language-specific
  - `--report-format markdown|html` for output format
  - `--report-output FILE` to save to file
  - Includes complete/partial/missing package breakdown

## [1.4.0] - 2026-02-04

### Added
- 📊 **Statistics feature** - View translation coverage from the TP matrix
  - `--stats` for global statistics with top/bottom language lists
  - `--stats LANG` for language-specific stats (translated, partial, missing packages)
  - `--domain PKG` for package-specific stats (which languages have translated it)
  - `--top N` to customize number of items in top lists
  - JSON output support for stats

## [1.3.1] - 2026-02-03

### Fixed
- Language detection now properly reads environment variables
- Priority order: `LANGUAGE` > `LC_ALL` > `LC_MESSAGES` > `LANG` > `locale.getlocale()`

## [1.3.0] - 2026-02-03

### Added
- 37 language translations

## [1.2.0] - 2026-02-03

### Changed
- Separate fuzzy count from warnings in output

## [1.1.0] - 2026-02-03

### Added
- `--by-translator` option to group results by translator
- Improved i18n support

### Fixed
- Progress display issues

## [1.0.0] - 2026-02-03

### Added
- Initial release
- Fetch PO files from Translation Project
- Lint with l10n-lint integration
- Filter by package
- Multiple output formats (text, JSON, GitHub Actions)
