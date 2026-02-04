# tp-lint

🔍 Lint PO files from the [Translation Project](https://translationproject.org)

Fetch and lint translation files for any language team on the Translation Project using [l10n-lint](https://github.com/yeager/l10n-lint).

## Features

- **Fetch PO files** – Downloads all translations for a language from TP
- **Lint with l10n-lint** – Checks for missing translations, fuzzy entries, placeholder mismatches
- **📊 Statistics** – View translation coverage per language, per package, and global top lists
- **Filter by package** – Lint only specific packages
- **Multiple output formats** – Text, JSON, or GitHub Actions annotations
- **Localized** – Available in Swedish and German (more coming)

## Installation

### Debian/Ubuntu

```bash
wget https://github.com/yeager/tp-lint/releases/download/v1.4.0/tp-lint_1.4.0_all.deb
sudo dpkg -i tp-lint_1.4.0_all.deb
```

### Fedora/RHEL/openSUSE

```bash
wget https://github.com/yeager/tp-lint/releases/download/v1.4.0/tp-lint-1.4.0-1.noarch.rpm
sudo rpm -i tp-lint-1.4.0-1.noarch.rpm
```

### Arch Linux

```bash
wget https://github.com/yeager/tp-lint/releases/download/v1.4.0/tp-lint-1.4.0.pkg.tar.zst
sudo pacman -U tp-lint-1.4.0.pkg.tar.zst
```

### From source

```bash
git clone https://github.com/yeager/tp-lint.git
cd tp-lint
chmod +x tp_lint.py
ln -s $(pwd)/tp_lint.py /usr/local/bin/tp-lint
```

## Usage

### List available languages

```bash
tp-lint --list
```

### Lint all PO files for a language

```bash
# Swedish
tp-lint sv

# German
tp-lint de

# French
tp-lint fr
```

### Lint specific packages

```bash
# Only lint coreutils and bash translations
tp-lint sv -p coreutils -p bash
```

### Keep downloaded files

```bash
# Keep files in tp-lint-sv/
tp-lint sv --keep

# Save to specific directory
tp-lint sv -o ./swedish-translations/
```

### Output formats

```bash
# JSON output
tp-lint sv --format json

# GitHub Actions annotations
tp-lint sv --format github
```

### Strict mode

```bash
# Exit with error on warnings too
tp-lint sv --strict
```

### Statistics

```bash
# Global statistics with top lists
tp-lint --stats

# Statistics for a specific language
tp-lint --stats sv

# Statistics for a specific package
tp-lint --domain coreutils

# JSON output
tp-lint --stats sv --format json

# Show top 20 instead of default 15
tp-lint --stats --top 20
```

## Options

| Option | Description |
|--------|-------------|
| `-l`, `--list` | List all available languages |
| `-s`, `--stats [LANG]` | Show statistics (global or per language) |
| `-d`, `--domain PKG` | Show statistics for a specific package |
| `-n`, `--top N` | Number of items in top lists (default: 15) |
| `-f`, `--format` | Output format: `text`, `json`, `github` |
| `-k`, `--keep` | Keep downloaded PO files |
| `-o`, `--output` | Output directory for PO files |
| `-p`, `--package` | Filter by package name (repeatable) |
| `--strict` | Treat warnings as errors |
| `-v`, `--version` | Show version |

## Examples

### Find untranslated strings in Swedish

```bash
tp-lint sv | grep missing-translation
```

### Check coreutils before submitting

```bash
tp-lint sv -p coreutils --strict
```

### CI/CD integration

```bash
tp-lint sv --format github --strict
```

## Dependencies

- Python 3.8+
- [l10n-lint](https://github.com/yeager/l10n-lint) (required)

## Translation Project

The [Translation Project](https://translationproject.org) is a coordination hub for free software translation teams. It hosts PO files for hundreds of packages in 80+ languages.

This tool helps translation teams maintain quality by identifying common issues in their translations.

## Related tools

- [l10n-lint](https://github.com/yeager/l10n-lint) – Lint localization files
- [po-translate](https://github.com/yeager/po-translate) – Batch translate PO/TS files

## License

GPL-3.0-or-later

## Author

**Daniel Nylander** ([@yeager](https://github.com/yeager))

Member of the Swedish Translation Team at the Translation Project since 2004.
