import requests
from playwright.sync_api import sync_playwright
import os
import re
from pypdf import PdfWriter, PdfReader


# Obsidian Publish site configuration
SITE_UID = "f786db9fac45774fa4f0d8112e232d67"
BASE_URL = "https://help.obsidian.md"
OPTIONS_API = f"https://publish-01.obsidian.md/options/{SITE_UID}"

# Custom CSS for PDF generation
custom_css = """
/* Hide navigation, sidebars, and non-content elements */
.site-body-left-column,
.site-body-right-column,
.site-header,
.site-footer,
.graph-view-container,
.backlinks,
.outline-view-container,
.site-body-left-column-site-name,
.published-search-container,
.published-search-input-container,
.theme-toggle-input-container,
.nav-header,
.nav-folder,
.nav-file,
.site-component-navbar {
    display: none !important;
}

/* Remove layout constraints so content fills the page */
body, .published-container {
    height: inherit;
    overflow: inherit;
}

.site-body {
    display: block !important;
}

.site-body-center-column {
    max-width: 100% !important;
    margin: 0 !important;
    padding: 0 !important;
    width: 100% !important;
}

/* Typography */
.markdown-rendered {
    font-family: "Helvetica Neue", sans-serif;
    font-weight: 400;
}

h1, h2, h3, h4, h5, h6 {
    font-family: "Georgia", serif !important;
}

code {
    font-family: "Menlo", monospace !important;
}

.markdown-rendered, blockquote > p, table {
    font-size: 0.8em;
}
"""


def get_obsidian_toc_items():
    """
    Get the ordered list of documentation pages from the Obsidian Publish API.
    Returns only actual page entries (ending in .md), excluding section headers,
    hidden items, attachments, and non-content files.
    """
    response = requests.get(OPTIONS_API)
    response.raise_for_status()
    options = response.json()

    nav_ordering = options.get("navigationOrdering", [])
    hidden_items = set(options.get("navigationHiddenItems", []))

    # Non-content files/folders to skip
    skip_prefixes = ("Attachments", "favicon", "publish.")
    skip_exact = {"Home.md"}

    toc_items = []
    seen = set()

    for entry in nav_ordering:
        # Only process .md files (skip section headers like "Getting started")
        if not entry.endswith(".md"):
            continue

        # Skip hidden, attachment, and non-content items
        if entry in hidden_items or entry in skip_exact:
            continue
        if any(entry.startswith(p) for p in skip_prefixes):
            continue
        if entry in seen:
            continue

        seen.add(entry)

        # Build title from filename
        title = entry.rsplit("/", 1)[-1].removesuffix(".md")

        # Build URL: remove .md, encode spaces as +
        url_path = entry.removesuffix(".md").replace(" ", "+")
        full_url = f"{BASE_URL}/{url_path}"

        # Determine section from folder path
        section = entry.split("/")[0] if "/" in entry else None

        toc_items.append({
            "title": title,
            "url": full_url,
            "section": section,
            "path": entry,
        })

    return toc_items


def sanitize_filename(filename):
    """Remove invalid characters from filename."""
    return re.sub(r'[<>:"/\\|?*]', '', filename)


def get_pdf_filename(index, item):
    """Generate PDF filename from index and TOC item."""
    title = sanitize_filename(item["title"])
    return f"{index:03d}. {title}.pdf"


def download_page_as_pdf(url, output_path, custom_css, browser):
    """Download a web page as PDF with custom CSS using an existing browser instance."""
    if os.path.exists(output_path):
        return False

    page = browser.new_page()

    try:
        # Navigate to the page and wait for content to render
        page.goto(url, wait_until="networkidle")

        # Wait for the main content to appear (Obsidian Publish is an SPA)
        page.wait_for_selector(".markdown-rendered", timeout=15000)

        # Inject custom CSS
        page.add_style_tag(content=custom_css)

        # Small delay for CSS to take effect
        page.wait_for_timeout(300)

        # Generate PDF
        page.pdf(
            path=output_path,
            format="Letter",
            margin={
                "top": "0.45in",
                "right": "0.45in",
                "bottom": "0.45in",
                "left": "0.45in",
            },
            print_background=False,
        )
    finally:
        page.close()

    return True


def merge_pdfs_with_toc(toc_items, output_dir, output_path):
    """
    Merge multiple PDFs into a single file with a working table of contents.
    Groups bookmarks by section.
    """
    writer = PdfWriter()

    print("\nMerging PDFs with table of contents...")

    current_section = None
    section_bookmark = None

    for i, item in enumerate(toc_items, 1):
        pdf_path = os.path.join(output_dir, get_pdf_filename(i, item))

        if not os.path.exists(pdf_path):
            print(f"    ⚠ Skipping missing file: {pdf_path}")
            continue

        try:
            reader = PdfReader(pdf_path)
            start_page = len(writer.pages)

            for page in reader.pages:
                writer.add_page(page)

            # Create section bookmark if entering a new section
            if item["section"] and item["section"] != current_section:
                current_section = item["section"]
                section_bookmark = writer.add_outline_item(
                    current_section, start_page
                )

            # Add page bookmark (nested under section if applicable)
            parent = section_bookmark if item["section"] else None
            writer.add_outline_item(item["title"], start_page, parent=parent)

            print(
                f"    [{i}/{len(toc_items)}] Added: {item['title']} (page {start_page + 1})"
            )

        except Exception as e:
            print(f"    ✗ Error merging {pdf_path}: {e}")

    total_pages = len(writer.pages)

    writer.add_metadata({
        "/Title": "Obsidian Help Documentation",
        "/Author": "Obsidian",
    })

    print(f"\n✓ Created TOC with {len(toc_items)} entries")

    with open(output_path, "wb") as output_file:
        writer.write(output_file)

    print(f"✓ Merged PDF saved to: {output_path}")
    print(f"  Total pages: {total_pages}")

    return output_path


def main():
    output_dir = "obsidian-docs-pdf"
    merged_output = "Obsidian.pdf"

    os.makedirs(output_dir, exist_ok=True)

    print("Fetching Obsidian documentation page list...\n")

    try:
        items = get_obsidian_toc_items()
        print(f"Found {len(items)} pages\n")

        # Download each page as PDF (reuse a single browser instance)
        with sync_playwright() as p:
            browser = p.chromium.launch()

            for i, item in enumerate(items, 1):
                filename = get_pdf_filename(i, item)
                output_path = os.path.join(output_dir, filename)

                print(f"[{i}/{len(items)}] Downloading: {item['title']}")
                print(f"    URL: {item['url']}")
                print(f"    Saving to: {filename}")

                try:
                    downloaded = download_page_as_pdf(
                        item["url"], output_path, custom_css, browser
                    )
                    if downloaded:
                        print("    ✓ Success\n")
                    else:
                        print("    ↷ Skipped (already exists)\n")
                except Exception as e:
                    print(f"    ✗ Error: {e}\n")

            browser.close()

        print(f"\nAll PDFs saved to: {output_dir}/")

        # Merge all PDFs into a single file with TOC
        merge_pdfs_with_toc(items, output_dir, merged_output)

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
