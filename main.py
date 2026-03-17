import requests
from playwright.sync_api import sync_playwright
import os
import re
from pypdf import PdfWriter, PdfReader


# Obsidian Publish site configuration
SITE_UID = "f786db9fac45774fa4f0d8112e232d67"
BASE_URL = "https://help.obsidian.md"
OPTIONS_API = f"https://publish-01.obsidian.md/options/{SITE_UID}"
CACHE_API = f"https://publish-01.obsidian.md/cache/{SITE_UID}"

# Minimal CSS — only hides non-content chrome; keeps all site fonts/styles intact
custom_css = """
.site-body-left-column,
.site-body-right-column,
.site-header,
.site-footer,
.graph-view-container,
.backlinks,
.mod-footer,
.outline-view-container,
.site-body-left-column-site-name,
.published-search-container,
.published-search-input-container,
.theme-toggle-input-container,
.nav-header,
.nav-folder,
.nav-file,
.site-component-navbar,
.extra-title {
    display: none !important;
}

.callout.is-collapsed {
    height: auto !important;
    overflow: visible !important;
}
.callout.is-collapsed .callout-content {
    display: block !important;
}

.site-body-center-column {
    margin: 0 auto !important;
    padding: 0 20px !important;
}
"""

# JS that runs on the live page before PDF export.  Removes non-content
# DOM nodes and stretches the viewport-locked containers to fit content
# so Chromium's PDF renderer doesn't create trailing blank pages.
PREPARE_FOR_PRINT_JS = """() => {
    // Remove non-content elements
    const removeSelectors = [
        '.site-body-left-column', '.site-body-right-column',
        '.site-header', '.site-footer', '.graph-view-container',
        '.backlinks', '.mod-footer', '.outline-view-container',
        '.extra-title', '.site-component-navbar',
        '.published-search-container', '.nav-header',
    ];
    for (const sel of removeSelectors) {
        document.querySelectorAll(sel).forEach(el => el.remove());
    }

    // Unlock overflow on every wrapper so nothing is clipped.
    const containers = document.querySelectorAll(
        '.published-container, .site-body, ' +
        '.site-body-center-column, .render-container, ' +
        '.render-container-inner, .publish-renderer, ' +
        '.markdown-preview-view, .markdown-rendered, ' +
        '.markdown-preview-sizer'
    );
    for (const el of containers) {
        el.style.setProperty('overflow', 'visible', 'important');
    }
}"""


def make_toc_entry(path):
    """Build a TOC item dict from a page path like 'Folder/Page.md'."""
    title = path.rsplit("/", 1)[-1].removesuffix(".md")
    url_path = path.removesuffix(".md").replace(" ", "+")
    section = path.split("/")[0] if "/" in path else None
    return {
        "type": "page",
        "title": title,
        "url": f"{BASE_URL}/{url_path}",
        "section": section,
        "path": path,
    }


def make_section_entry(folder_name):
    """Build a TOC item for a section title page (no URL)."""
    title = folder_name.rsplit("/", 1)[-1]
    return {
        "type": "section",
        "title": title,
        "url": None,
        "section": folder_name.split("/")[0],
        "path": folder_name,
    }


def get_obsidian_toc_items():
    """
    Get the ordered list of documentation pages from the Obsidian Publish API.
    Preserves the exact navigation ordering.  Folder entries become section
    title pages; .md entries that follow a folder are kept in order.  For
    folders whose children are NOT listed individually in the nav ordering,
    children are fetched from the cache API (sorted alphabetically).
    """
    response = requests.get(OPTIONS_API)
    response.raise_for_status()
    options = response.json()

    cache_response = requests.get(CACHE_API)
    cache_response.raise_for_status()
    all_cache_pages = set(cache_response.json().keys())

    nav_ordering = options.get("navigationOrdering", [])
    hidden_items = set(options.get("navigationHiddenItems", []))

    # Non-content files/folders to skip
    skip_prefixes = ("Attachments", "favicon", "publish.")
    skip_exact = {"Home.md"}

    # Pre-scan: figure out which folder entries have explicit .md children
    # listed after them in the nav ordering so we know when to fall back
    # to the cache API.
    nav_set = set(nav_ordering)

    toc_items = []
    seen = set()

    for entry in nav_ordering:
        if entry.endswith(".md"):
            # Page entry — add it in the order it appears
            if entry in hidden_items or entry in skip_exact:
                continue
            if any(entry.startswith(p) for p in skip_prefixes):
                continue
            if entry in seen:
                continue
            seen.add(entry)
            toc_items.append(make_toc_entry(entry))
        else:
            # Folder entry — skip non-content folders
            if any(entry.startswith(p) for p in skip_prefixes):
                continue

            # Add a section title page
            toc_items.append(make_section_entry(entry))

            # Check if this folder's children are explicitly listed in nav.
            # If so, they'll be picked up in subsequent loop iterations.
            folder_prefix = entry + "/"
            has_explicit_children = any(
                e.startswith(folder_prefix) and e.endswith(".md")
                for e in nav_set
            )

            if not has_explicit_children:
                # Fall back: fetch children from cache, sorted alphabetically
                child_pages = sorted(
                    p for p in all_cache_pages
                    if p.startswith(folder_prefix)
                    and p.endswith(".md")
                    and p not in hidden_items
                    and p not in seen
                )
                for child in child_pages:
                    if any(child.startswith(p) for p in skip_prefixes):
                        continue
                    seen.add(child)
                    toc_items.append(make_toc_entry(child))

    return toc_items


def sanitize_filename(filename):
    """Remove invalid characters from filename."""
    return re.sub(r'[<>:"/\\|?*]', '', filename)


def get_pdf_filename(index, item):
    """Generate PDF filename from index and TOC item."""
    title = sanitize_filename(item["title"])
    return f"{index:03d}. {title}.pdf"


def generate_section_title_pdf(title, output_path, browser):
    """Generate a single-page PDF with a centered section title."""
    if os.path.exists(output_path):
        return False

    page = browser.new_page()
    try:
        page.set_content(f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  html, body {{
    margin: 0; padding: 0;
    height: 100%;
    display: flex; align-items: center; justify-content: center;
    font-family: ui-sans-serif, -apple-system, system-ui, sans-serif;
    background: #fff;
  }}
  h1 {{
    font-size: 36px;
    font-weight: 600;
    color: #222;
    text-align: center;
  }}
</style>
</head><body><h1>{title}</h1></body></html>""", wait_until="load")
        page.pdf(
            path=output_path,
            format="Letter",
            margin={"top": "0.25in", "right": "0.25in",
                    "bottom": "0.25in", "left": "0.25in"},
            print_background=True,
        )
    finally:
        page.close()
    return True


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

        # Wait for content to fully render (lazy-loaded images, embeds, etc.)
        page.wait_for_function(
            """() => {
                const sizer = document.querySelector('.markdown-preview-sizer');
                return sizer && sizer.scrollHeight > 100;
            }""",
            timeout=10000,
        )

        # Inject our CSS overrides
        page.add_style_tag(content=custom_css)

        # Remove non-content DOM and unlock overflow, preserving all
        # site styling (callout colors, code blocks, theme, backgrounds).
        page.evaluate(PREPARE_FOR_PRINT_JS)
        page.wait_for_timeout(500)

        # Generate PDF — scale down to match the site's readable line width
        # proportionally on a Letter page (site renders at ~620px content
        # width; Letter printable area is ~730px at 96 dpi → 0.85 scale).
        page.pdf(
            path=output_path,
            format="Letter",
            margin={
                "top": "0.45in",
                "right": "0.25in",
                "bottom": "0.45in",
                "left": "0.25in",
            },
            print_background=True,
            scale=0.85,
        )
    finally:
        page.close()

    # Strip trailing blank pages left by the SPA's viewport-height containers
    _strip_trailing_blank_pages(output_path)

    return True


def _strip_trailing_blank_pages(pdf_path):
    """Remove trailing pages that have no text and no images."""
    reader = PdfReader(pdf_path)
    pages = reader.pages
    if len(pages) <= 1:
        return

    # Walk backwards to find first non-empty page
    last_good = len(pages) - 1
    while last_good > 0:
        pg = pages[last_good]
        text = (pg.extract_text() or "").strip()
        has_images = bool(pg.images) if hasattr(pg, "images") else False
        has_xobjects = bool(pg.get("/Resources", {}).get("/XObject"))
        if text or has_images or has_xobjects:
            break
        last_good -= 1

    if last_good == len(pages) - 1:
        return  # nothing to strip

    writer = PdfWriter()
    for i in range(last_good + 1):
        writer.add_page(pages[i])
    with open(pdf_path, "wb") as f:
        writer.write(f)


def merge_pdfs_with_toc(toc_items, output_dir, output_path):
    """
    Merge multiple PDFs into a single file with a working table of contents.
    Groups bookmarks by section.
    """
    writer = PdfWriter()

    print("\nMerging PDFs with table of contents...")

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

            if item["type"] == "section":
                # Section title page gets a top-level bookmark
                section_bookmark = writer.add_outline_item(
                    item["title"], start_page
                )
            else:
                # Content page — nested under current section if applicable
                parent = section_bookmark if item["section"] else None
                writer.add_outline_item(
                    item["title"], start_page, parent=parent
                )

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

                if item["type"] == "section":
                    print(f"[{i}/{len(items)}] Section: {item['title']}")
                    try:
                        created = generate_section_title_pdf(
                            item["title"], output_path, browser
                        )
                        if created:
                            print("    ✓ Created section page\n")
                        else:
                            print("    ↷ Skipped (already exists)\n")
                    except Exception as e:
                        print(f"    ✗ Error: {e}\n")
                else:
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
