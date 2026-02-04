# Changelog

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
