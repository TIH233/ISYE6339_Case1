# PDF File Interaction Protocol

## Core Problem

PDFs are binary files containing embedded fonts, images, vector graphics, and metadata.
Reading them directly is meaningless (binary garbage). Passing them through Claude's
Read tool or `cat` wastes tokens on unreadable bytes. Even extracted text can be bloated
with repeated headers, footers, page numbers, and whitespace on every page.

**Never interact with PDF files directly. Always extract → filter → act.**

---

## Strategy Hierarchy (use in this order)

### 1. TEXT EXTRACT → STRIP (for reading/understanding)

Extract clean text only — no layout artifacts, no repeated headers/footers.

```bash
# Install once
pip install pymupdf --break-system-packages  # fastest, most accurate

# Extract clean text to /tmp
python3 -c "
import fitz  # pymupdf
doc = fitz.open('path/to/file.pdf')
text = '\n\n--- Page {i+1} ---\n'.join(
    page.get_text('text') for i, page in enumerate(doc)
)
with open('/tmp/pdf_extracted.txt', 'w') as f:
    f.write(text)
print(f'Extracted {len(doc)} pages, {len(text)} chars')
"
cat /tmp/pdf_extracted.txt
```

For even leaner output, strip repeated headers/footers (common in reports/books):

```python
# /tmp/pdf_clean.py — strips repeated lines appearing on 80%+ of pages
import fitz, collections

doc = fitz.open("path/to/file.pdf")
pages = [page.get_text("text").splitlines() for page in doc]

# Find lines repeated across many pages (headers/footers)
all_lines = [line.strip() for page in pages for line in page if line.strip()]
freq = collections.Counter(all_lines)
noise = {line for line, count in freq.items() if count >= len(pages) * 0.8}

cleaned = []
for i, page in enumerate(pages):
    body = [l for l in page if l.strip() and l.strip() not in noise]
    if body:
        cleaned.append(f"--- Page {i+1} ---\n" + "\n".join(body))

with open("/tmp/pdf_clean.txt", "w") as f:
    f.write("\n\n".join(cleaned))

print(f"Done. {len(cleaned)} pages written.")
```

**When to use:** Reading reports, extracting content, answering questions about a PDF.

---

### 2. PAGE-TARGETED EXTRACT (when you only need specific pages)

Never extract the whole PDF if you only need a section.

```bash
python3 -c "
import fitz
doc = fitz.open('path/to/file.pdf')
pages = range(4, 12)  # 0-indexed, so pages 5-12 in human terms
text = '\n\n'.join(doc[i].get_text('text') for i in pages)
with open('/tmp/pdf_pages.txt', 'w') as f:
    f.write(text)
"
cat /tmp/pdf_pages.txt
```

For even faster lookup — get the page count and a 1-line preview per page first:

```bash
python3 -c "
import fitz
doc = fitz.open('path/to/file.pdf')
print(f'Total pages: {len(doc)}')
for i, page in enumerate(doc):
    first_line = page.get_text('text').split('\n')[0][:100]
    print(f'  [{i}] {first_line}')
"
```

This costs ~500 tokens and tells you exactly which pages to target.

---

### 3. TABLE EXTRACT (for structured data)

When the PDF contains tables, extract as CSV — far cheaper than reading prose with
embedded table text.

```bash
pip install pdfplumber --break-system-packages

python3 -c "
import pdfplumber, csv, sys

with pdfplumber.open('path/to/file.pdf') as pdf:
    with open('/tmp/pdf_tables.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        for i, page in enumerate(pdf.pages):
            for table in page.extract_tables():
                writer.writerow([f'--- Page {i+1} Table ---'])
                writer.writerows(table)
"
cat /tmp/pdf_tables.csv
"

---

### 4. TARGETED SEARCH (when you know what you're looking for)

Don't read the whole PDF to find one fact. Search by keyword:

```bash
python3 -c "
import fitz, sys
doc = fitz.open('path/to/file.pdf')
query = 'revenue'  # change this

for i, page in enumerate(doc):
    text = page.get_text('text')
    if query.lower() in text.lower():
        # Print only the surrounding context (~5 lines)
        lines = text.splitlines()
        for j, line in enumerate(lines):
            if query.lower() in line.lower():
                ctx = lines[max(0,j-2):j+3]
                print(f'Page {i+1}, line ~{j}:')
                print('\n'.join(ctx))
                print()
"
```

Costs near-zero tokens. Use before any full extraction.

---

### 5. PDF MODIFICATION (editing metadata, merging, splitting)

For write operations, always script via `/tmp` — never reconstruct the PDF manually.

**Merge PDFs:**
```python
# /tmp/pdf_merge.py
import fitz
docs = ["a.pdf", "b.pdf", "c.pdf"]
out = fitz.open()
for path in docs:
    out.insert_pdf(fitz.open(path))
out.save("/tmp/merged.pdf")
print("Saved merged.pdf")
```

**Extract pages to new PDF:**
```python
# /tmp/pdf_split.py
import fitz
doc = fitz.open("path/to/file.pdf")
out = fitz.open()
out.insert_pdf(doc, from_page=4, to_page=11)  # 0-indexed
out.save("/tmp/extracted_pages.pdf")
```

**Add text/annotation to a page:**
```python
# /tmp/pdf_annotate.py
import fitz
doc = fitz.open("path/to/file.pdf")
page = doc[0]  # first page
page.insert_text((72, 72), "DRAFT", fontsize=48, color=(1, 0, 0))
doc.save("/tmp/annotated.pdf")
```

---

### 6. OCR FALLBACK (for scanned/image-only PDFs)

If `get_text()` returns empty strings, the PDF is image-based. Use OCR:

```bash
pip install pymupdf pytesseract pillow --break-system-packages
# Also: sudo apt-get install tesseract-ocr

python3 -c "
import fitz
from PIL import Image
import pytesseract, io

doc = fitz.open('path/to/scanned.pdf')
with open('/tmp/pdf_ocr.txt', 'w') as f:
    for i, page in enumerate(doc):
        pix = page.get_pixmap(dpi=200)
        img = Image.open(io.BytesIO(pix.tobytes('png')))
        text = pytesseract.image_to_string(img)
        f.write(f'--- Page {i+1} ---\n{text}\n\n')
print('OCR complete')
"
cat /tmp/pdf_ocr.txt
```

Only use OCR when standard extraction returns empty. It is slower but necessary for
scanned documents.

---

## What to NEVER Do

| Action | Why Forbidden |
|---|---|
| `Read("file.pdf")` | Binary content — unreadable garbage in context |
| `cat file.pdf` | Same — binary dump, wastes tokens entirely |
| `Write("file.pdf", content)` | PDFs are binary; text writes corrupt the file |
| Passing whole PDF text without filtering | Headers/footers repeat every page, inflating tokens 3-5x |
| Reading image-heavy PDFs without stripping images | Embedded images bloat extracted text with artifact characters |

---

## Tool Detection (check what's available before starting)

```bash
python3 -c "
tools = {}
try: import fitz; tools['pymupdf'] = fitz.__version__
except: tools['pymupdf'] = 'not installed'
try: import pdfplumber; tools['pdfplumber'] = 'ok'
except: tools['pdfplumber'] = 'not installed'
try: import pytesseract; tools['pytesseract'] = 'ok'
except: tools['pytesseract'] = 'not installed'
print(tools)
"
```

Install only what you need. `pymupdf` covers 90% of cases.

---

## Permissions (add to .claude/settings.json)

```json
{
  "permissions": {
    "allowedTools": [
      "Bash(python3 /tmp/pdf_*.py)",
      "Bash(python3 -c *)",
      "Bash(pip install pymupdf*)",
      "Bash(pip install pdfplumber*)",
      "Bash(pip install pytesseract*)",
      "Read(/tmp/pdf_*.txt)",
      "Read(/tmp/pdf_*.csv)"
    ],
    "deny": [
      "Read(*.pdf)",
      "Write(*.pdf)"
    ]
  }
}
```

---

## Quick Reference

| Task | Method | Temp Output |
|---|---|---|
| Read/understand PDF | `pymupdf` text extract → strip headers | `/tmp/pdf_clean.txt` |
| Find specific info | Keyword search one-liner | stdout only |
| Read specific pages | Page-targeted extract | `/tmp/pdf_pages.txt` |
| Extract tables | `pdfplumber` → CSV | `/tmp/pdf_tables.csv` |
| Page map / navigation | Page count + first-line preview | stdout only |
| Merge PDFs | `pymupdf` insert_pdf script | `/tmp/merged.pdf` |
| Split/extract pages | `pymupdf` insert_pdf range | `/tmp/extracted_pages.pdf` |
| Annotate/watermark | `pymupdf` insert_text script | `/tmp/annotated.pdf` |
| Scanned PDF (no text) | OCR via pytesseract | `/tmp/pdf_ocr.txt` |
| Read raw `.pdf` | ❌ NEVER | — |
