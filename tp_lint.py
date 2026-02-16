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
import time
import urllib.error
import urllib.request
from pathlib import Path

__version__ = "1.8.3"

# Translation setup
DOMAIN = "tp-lint"

# Look for locale in multiple places
_possible_locale_dirs = [
    Path("/usr/share/tp-lint/locale"),  # System install (Debian)
    Path(__file__).parent / "locale",  # Development
]
LOCALE_DIR = None
for _dir in _possible_locale_dirs:
    # Check it's a real locale dir (has LC_MESSAGES subdir or .pot file)
    if _dir.is_dir() and (list(_dir.glob("*/LC_MESSAGES")) or list(_dir.glob("*.pot"))):
        LOCALE_DIR = _dir
        break

# Initialize gettext - detect language
# Priority: LANGUAGE > LC_ALL > LC_MESSAGES > LANG > locale.getlocale()
_system_lang = (
    os.environ.get("LANGUAGE", "").split(":")[0] or
    os.environ.get("LC_ALL", "") or
    os.environ.get("LC_MESSAGES", "") or
    os.environ.get("LANG", "") or
    locale.getlocale()[0] or
    "en"
)
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


class MatrixParser(html.parser.HTMLParser):
    """Parse the TP matrix page to extract translation statistics."""
    
    def __init__(self):
        super().__init__()
        self.languages = []  # List of language codes from header
        self.lang_percentages = {}  # lang_code -> overall percentage
        self.domains = {}  # domain -> {lang_code: percentage}
        self.domain_counts = {}  # domain -> number of translations
        self._in_header = False
        self._in_pct_row = False
        self._current_row = []
        self._current_domain = None
        self._cell_index = 0
        self._in_td = False
        self._td_content = ""
        self._current_href = None
        
    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "thead":
            self._in_header = True
        elif tag == "tbody":
            self._in_header = False
        elif tag == "tr":
            self._current_row = []
            self._cell_index = 0
            self._current_domain = None
        elif tag == "th" and self._in_header:
            self._in_td = True
            self._td_content = ""
            self._current_href = None
        elif tag == "td":
            self._in_td = True
            self._td_content = ""
            self._current_href = None
        elif tag == "a" and self._in_td:
            href = attrs_dict.get("href", "")
            self._current_href = href
            # Check for language link in header
            if self._in_header and "/team/" in href:
                match = re.search(r"/team/([^.]+)\.html", href)
                if match:
                    lang = match.group(1)
                    self.languages.append(lang)
            # Check for domain link
            elif "/domain/" in href:
                match = re.search(r"/domain/([^.]+)\.html", href)
                if match:
                    self._current_domain = match.group(1)
                    
    def handle_data(self, data):
        if self._in_td:
            self._td_content += data.strip()
            
    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            content = self._td_content.strip()
            self._current_row.append(content)
            self._cell_index += 1
            self._in_td = False
        elif tag == "tr" and not self._in_header:
            self._process_row()
            
    def _process_row(self):
        if len(self._current_row) < 3:
            return
            
        # Check if this is the percentage summary row
        if self._current_row[1] == "Pct":
            self._in_pct_row = True
            # Parse language percentages (skip first 2 columns: empty + "Pct")
            for i, lang in enumerate(self.languages):
                if i + 2 < len(self._current_row):
                    pct_str = self._current_row[i + 2].replace("%", "")
                    try:
                        self.lang_percentages[lang] = int(pct_str)
                    except ValueError:
                        self.lang_percentages[lang] = 0
            return
            
        # Regular domain row
        if self._current_domain:
            self.domains[self._current_domain] = {}
            count = 0
            # Parse percentages for each language
            for i, lang in enumerate(self.languages):
                # Cell index: domain(0), pct(1), lang cells start at 2
                cell_idx = i + 2
                if cell_idx < len(self._current_row):
                    cell = self._current_row[cell_idx]
                    if cell and cell != "\xa0" and cell != "":
                        pct_str = cell.replace("%", "")
                        try:
                            pct = int(pct_str)
                            self.domains[self._current_domain][lang] = pct
                            count += 1
                        except ValueError:
                            pass
            # Get count from last column if available
            if self._current_row[-1].isdigit():
                self.domain_counts[self._current_domain] = int(self._current_row[-1])
            else:
                self.domain_counts[self._current_domain] = count


def fetch_matrix():
    """Fetch and parse the translation matrix."""
    url = f"{TP_BASE}/extra/matrix.html"
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            html_content = resp.read().decode("utf-8")
    except urllib.error.URLError as e:
        print(_("Error fetching matrix: {error}").format(error=e), file=sys.stderr)
        return None
    
    parser = MatrixParser()
    parser.feed(html_content)
    return parser


def print_stats(matrix, lang_filter=None, domain_filter=None, top_n=15, output_format="text"):
    """Print statistics from the matrix data."""
    
    if output_format == "json":
        stats = {
            "total_languages": len(matrix.languages),
            "total_domains": len(matrix.domains),
            "languages": matrix.lang_percentages,
            "domains": {d: {"translations": len(t), "languages": t} for d, t in matrix.domains.items()}
        }
        if lang_filter:
            stats["filter"] = {"language": lang_filter}
        if domain_filter:
            stats["filter"] = {"domain": domain_filter}
        print(json.dumps(stats, indent=2, ensure_ascii=False))
        return
    
    # Text output
    print()
    print("=" * 60)
    print(_("📊 Translation Project Statistics"))
    print("=" * 60)
    print()
    
    # Overall stats
    total_langs = len(matrix.languages)
    total_domains = len(matrix.domains)
    total_translations = sum(len(t) for t in matrix.domains.values())
    max_translations = total_langs * total_domains
    overall_pct = (total_translations / max_translations * 100) if max_translations > 0 else 0
    
    print(_("📈 Overview"))
    print("-" * 40)
    print(_("  Languages: {count}").format(count=total_langs))
    print(_("  Domains (packages): {count}").format(count=total_domains))
    print(_("  Total translations: {count}").format(count=total_translations))
    print(_("  Overall coverage: {pct:.1f}%").format(pct=overall_pct))
    print()
    
    # Filter by language
    if lang_filter:
        lang_filter = lang_filter.lower()
        # Handle variants like pt_BR -> BR in matrix
        lang_key = lang_filter
        if lang_filter not in matrix.lang_percentages:
            # Try uppercase suffix (pt_BR -> BR)
            if "_" in lang_filter:
                lang_key = lang_filter.split("_")[1].upper()
        
        if lang_key not in matrix.lang_percentages and lang_filter not in matrix.languages:
            print(_("⚠️  Language '{lang}' not found in matrix").format(lang=lang_filter))
            print(_("   Available: {langs}").format(langs=", ".join(sorted(matrix.languages)[:20]) + "..."))
            return
        
        print(_("🔍 Statistics for: {lang}").format(lang=lang_filter.upper()))
        print("-" * 40)
        
        pct = matrix.lang_percentages.get(lang_key, matrix.lang_percentages.get(lang_filter, 0))
        print(_("  Overall coverage: {pct}%").format(pct=pct))
        
        # Count translations for this language
        translated = []
        not_translated = []
        for domain, langs in matrix.domains.items():
            if lang_key in langs or lang_filter in langs:
                p = langs.get(lang_key, langs.get(lang_filter, 0))
                translated.append((domain, p))
            else:
                not_translated.append(domain)
        
        print(_("  Translated: {count}/{total} packages").format(count=len(translated), total=total_domains))
        print()
        
        # Top translated packages
        print(_("✅ Best translations (100%):"))
        complete = [(d, p) for d, p in translated if p == 100]
        if complete:
            for d, p in sorted(complete)[:top_n]:
                print(f"     {d}")
            if len(complete) > top_n:
                print(_("     ... and {more} more").format(more=len(complete) - top_n))
        else:
            print(_("     (none)"))
        print()
        
        # Partial translations
        print(_("🔶 Partial translations:"))
        partial = [(d, p) for d, p in translated if 0 < p < 100]
        partial.sort(key=lambda x: x[1], reverse=True)
        if partial:
            for d, p in partial[:top_n]:
                print(f"     {d}: {p}%")
            if len(partial) > top_n:
                print(_("     ... and {more} more").format(more=len(partial) - top_n))
        else:
            print(_("     (none)"))
        print()
        
        # Missing translations (popular packages)
        print(_("❌ Missing (not translated):"))
        if not_translated:
            # Show first N alphabetically
            for d in sorted(not_translated)[:top_n]:
                print(f"     {d}")
            if len(not_translated) > top_n:
                print(_("     ... and {more} more").format(more=len(not_translated) - top_n))
        else:
            print(_("     (none - all packages translated!)"))
        return
    
    # Filter by domain
    if domain_filter:
        domain_filter = domain_filter.lower()
        if domain_filter not in matrix.domains:
            # Try fuzzy match
            matches = [d for d in matrix.domains if domain_filter in d.lower()]
            if matches:
                print(_("⚠️  Domain '{domain}' not found. Did you mean:").format(domain=domain_filter))
                for m in matches[:5]:
                    print(f"     {m}")
                return
            print(_("⚠️  Domain '{domain}' not found").format(domain=domain_filter))
            return
        
        print(_("🔍 Statistics for package: {domain}").format(domain=domain_filter))
        print("-" * 40)
        
        langs = matrix.domains[domain_filter]
        print(_("  Translations: {count}/{total} languages").format(count=len(langs), total=total_langs))
        print()
        
        # Complete translations
        complete = [(l, p) for l, p in langs.items() if p == 100]
        print(_("✅ Complete (100%): {count}").format(count=len(complete)))
        if complete:
            lang_list = ", ".join(sorted(l for l, p in complete))
            print(f"     {lang_list}")
        print()
        
        # Partial
        partial = [(l, p) for l, p in langs.items() if 0 < p < 100]
        partial.sort(key=lambda x: x[1], reverse=True)
        print(_("🔶 Partial: {count}").format(count=len(partial)))
        if partial:
            for l, p in partial[:top_n]:
                print(f"     {l}: {p}%")
        print()
        
        # Missing
        translated_langs = set(langs.keys())
        missing = [l for l in matrix.languages if l not in translated_langs]
        print(_("❌ Missing: {count}").format(count=len(missing)))
        if missing:
            print(f"     {', '.join(sorted(missing)[:20])}{'...' if len(missing) > 20 else ''}")
        return
    
    # Global top lists
    print(_("🏆 Top {n} Languages (by coverage)").format(n=top_n))
    print("-" * 40)
    sorted_langs = sorted(matrix.lang_percentages.items(), key=lambda x: x[1], reverse=True)
    for i, (lang, pct) in enumerate(sorted_langs[:top_n], 1):
        bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
        print(f"  {i:2}. {lang:6} {bar} {pct}%")
    print()
    
    # Bottom languages
    print(_("📉 Bottom {n} Languages").format(n=min(10, top_n)))
    print("-" * 40)
    for i, (lang, pct) in enumerate(sorted_langs[-min(10, top_n):], 1):
        bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
        print(f"  {i:2}. {lang:6} {bar} {pct}%")
    print()
    
    # Best covered domains
    print(_("📦 Best Covered Packages (most translations)"))
    print("-" * 40)
    domain_coverage = [(d, len(t), sum(t.values()) / len(t) if t else 0) 
                       for d, t in matrix.domains.items()]
    domain_coverage.sort(key=lambda x: (x[1], x[2]), reverse=True)
    for i, (domain, count, avg_pct) in enumerate(domain_coverage[:top_n], 1):
        print(f"  {i:2}. {domain:20} {count:2} langs, avg {avg_pct:.0f}%")
    print()
    
    # Least covered domains
    print(_("🆘 Least Covered Packages (need translations)"))
    print("-" * 40)
    domain_coverage.sort(key=lambda x: (x[1], x[2]))
    for i, (domain, count, avg_pct) in enumerate(domain_coverage[:top_n], 1):
        print(f"  {i:2}. {domain:20} {count:2} langs, avg {avg_pct:.0f}%")


def generate_report(matrix, lang_filter=None, output_file=None, report_format="markdown"):
    """Generate a translation status report."""
    from datetime import datetime
    
    lines = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    if report_format == "markdown":
        lines.append(f"# Translation Project Report")
        lines.append(f"")
        lines.append(f"Generated: {now}")
        lines.append(f"")
        
        # Overview
        total_langs = len(matrix.languages)
        total_domains = len(matrix.domains)
        total_translations = sum(len(t) for t in matrix.domains.values())
        max_translations = total_langs * total_domains
        overall_pct = (total_translations / max_translations * 100) if max_translations > 0 else 0
        
        lines.append(f"## Overview")
        lines.append(f"")
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        lines.append(f"| Languages | {total_langs} |")
        lines.append(f"| Packages | {total_domains} |")
        lines.append(f"| Total translations | {total_translations} |")
        lines.append(f"| Overall coverage | {overall_pct:.1f}% |")
        lines.append(f"")
        
        if lang_filter:
            # Language-specific report
            lang_key = lang_filter.lower()
            if "_" in lang_filter and lang_key not in matrix.lang_percentages:
                lang_key = lang_filter.split("_")[1].upper()
            
            pct = matrix.lang_percentages.get(lang_key, matrix.lang_percentages.get(lang_filter.lower(), 0))
            
            lines.append(f"## Language: {lang_filter.upper()}")
            lines.append(f"")
            lines.append(f"**Coverage:** {pct}%")
            lines.append(f"")
            
            # Categorize packages
            complete = []
            partial = []
            missing = []
            
            for domain, langs in matrix.domains.items():
                if lang_key in langs or lang_filter.lower() in langs:
                    p = langs.get(lang_key, langs.get(lang_filter.lower(), 0))
                    if p == 100:
                        complete.append(domain)
                    else:
                        partial.append((domain, p))
                else:
                    missing.append(domain)
            
            lines.append(f"### Complete (100%) – {len(complete)} packages")
            lines.append(f"")
            if complete:
                for d in sorted(complete):
                    lines.append(f"- {d}")
            else:
                lines.append(f"*None*")
            lines.append(f"")
            
            lines.append(f"### Partial – {len(partial)} packages")
            lines.append(f"")
            if partial:
                lines.append(f"| Package | Coverage |")
                lines.append(f"|---------|----------|")
                for d, p in sorted(partial, key=lambda x: x[1], reverse=True):
                    lines.append(f"| {d} | {p}% |")
            else:
                lines.append(f"*None*")
            lines.append(f"")
            
            lines.append(f"### Missing – {len(missing)} packages")
            lines.append(f"")
            if missing:
                for d in sorted(missing):
                    lines.append(f"- {d}")
            else:
                lines.append(f"*None – all packages translated!* 🎉")
            lines.append(f"")
        else:
            # Global report - top languages
            lines.append(f"## Top Languages")
            lines.append(f"")
            lines.append(f"| Rank | Language | Coverage |")
            lines.append(f"|------|----------|----------|")
            sorted_langs = sorted(matrix.lang_percentages.items(), key=lambda x: x[1], reverse=True)
            for i, (lang, pct) in enumerate(sorted_langs[:20], 1):
                lines.append(f"| {i} | {lang} | {pct}% |")
            lines.append(f"")
            
            # Best covered packages
            lines.append(f"## Best Covered Packages")
            lines.append(f"")
            lines.append(f"| Package | Languages | Avg Coverage |")
            lines.append(f"|---------|-----------|--------------|")
            domain_coverage = [(d, len(t), sum(t.values()) / len(t) if t else 0) 
                               for d, t in matrix.domains.items()]
            domain_coverage.sort(key=lambda x: (x[1], x[2]), reverse=True)
            for d, count, avg in domain_coverage[:20]:
                lines.append(f"| {d} | {count} | {avg:.0f}% |")
            lines.append(f"")
    
    elif report_format == "html":
        title = f"Translation Project Report" + (f" – {lang_filter.upper()}" if lang_filter else "")
        lines.append(f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="generator" content="tp-lint {__version__}">
    <meta name="description" content="Translation status report from the GNU Translation Project">
    <title>{title}</title>
    <style>
        :root {{
            --primary: #2563eb;
            --success: #16a34a;
            --warning: #ca8a04;
            --danger: #dc2626;
            --bg: #f8fafc;
            --card-bg: #ffffff;
            --text: #1e293b;
            --text-muted: #64748b;
            --border: #e2e8f0;
        }}
        * {{ box-sizing: border-box; }}
        body {{
            font-family: system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;
            max-width: 1000px;
            margin: 0 auto;
            padding: 2rem 1rem;
            background: var(--bg);
            color: var(--text);
            line-height: 1.6;
        }}
        header {{
            text-align: center;
            margin-bottom: 2rem;
            padding-bottom: 1rem;
            border-bottom: 2px solid var(--border);
        }}
        h1 {{ color: var(--primary); margin: 0 0 0.5rem; }}
        .meta {{ color: var(--text-muted); font-size: 0.9rem; }}
        .card {{
            background: var(--card-bg);
            border-radius: 8px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            padding: 1.5rem;
            margin-bottom: 1.5rem;
        }}
        h2 {{ color: var(--text); margin: 0 0 1rem; font-size: 1.25rem; }}
        h3 {{ margin: 1rem 0 0.5rem; font-size: 1rem; }}
        h3.complete {{ color: var(--success); }}
        h3.partial {{ color: var(--warning); }}
        h3.missing {{ color: var(--danger); }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.95rem;
        }}
        th, td {{
            padding: 0.75rem;
            text-align: left;
            border-bottom: 1px solid var(--border);
        }}
        th {{ background: var(--bg); font-weight: 600; }}
        tr:hover {{ background: var(--bg); }}
        .overview-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 1rem;
        }}
        .stat {{
            text-align: center;
            padding: 1rem;
            background: var(--bg);
            border-radius: 6px;
        }}
        .stat-value {{ font-size: 1.75rem; font-weight: bold; color: var(--primary); }}
        .stat-label {{ font-size: 0.85rem; color: var(--text-muted); }}
        ul {{ padding-left: 1.5rem; }}
        li {{ margin: 0.25rem 0; }}
        .progress {{
            height: 8px;
            background: var(--border);
            border-radius: 4px;
            overflow: hidden;
        }}
        .progress-bar {{
            height: 100%;
            background: var(--success);
            transition: width 0.3s;
        }}
        footer {{
            margin-top: 3rem;
            padding-top: 1.5rem;
            border-top: 1px solid var(--border);
            text-align: center;
            font-size: 0.85rem;
            color: var(--text-muted);
        }}
        footer a {{ color: var(--primary); text-decoration: none; }}
        footer a:hover {{ text-decoration: underline; }}
        @media (max-width: 600px) {{
            body {{ padding: 1rem 0.5rem; }}
            .card {{ padding: 1rem; }}
        }}
    </style>
</head>
<body>
<header>
    <h1>📊 {title}</h1>
    <p class="meta">Generated: {now} · Data source: <a href="https://translationproject.org/extra/matrix.html">Translation Project</a></p>
</header>""")
        
        total_langs = len(matrix.languages)
        total_domains = len(matrix.domains)
        total_translations = sum(len(t) for t in matrix.domains.values())
        max_translations = total_langs * total_domains
        overall_pct = (total_translations / max_translations * 100) if max_translations > 0 else 0
        
        lines.append(f"""<div class="card">
<h2>📈 Overview</h2>
<div class="overview-grid">
    <div class="stat"><div class="stat-value">{total_langs}</div><div class="stat-label">Languages</div></div>
    <div class="stat"><div class="stat-value">{total_domains}</div><div class="stat-label">Packages</div></div>
    <div class="stat"><div class="stat-value">{total_translations:,}</div><div class="stat-label">Translations</div></div>
    <div class="stat"><div class="stat-value">{overall_pct:.1f}%</div><div class="stat-label">Coverage</div></div>
</div>
</div>""")
        
        if lang_filter:
            lang_key = lang_filter.lower()
            if "_" in lang_filter and lang_key not in matrix.lang_percentages:
                lang_key = lang_filter.split("_")[1].upper()
            pct = matrix.lang_percentages.get(lang_key, matrix.lang_percentages.get(lang_filter.lower(), 0))
            
            complete, partial, missing = [], [], []
            for domain, langs in matrix.domains.items():
                if lang_key in langs or lang_filter.lower() in langs:
                    p = langs.get(lang_key, langs.get(lang_filter.lower(), 0))
                    if p == 100:
                        complete.append(domain)
                    else:
                        partial.append((domain, p))
                else:
                    missing.append(domain)
            
            lines.append(f"""<div class="card">
<h2>🌐 Language: {lang_filter.upper()}</h2>
<div style="margin-bottom:1rem">
    <div style="display:flex;justify-content:space-between;margin-bottom:0.25rem">
        <span>Coverage</span><span><strong>{pct}%</strong></span>
    </div>
    <div class="progress"><div class="progress-bar" style="width:{pct}%"></div></div>
</div>
<div class="overview-grid">
    <div class="stat"><div class="stat-value" style="color:var(--success)">{len(complete)}</div><div class="stat-label">Complete (100%)</div></div>
    <div class="stat"><div class="stat-value" style="color:var(--warning)">{len(partial)}</div><div class="stat-label">Partial</div></div>
    <div class="stat"><div class="stat-value" style="color:var(--danger)">{len(missing)}</div><div class="stat-label">Missing</div></div>
</div>
</div>""")
            
            lines.append(f"""<div class="card">
<h3 class="complete">✅ Complete (100%) – {len(complete)} packages</h3>
<ul>""")
            for d in sorted(complete):
                lines.append(f"<li><a href='https://translationproject.org/domain/{d}.html'>{d}</a></li>")
            if not complete:
                lines.append("<li><em>None</em></li>")
            lines.append("</ul></div>")
            
            if partial:
                lines.append(f"""<div class="card">
<h3 class="partial">🔶 Partial – {len(partial)} packages</h3>
<table><thead><tr><th>Package</th><th>Coverage</th><th>Progress</th></tr></thead><tbody>""")
                for d, p in sorted(partial, key=lambda x: x[1], reverse=True):
                    lines.append(f"<tr><td><a href='https://translationproject.org/domain/{d}.html'>{d}</a></td><td>{p}%</td><td><div class='progress' style='width:100px'><div class='progress-bar' style='width:{p}%;background:var(--warning)'></div></div></td></tr>")
                lines.append("</tbody></table></div>")
            
            if missing:
                lines.append(f"""<div class="card">
<h3 class="missing">❌ Missing – {len(missing)} packages</h3>
<ul style="column-count:3;column-gap:1rem">""")
                for d in sorted(missing):
                    lines.append(f"<li><a href='https://translationproject.org/domain/{d}.html'>{d}</a></li>")
                lines.append("</ul></div>")
        else:
            sorted_langs = sorted(matrix.lang_percentages.items(), key=lambda x: x[1], reverse=True)
            
            lines.append(f"""<div class="card">
<h2>🏆 Top 20 Languages</h2>
<table><thead><tr><th>#</th><th>Language</th><th>Coverage</th><th>Progress</th></tr></thead><tbody>""")
            for i, (lang, pct) in enumerate(sorted_langs[:20], 1):
                lines.append(f"<tr><td>{i}</td><td><a href='https://translationproject.org/team/{lang}.html'>{lang}</a></td><td>{pct}%</td><td><div class='progress' style='width:150px'><div class='progress-bar' style='width:{pct}%'></div></div></td></tr>")
            lines.append("</tbody></table></div>")
            
            # Best covered packages
            lines.append(f"""<div class="card">
<h2>📦 Best Covered Packages</h2>
<table><thead><tr><th>Package</th><th>Languages</th><th>Avg Coverage</th></tr></thead><tbody>""")
            domain_coverage = [(d, len(t), sum(t.values()) / len(t) if t else 0) 
                               for d, t in matrix.domains.items()]
            domain_coverage.sort(key=lambda x: (x[1], x[2]), reverse=True)
            for d, count, avg in domain_coverage[:15]:
                lines.append(f"<tr><td><a href='https://translationproject.org/domain/{d}.html'>{d}</a></td><td>{count}</td><td>{avg:.0f}%</td></tr>")
            lines.append("</tbody></table></div>")
        
        lines.append(f"""
<footer>
    <p>Generated by <a href="https://github.com/yeager/tp-lint"><strong>tp-lint</strong></a> v{__version__}</p>
    <p>Data from <a href="https://translationproject.org">GNU Translation Project</a> · 
       Report issues on <a href="https://github.com/yeager/tp-lint/issues">GitHub</a> · 
       <a href="https://app.transifex.com/danielnylander/tp-lint/">Help translate</a></p>
    <p>© 2026 <a href="https://www.danielnylander.se">Daniel Nylander</a> · GPL-3.0-or-later</p>
</footer>
</body>
</html>""")
    
    report = "\n".join(lines)
    
    if output_file:
        Path(output_file).write_text(report, encoding="utf-8")
        print(_("Report saved to: {path}").format(path=output_file))
    else:
        print(report)
    
    return report


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


def download_po_file(url, dest_dir, verbose=False):
    """Download a PO file to the destination directory.
    
    Returns:
        tuple: (dest_path, size_bytes, elapsed_seconds) or (None, 0, 0) on error
    """
    import time as _time
    filename = url.split("/")[-1]
    dest_path = dest_dir / filename
    
    try:
        start = _time.time()
        with urllib.request.urlopen(url, timeout=60) as resp:
            content = resp.read()
        elapsed = _time.time() - start
        dest_path.write_bytes(content)
        return dest_path, len(content), elapsed
    except Exception as e:
        if verbose:
            print(_("Error downloading {url}: {error}").format(url=url, error=e), file=sys.stderr)
        return None, 0, 0


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


def check_l10n_lint():
    """Check if l10n-lint is available."""
    try:
        result = subprocess.run(["l10n-lint", "--version"], capture_output=True, text=True)
        return result.returncode == 0
    except FileNotFoundError:
        return False


class TranslatedHelpFormatter(argparse.RawDescriptionHelpFormatter):
    """Custom formatter that translates argparse default strings."""
    
    def start_section(self, heading):
        translations = {
            'positional arguments': _('positional arguments'),
            'options': _('options'),
            'optional arguments': _('options'),
        }
        heading = translations.get(heading, heading)
        super().start_section(heading)


def main():
    # Check for l10n-lint availability
    if not check_l10n_lint():
        print(_("⚠️  Warning: l10n-lint not found. Install it for linting functionality:"), file=sys.stderr)
        print(_("   sudo apt install l10n-lint"), file=sys.stderr)
        print(_("   pip install l10n-lint"), file=sys.stderr)
        print(file=sys.stderr)
    
    parser = argparse.ArgumentParser(
        prog="tp-lint",
        description=_("Lint PO files from the Translation Project (translationproject.org)"),
        add_help=False,
        epilog=_("""Examples:
  tp-lint -l                    List all available languages
  tp-lint -s                    Show global translation statistics
  tp-lint -s sv                 Show statistics for Swedish
  tp-lint sv                    Lint all Swedish PO files
  tp-lint -d coreutils sv       Lint only coreutils for Swedish
  tp-lint --no-lint sv          Download only, don't lint
  tp-lint -r sv --report-format html --report-output sv.html
                                Generate HTML report for Swedish"""),
        formatter_class=TranslatedHelpFormatter
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
        "-s", "--stats",
        nargs="?",
        const="global",
        metavar="LANG",
        help=_("Show statistics (optionally for a specific language)")
    )
    
    parser.add_argument(
        "-d", "--domain",
        metavar="PACKAGE",
        help=_("Show statistics for a specific package/domain")
    )
    
    parser.add_argument(
        "-n", "--top",
        type=int,
        default=15,
        metavar="N",
        help=_("Number of items in top lists (default: 15)")
    )
    
    parser.add_argument(
        "-r", "--report",
        nargs="?",
        const="global",
        metavar="LANG",
        help=_("Generate report (optionally for a specific language)")
    )
    
    parser.add_argument(
        "--report-format",
        choices=["markdown", "html"],
        default="markdown",
        help=_("Report format (default: markdown)")
    )
    
    parser.add_argument(
        "--report-output",
        metavar="FILE",
        help=_("Save report to file")
    )
    
    parser.add_argument(
        "-j", "--json",
        action="store_true",
        help=_("JSON output (shorthand for --format json)")
    )
    
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help=_("Suppress non-essential output (only errors)")
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
        "--no-lint",
        action="store_true",
        help=_("Download only, don't run l10n-lint")
    )
    
    parser.add_argument(
        "-t", "--by-translator",
        action="store_true",
        help=_("Group results by translator")
    )
    
    parser.add_argument(
        "-V", "--verbose",
        action="store_true",
        help=_("Show detailed progress")
    )
    
    parser.add_argument(
        "-h", "--help",
        action="help",
        help=_("Show this help message and exit")
    )
    
    parser.add_argument(
        "-v", "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help=_("Show version number and exit")
    )
    
    args = parser.parse_args()
    
    # --json shorthand
    if args.json:
        args.format = "json"
    
    # Setup verbose printing
    verbose = args.verbose
    start_time = time.time()
    
    def vprint(msg):
        if verbose:
            print(msg, file=sys.stderr)
    
    def vprint_elapsed():
        """Print elapsed time."""
        elapsed = time.time() - start_time
        vprint(_("⏱️  Total elapsed time: {elapsed:.2f}s").format(elapsed=elapsed))
    
    vprint(_("🔧 tp-lint {version} starting...").format(version=__version__))
    
    # List languages mode
    if args.list:
        vprint(_("   Mode: List languages"))
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
    
    # Report mode
    if args.report:
        vprint(_("   Mode: Generate report"))
        vprint(_("   Format: {fmt}").format(fmt=args.report_format))
        if args.report_output:
            vprint(_("   Output file: {file}").format(file=args.report_output))
        print(_("Fetching translation matrix..."))
        vprint(_("   Connecting to translationproject.org/extra/matrix.html..."))
        matrix = fetch_matrix()
        if not matrix:
            return 1
        vprint(_("   Matrix loaded: {langs} languages, {domains} domains").format(
            langs=len(matrix.languages), domains=len(matrix.domains)))
        
        lang_filter = args.report if args.report != "global" else None
        generate_report(
            matrix,
            lang_filter=lang_filter,
            output_file=args.report_output,
            report_format=args.report_format
        )
        return 0
    
    # Statistics mode (but not if -L/--lint is specified with -d)
    if args.stats or (args.domain and args.no_lint):
        vprint(_("   Mode: Statistics"))
        if args.domain:
            vprint(_("   Domain filter: {domain}").format(domain=args.domain))
        print(_("Fetching translation matrix..."))
        vprint(_("   Connecting to translationproject.org/extra/matrix.html..."))
        matrix = fetch_matrix()
        if not matrix:
            return 1
        vprint(_("   Matrix loaded: {langs} languages, {domains} domains").format(
            langs=len(matrix.languages), domains=len(matrix.domains)))
        
        lang_filter = args.stats if args.stats != "global" else None
        print_stats(
            matrix, 
            lang_filter=lang_filter, 
            domain_filter=args.domain,
            top_n=args.top,
            output_format=args.format
        )
        return 0
    
    # Require language for linting
    if not args.language:
        parser.print_help()
        return 1
    
    lang_code = args.language.lower()
    vprint(_("   Mode: Lint language '{lang}'").format(lang=lang_code))
    vprint(_("   Output format: {fmt}").format(fmt=args.format))
    vprint(_("   Strict mode: {strict}").format(strict=args.strict))
    
    # If -d is specified with -L, use it as package filter
    if args.domain and not args.no_lint:
        if not args.packages:
            args.packages = []
        args.packages.append(args.domain)
        vprint(_("   Domain filter (via -d): {domain}").format(domain=args.domain))
    
    if args.packages:
        vprint(_("   Package filter: {pkgs}").format(pkgs=", ".join(args.packages)))
    
    # Fetch PO file list and translators
    print(_("Fetching PO files for '{lang}'...").format(lang=lang_code))
    vprint(_("   Connecting to translationproject.org..."))
    po_urls, translators = get_po_files_and_translators(lang_code)
    vprint(_("   Found {count} translators assigned").format(count=len(translators)))
    
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
    vprint(_("   Output directory: {dir}").format(dir=output_dir))
    downloaded = []
    total_bytes = 0
    total_download_time = 0
    max_filename_len = 0
    download_start = time.time()
    
    for i, url in enumerate(po_urls, 1):
        filename = url.split("/")[-1]
        max_filename_len = max(max_filename_len, len(filename))
        # Clear line and print progress
        if verbose:
            vprint(_("  [{current}/{total}] {filename}").format(
                current=i, total=len(po_urls), filename=filename
            ))
        else:
            progress = _("  [{current}/{total}] {filename}").format(
                current=i, total=len(po_urls), filename=filename
            )
            sys.stdout.write(f"\r\033[K{progress}")
            sys.stdout.flush()
        path, size, elapsed = download_po_file(url, output_dir, verbose=verbose)
        if path:
            downloaded.append(path)
            total_bytes += size
            total_download_time += elapsed
            if verbose:
                speed = size / elapsed / 1024 if elapsed > 0 else 0
                vprint(_("       Size: {size} bytes, {elapsed:.2f}s ({speed:.1f} KB/s)").format(
                    size=size, elapsed=elapsed, speed=speed))
    
    download_elapsed = time.time() - download_start
    
    # Clear progress line and print completion
    if not verbose:
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()
    print(_("Downloaded {count} files").format(count=len(downloaded)))
    
    # Verbose download summary
    if verbose and downloaded:
        avg_speed = total_bytes / total_download_time / 1024 if total_download_time > 0 else 0
        vprint(_("   Total downloaded: {size:.1f} KB in {elapsed:.2f}s").format(
            size=total_bytes / 1024, elapsed=download_elapsed))
        vprint(_("   Average speed: {speed:.1f} KB/s").format(speed=avg_speed))
    
    if not downloaded:
        print(_("No files downloaded"), file=sys.stderr)
        return 1
    
    # Run l10n-lint if requested
    if not args.no_lint:
        if not check_l10n_lint():
            print(_("❌ Error: l10n-lint not found. Install it first:"), file=sys.stderr)
            print(_("   sudo apt install l10n-lint"), file=sys.stderr)
            print(_("   pip install l10n-lint"), file=sys.stderr)
            return 1
        
        print()
        print(_("Running l10n-lint..."))
        vprint(_("   By translator: {by_translator}").format(by_translator=args.by_translator))
        vprint(_("   Files to lint: {count}").format(count=len(downloaded)))
        print("=" * 60)
    
    if not args.no_lint and args.by_translator:
        # Group results by translator
        lint_results = run_l10n_lint_per_file(downloaded, args.format, args.strict, _lang_code)
        
        # Group by translator
        translator_results = {}
        for filename, data in lint_results.items():
            domain = get_domain_from_filename(filename)
            translator = translators.get(domain, _("Unknown"))
            if translator not in translator_results:
                translator_results[translator] = {"files": [], "errors": 0, "warnings": 0, "fuzzy": 0}
            translator_results[translator]["files"].append(filename)
            
            issues = data.get("issues", [])
            for issue in issues:
                if issue.get("rule") == "fuzzy":
                    translator_results[translator]["fuzzy"] += 1
                elif issue.get("severity") == "error":
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
            print(_("   Fuzzy: {count}").format(count=stats["fuzzy"]))
            print(_("   Warnings: {count}").format(count=stats["warnings"]))
            print()
        
        # Summary
        total_errors = sum(s["errors"] for s in translator_results.values())
        total_fuzzy = sum(s["fuzzy"] for s in translator_results.values())
        total_warnings = sum(s["warnings"] for s in translator_results.values())
        print("=" * 60)
        print(_("Total: {files} files, {errors} errors, {fuzzy} fuzzy, {warnings} warnings").format(
            files=len(downloaded), errors=total_errors, fuzzy=total_fuzzy, warnings=total_warnings
        ))
        
        returncode = 2 if total_errors > 0 else (1 if total_warnings > 0 or (args.strict and total_fuzzy > 0) else 0)
    elif not args.no_lint:
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
    else:
        # No linting requested, just download
        print()
        print(_("✅ Downloaded {count} files to {path}").format(count=len(downloaded), path=output_dir))
        print(_("   Run with --lint to check for issues"))
        returncode = 0
    
    # Cleanup
    if not keep_files and temp_dir:
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
    elif keep_files:
        print()
        print(_("PO files saved to: {path}").format(path=output_dir))
    
    vprint_elapsed()
    return returncode


if __name__ == "__main__":
    sys.exit(main())
