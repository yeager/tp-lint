#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# tp-lint - Lint Translation Project PO files
# Copyright (C) 2026 Daniel Nylander <daniel@danielnylander.se>

"""
tp-lint - Lint PO files from the Translation Project (translationproject.org)

This tool fetches PO files for a given language from the Translation Project
and runs l10n-lint on them to check for common translation issues.
"""

import argparse
import gettext
import html.parser
import json
import locale
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

__version__ = "1.1.0"

# Translation setup
DOMAIN = "tp-lint"

# Look for locale in multiple places
_possible_locale_dirs = [
    Path(__file__).parent / "locale",  # Development
    Path("/usr/share/tp-lint/locale"),  # System install
    Path("/usr/local/share/tp-lint/locale"),  # Local install
]
LOCALE_DIR = None
for _dir in _possible_locale_dirs:
    if _dir.exists():
        LOCALE_DIR = _dir
        break

# Initialize gettext - detect language
_system_lang = locale.getlocale()[0] or os.environ.get("LANG", "en")
_lang_code = _system_lang.split("_")[0].split(".")[0] if _system_lang else "en"

try:
    if LOCALE_DIR:
        translation = gettext.translation(DOMAIN, LOCALE_DIR, languages=[_lang_code], fallback=True)
    else:
        translation = gettext.NullTranslations()
    _ = translation.gettext
except Exception:
    def _(s): return s


# Translation Project base URL
TP_BASE = "https://translationproject.org"


class TeamPageParser(html.parser.HTMLParser):
    """Parse a TP team page to extract PO file URLs and translator assignments."""
    
    def __init__(self):
        super().__init__()
        self.po_files = []
        self.translators = {}  # domain -> translator name
        self._in_table = False
        self._current_domain = None
        self._in_translator_cell = False
        self._current_translator = None
        
    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "a":
            href = attrs_dict.get("href", "")
            if "/PO-files/" in href and href.endswith(".po"):
                # Convert relative URL to absolute
                if href.startswith("../"):
                    href = TP_BASE + "/" + href[3:]
                elif href.startswith("/"):
                    href = TP_BASE + href
                self.po_files.append(href)
                # Extract domain from URL
                filename = href.split("/")[-1]
                match = re.match(r"([^-]+)-.*\.po$", filename)
                if match:
                    self._current_domain = match.group(1)
            elif "/domain/" in href:
                # Domain link in assignment table
                match = re.match(r"\.\./domain/([^.]+)\.html$", href)
                if match:
                    self._current_domain = match.group(1)
            elif "mailto:" in href:
                self._in_translator_cell = True
                
    def handle_data(self, data):
        data = data.strip()
        if self._in_translator_cell and data and self._current_domain:
            self.translators[self._current_domain] = data
            self._in_translator_cell = False
            
    def handle_endtag(self, tag):
        if tag == "tr":
            self._current_domain = None
            self._in_translator_cell = False


class TeamIndexParser(html.parser.HTMLParser):
    """Parse the team index page to extract language codes."""
    
    def __init__(self):
        super().__init__()
        self.languages = []
        self.prev_tag = None
        self.current_lang_name = None
        
    def handle_starttag(self, tag, attrs):
        self.prev_tag = tag
        if tag == "a":
            href = dict(attrs).get("href", "")
            match = re.match(r"([a-z]{2,3})\.html$", href)
            if match:
                self.current_lang_name = None
                
    def handle_data(self, data):
        data = data.strip()
        if self.prev_tag == "a" and data and not data.startswith("mailto:"):
            if re.match(r"^[A-Z][a-z]+", data):
                self.current_lang_name = data
        elif self.prev_tag == "td" and re.match(r"^[a-z]{2,3}$", data):
            if self.current_lang_name:
                self.languages.append((data, self.current_lang_name))


def get_languages():
    """Fetch list of languages from Translation Project."""
    url = f"{TP_BASE}/team/index.html"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            html_content = resp.read().decode("utf-8")
    except urllib.error.URLError as e:
        print(_("Error fetching team index: {error}").format(error=e), file=sys.stderr)
        return []
    
    parser = TeamIndexParser()
    parser.feed(html_content)
    return parser.languages


def get_po_files_and_translators(lang_code):
    """Fetch list of PO file URLs and translator assignments for a language."""
    url = f"{TP_BASE}/team/{lang_code}.html"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            html_content = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(_("Language '{lang}' not found on Translation Project").format(lang=lang_code), file=sys.stderr)
        else:
            print(_("Error fetching team page: {error}").format(error=e), file=sys.stderr)
        return [], {}
    except urllib.error.URLError as e:
        print(_("Error fetching team page: {error}").format(error=e), file=sys.stderr)
        return [], {}
    
    parser = TeamPageParser()
    parser.feed(html_content)
    return parser.po_files, parser.translators


def download_po_file(url, dest_dir):
    """Download a PO file to the destination directory."""
    filename = url.split("/")[-1]
    dest_path = dest_dir / filename
    
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            content = resp.read()
        dest_path.write_bytes(content)
        return dest_path
    except Exception as e:
        print(_("Error downloading {url}: {error}").format(url=url, error=e), file=sys.stderr)
        return None


def get_domain_from_filename(filename):
    """Extract domain name from PO filename."""
    match = re.match(r"([^-]+)-.*\.po$", filename)
    if match:
        return match.group(1)
    match = re.match(r"([^.]+)\..*\.po$", filename)
    if match:
        return match.group(1)
    return filename


def run_l10n_lint(path, output_format="text", strict=False, lang_code=None):
    """Run l10n-lint on a file or directory."""
    cmd = ["l10n-lint"]
    
    if output_format != "text":
        cmd.extend(["--format", output_format])
    if strict:
        cmd.append("--strict")
    
    cmd.append(str(path))
    
    # Pass language to l10n-lint via environment
    env = os.environ.copy()
    if lang_code:
        env["LANG"] = f"{lang_code}.UTF-8"
        env["LC_ALL"] = f"{lang_code}.UTF-8"
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, env=env)
        return result.stdout, result.stderr, result.returncode
    except FileNotFoundError:
        print(_("Error: l10n-lint not found. Please install l10n-lint first."), file=sys.stderr)
        sys.exit(1)


def run_l10n_lint_per_file(files, output_format="text", strict=False, lang_code=None):
    """Run l10n-lint on each file and return results per file."""
    results = {}
    
    env = os.environ.copy()
    if lang_code:
        env["LANG"] = f"{lang_code}.UTF-8"
        env["LC_ALL"] = f"{lang_code}.UTF-8"
    
    for filepath in files:
        cmd = ["l10n-lint", "--format", "json", str(filepath)]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, env=env)
            if result.stdout.strip():
                try:
                    data = json.loads(result.stdout)
                    results[filepath.name] = data
                except json.JSONDecodeError:
                    pass
        except FileNotFoundError:
            print(_("Error: l10n-lint not found. Please install l10n-lint first."), file=sys.stderr)
            sys.exit(1)
    
    return results


def clear_line():
    """Clear the current terminal line."""
    sys.stdout.write("\033[K")
    sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser(
        prog="tp-lint",
        description=_("Lint PO files from the Translation Project (translationproject.org)"),
        epilog=_("Example: tp-lint sv")
    )
    
    parser.add_argument(
        "language",
        nargs="?",
        help=_("Language code to lint (e.g., sv, de, fr)")
    )
    
    parser.add_argument(
        "-l", "--list",
        action="store_true",
        help=_("List all available languages")
    )
    
    parser.add_argument(
        "-f", "--format",
        choices=["text", "json", "github"],
        default="text",
        help=_("Output format (default: text)")
    )
    
    parser.add_argument(
        "--strict",
        action="store_true",
        help=_("Treat warnings as errors")
    )
    
    parser.add_argument(
        "-k", "--keep",
        action="store_true",
        help=_("Keep downloaded PO files (don't delete temp directory)")
    )
    
    parser.add_argument(
        "-o", "--output",
        help=_("Output directory for downloaded PO files (implies --keep)")
    )
    
    parser.add_argument(
        "-p", "--package",
        action="append",
        dest="packages",
        help=_("Only lint specific package(s) (can be repeated)")
    )
    
    parser.add_argument(
        "-t", "--by-translator",
        action="store_true",
        help=_("Group results by translator")
    )
    
    parser.add_argument(
        "-v", "--version",
        action="version",
        version=f"%(prog)s {__version__}"
    )
    
    args = parser.parse_args()
    
    # List languages mode
    if args.list:
        print(_("Fetching languages from Translation Project..."))
        languages = get_languages()
        if not languages:
            print(_("Could not fetch language list"), file=sys.stderr)
            return 1
        
        print()
        print(_("Available languages ({count}):").format(count=len(languages)))
        print()
        for code, name in sorted(languages, key=lambda x: x[1]):
            print(f"  {code:6} {name}")
        return 0
    
    # Require language for linting
    if not args.language:
        parser.print_help()
        return 1
    
    lang_code = args.language.lower()
    
    # Fetch PO file list and translators
    print(_("Fetching PO files for '{lang}'...").format(lang=lang_code))
    po_urls, translators = get_po_files_and_translators(lang_code)
    
    if not po_urls:
        print(_("No PO files found for language '{lang}'").format(lang=lang_code), file=sys.stderr)
        return 1
    
    # Filter by package if specified
    if args.packages:
        filtered = []
        for url in po_urls:
            filename = url.split("/")[-1]
            for pkg in args.packages:
                if filename.startswith(pkg + "-") or filename.startswith(pkg + "."):
                    filtered.append(url)
                    break
        po_urls = filtered
        
        if not po_urls:
            print(_("No matching packages found"), file=sys.stderr)
            return 1
    
    print(_("Found {count} PO files").format(count=len(po_urls)))
    
    # Setup output directory
    if args.output:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        temp_dir = None
        keep_files = True
    elif args.keep:
        output_dir = Path(f"tp-lint-{lang_code}")
        output_dir.mkdir(parents=True, exist_ok=True)
        temp_dir = None
        keep_files = True
    else:
        temp_dir = tempfile.mkdtemp(prefix="tp-lint-")
        output_dir = Path(temp_dir)
        keep_files = False
    
    # Download PO files
    print(_("Downloading PO files..."))
    downloaded = []
    max_filename_len = 0
    for i, url in enumerate(po_urls, 1):
        filename = url.split("/")[-1]
        max_filename_len = max(max_filename_len, len(filename))
        # Clear line and print progress
        progress = _("  [{current}/{total}] {filename}").format(
            current=i, total=len(po_urls), filename=filename
        )
        sys.stdout.write(f"\r\033[K{progress}")
        sys.stdout.flush()
        path = download_po_file(url, output_dir)
        if path:
            downloaded.append(path)
    
    # Clear progress line and print completion
    sys.stdout.write("\r\033[K")
    sys.stdout.flush()
    print(_("Downloaded {count} files").format(count=len(downloaded)))
    
    if not downloaded:
        print(_("No files to lint"), file=sys.stderr)
        return 1
    
    # Run l10n-lint
    print()
    print(_("Running l10n-lint..."))
    print("=" * 60)
    
    if args.by_translator:
        # Group results by translator
        lint_results = run_l10n_lint_per_file(downloaded, args.format, args.strict, _lang_code)
        
        # Group by translator
        translator_results = {}
        for filename, data in lint_results.items():
            domain = get_domain_from_filename(filename)
            translator = translators.get(domain, _("Unknown"))
            if translator not in translator_results:
                translator_results[translator] = {"files": [], "errors": 0, "warnings": 0}
            translator_results[translator]["files"].append(filename)
            
            issues = data.get("issues", [])
            for issue in issues:
                if issue.get("severity") == "error":
                    translator_results[translator]["errors"] += 1
                else:
                    translator_results[translator]["warnings"] += 1
        
        # Print results by translator
        print()
        print(_("Results by translator:"))
        print()
        
        for translator in sorted(translator_results.keys()):
            stats = translator_results[translator]
            print(f"👤 {translator}")
            print(_("   Files: {count}").format(count=len(stats["files"])))
            print(_("   Errors: {count}").format(count=stats["errors"]))
            print(_("   Warnings: {count}").format(count=stats["warnings"]))
            print()
        
        # Summary
        total_errors = sum(s["errors"] for s in translator_results.values())
        total_warnings = sum(s["warnings"] for s in translator_results.values())
        print("=" * 60)
        print(_("Total: {files} files, {errors} errors, {warnings} warnings").format(
            files=len(downloaded), errors=total_errors, warnings=total_warnings
        ))
        
        returncode = 1 if total_errors > 0 or (args.strict and total_warnings > 0) else 0
    else:
        # Standard mode - run on whole directory
        stdout, stderr, returncode = run_l10n_lint(
            output_dir,
            output_format=args.format,
            strict=args.strict,
            lang_code=_lang_code
        )
        
        if stdout:
            print(stdout)
        if stderr:
            print(stderr, file=sys.stderr)
    
    # Cleanup
    if not keep_files and temp_dir:
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
    elif keep_files:
        print()
        print(_("PO files saved to: {path}").format(path=output_dir))
    
    return returncode


if __name__ == "__main__":
    sys.exit(main())
