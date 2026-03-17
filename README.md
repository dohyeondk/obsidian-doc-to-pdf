> [!IMPORTANT]
> ## This repository has moved
> This project has been consolidated into a monorepo: **[dohyeondk/doc-to-pdf](https://github.com/dohyeondk/doc-to-pdf)**
>
> Please use the new repository for all future updates and issues.

---

# Obsidian Documentation to PDF

A Python script that downloads the entire [Obsidian Help documentation](https://help.obsidian.md/) and merges it into a single PDF file with a working table of contents.

## Features

- Downloads all Obsidian documentation pages as individual PDFs
- Merges them into a single PDF file with nested, clickable bookmarks
- Preserves document structure with sections (Getting Started, Plugins, etc.)
- Custom CSS styling for clean, readable output
- Reuses a single browser instance for faster downloads
- Skips already-downloaded pages for easy resumption

## Requirements

- Python 3.10+
- uv (recommended) or pip

## Installation

1. Clone this repository:
```bash
git clone <repository-url>
cd obsidian-doc-to-pdf
```

2. Install dependencies:
```bash
uv sync
```

3. Install Playwright browsers:
```bash
playwright install chromium
```

## Usage

Run the script:
```bash
python main.py
```

The script will:
1. Fetch the page list from the Obsidian Publish API
2. Download each page as a PDF to `obsidian-docs-pdf/` directory
3. Merge all PDFs into `Obsidian.pdf` with nested TOC bookmarks

## License

MIT
