# Jupyter Notebook (.ipynb) Interaction Protocol

## Core Problem

`.ipynb` files are JSON with heavy bloat: base64-encoded images, execution counts,
output blobs, and metadata. A notebook with a few plots can exceed **250,000 characters**.
Never read or write `.ipynb` files directly — always use the strategies below.

---

## Strategy Hierarchy (use in this order)

### 1. STRIP → READ (for inspection/understanding)

Before reading any `.ipynb`, extract only what matters using a one-liner bash script.
Never pass raw `.ipynb` content into context.

```bash
# Extract code + markdown source only, no outputs, no base64
python3 -c "
import json, sys
nb = json.load(open('$NOTEBOOK'))
for i, cell in enumerate(nb['cells']):
    src = ''.join(cell['source'])
    print(f'--- Cell {i} [{cell[\"cell_type\"]}] ---')
    print(src)
    print()
" > /tmp/nb_stripped.txt
cat /tmp/nb_stripped.txt
```

This reduces a 250k-character notebook to ~5-15k characters (94%+ reduction).
Read `/tmp/nb_stripped.txt` — never the `.ipynb` directly.

**When to use:** Understanding structure, auditing code, searching for logic.

---

### 2. CELL-TARGETED JSON PATCH (for editing)

Never rewrite the whole notebook. Surgically patch only the target cell using Python
in `/tmp` — preserves all metadata, kernelspec, outputs, and cell IDs.

```bash
python3 /tmp/nb_patch.py
```

Write the patch script first, then execute it:

```python
# /tmp/nb_patch.py — always generate this before editing
import json, copy

NOTEBOOK = "path/to/notebook.ipynb"
CELL_INDEX = 3  # 0-indexed

NEW_SOURCE = """# your new cell content here
x = 42
print(x)
"""

with open(NOTEBOOK, 'r') as f:
    nb = json.load(f)

nb['cells'][CELL_INDEX]['source'] = NEW_SOURCE
# Preserve outputs and execution_count — only touch source
# nb['cells'][CELL_INDEX]['outputs'] = []  # optionally clear outputs

with open(NOTEBOOK, 'w') as f:
    json.dump(nb, f, indent=1)

print(f"Patched cell {CELL_INDEX} in {NOTEBOOK}")
```

**When to use:** Editing existing cells — the primary write method.

---

### 3. NBFORMAT APPEND/INSERT (for adding cells)

To insert or append cells without touching existing ones:

```python
# /tmp/nb_insert.py
import json

NOTEBOOK = "path/to/notebook.ipynb"
INSERT_AFTER = 2  # insert after this cell index

new_cell = {
    "cell_type": "code",
    "execution_count": None,
    "metadata": {},
    "outputs": [],
    "source": "# new cell\nprint('hello')"
}

with open(NOTEBOOK, 'r') as f:
    nb = json.load(f)

nb['cells'].insert(INSERT_AFTER + 1, new_cell)

with open(NOTEBOOK, 'w') as f:
    json.dump(nb, f, indent=1)
```

---

### 4. CONVERT → EDIT → RECONVERT (for large structural refactors)

For wholesale refactors (restructuring sections, renaming many cells):

```bash
# Convert to .py, edit cleanly, convert back
jupyter nbconvert --to script notebook.ipynb --output /tmp/nb_edit
# edit /tmp/nb_edit.py
jupytext --to notebook /tmp/nb_edit.py -o notebook_new.ipynb
```

Requires `jupytext` (has been installed). Only use when patching individual cells
would require 5+ separate patch operations.

---

## What to NEVER Do

| Action | Why Forbidden |
|---|---|
| `Read("notebook.ipynb")` | Dumps full JSON including base64 images into context |
| `Write("notebook.ipynb", full_content)` | Requires entire file in context to rewrite |
| `cat notebook.ipynb` | Same as Read — massive token waste |
| Regex-editing raw `.ipynb` | Breaks JSON structure, corrupts cell IDs |
| Reading outputs/plots | Base64 images = thousands of tokens per cell |

---

## Cell Index Discovery (when you don't know the index)

```bash
python3 -c "
import json
nb = json.load(open('notebook.ipynb'))
for i, c in enumerate(nb['cells']):
    preview = ''.join(c['source'])[:80].replace('\n',' ')
    print(f'[{i}] {c[\"cell_type\"]}: {preview}')
"
```

This gives a compact cell map — use it to find target indices before patching.
Costs ~200 tokens instead of 250,000.

---

## Permissions (add to .claude/settings.json)

```json
{
  "permissions": {
    "allowedTools": [
      "Bash(python3 /tmp/nb_*.py)",
      "Bash(python3 -c *)",
      "Bash(jupyter nbconvert *)",
      "Bash(jupytext *)",
      "Read(/tmp/nb_stripped.txt)"
    ],
    "deny": [
      "Read(*.ipynb)",
      "Write(*.ipynb)"
    ]
  }
}
```

This enforces the protocol automatically — Claude cannot accidentally `Read` a raw
`.ipynb`, and all notebook interaction flows through `/tmp` scripts.

**If any of the command/ method did not or have any implications/ high probabilties that does not suite in certain situation, bypass the forcable requirements in this section and ask user for further considerations**