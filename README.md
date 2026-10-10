# ChoboPDF

English | [한국어](README.ko.md)

A Windows desktop tool for reordering, rotating, deleting and merging the pages of very large PDFs (hundreds of MB) while looking at their thumbnails.

Editing only changes an in-memory page list, and the PDF is written once, when you save. Moving, rotating and deleting pages is therefore immediate even in a big file.

The user interface is in Korean.

## Features

- **Page editing**: drag to reorder, delete, rotate 90° left or right, cut/copy/paste, duplicate. Works on multi-page selections, and every edit can be undone.
- **Page marks**: put a bookmark ribbon on the top right corner of the pages you are working around, so you do not lose track of them while moving and deleting others. A mark follows its page and is never written to the PDF.
- **Merging files**: open several PDFs at once and they are joined in file-name order. Numbers are compared by value, so `2.pdf` comes before `10.pdf`.
- **Adding a PDF**: insert the pages of another PDF into the open document. Drop a file from Explorer between two thumbnails to insert it there.
- **Preview**: double-click a page to split the window and show that page large on the right, with 25–400% zoom, fit width and fit page.
- **Thumbnail zoom**: 100–200%, with the status bar slider or Ctrl+wheel.
- **Save as a copy**: saving an opened file asks whether to overwrite it or save a copy. A copy is written to another file while you keep working on the original.
- **Pages as JPG**: right-click the selected pages to save them as JPG images (200 DPI), in the rotation shown.
- **Safe saving**: the file is written in the background to a temporary file that then replaces the target, so a failed or cancelled save leaves the existing file untouched. Shows progress and can be cancelled.

## Install and run

Requires Python 3.12 or later.

```bat
python -m venv .venv
.venv\Scripts\python -m pip install -e .[dev]
.venv\Scripts\python -m chobopdf [file.pdf ...]
```

Passing several files opens them as one merged document.

### Building a single exe

```bat
build_exe.bat
```

Uses PyInstaller to build `dist\ChoboPDF.exe` (one file, no console window). Needs the `.venv` created above.

## Usage

### Files

| Action | How |
| --- | --- |
| Open | `Ctrl+O`, or drop a PDF on the window |
| Merge several files | `Ctrl+M`, or select several files in Open |
| Add a PDF to the open document | `Ctrl+I` (after the selected pages, or at the end if nothing is selected), or drop it between thumbnails |
| Save (asks: overwrite the original, or save a copy) | `Ctrl+S` |
| Save as (continues in the new file) | `Ctrl+Shift+S` |
| Save a copy (the open document stays as it is) | `Ctrl+Alt+S` |
| Save the selected pages as JPG | `Ctrl+J`, or right-click the pages |
| Quit | `Ctrl+Q` |

A merged document has no file of its own yet, so `Ctrl+S` asks for a name.

Saving a copy does not count as saving the document: the title keeps its `*` until the document itself is saved. A copy cannot be written over a file whose pages are currently open.

With one page selected, JPG export asks for a file name; with several, it asks for a folder and names the files `<document>_<page number>.jpg`.

### Editing pages

The same commands are in the Edit menu and in the thumbnail context menu.

| Action | Shortcut |
| --- | --- |
| Undo / redo | `Ctrl+Z` / `Ctrl+Y`, `Ctrl+Shift+Z` |
| Cut / copy / paste | `Ctrl+X` / `Ctrl+C` / `Ctrl+V` |
| Duplicate | `Ctrl+D` |
| Delete | `Del` |
| Rotate right / left | `R` / `Shift+R` |
| Select all | `Ctrl+A` |
| Mark / unmark the selected pages | `M` |
| Go to the next / previous mark | `N` / `Shift+N` |
| Clear all marks | `Ctrl+Shift+M` |
| Reorder | Drag the selected thumbnails to the new position |
| Thumbnail size | `Ctrl+wheel` over the thumbnails, or the status bar slider |

Marks are only a reminder while editing: setting one does not count as a change and is not undone by `Ctrl+Z`. They stay on their pages through moves, undo and saving, are not copied to duplicated or pasted pages, and are gone once the file is closed.

### Preview

| Action | How |
| --- | --- |
| Open | Double-click a page |
| Close | `Esc`, or the ✕ button |
| Zoom in / out | `Ctrl++` / `Ctrl+-`, `Ctrl+wheel`, or the ＋ / － buttons |
| Fit width | `Ctrl+0`, or the "폭 맞춤" button |
| Fit page (the whole page on screen) | `Ctrl+9`, or the "쪽 맞춤" button |
| Next / previous page | `Page Down` / `Page Up` |

`F1` opens the in-app help with this shortcut list and the version; pressing `F1` again closes it.

The zoom, fit and page keys work once the preview has the focus, so click it first. While it is open, the preview follows the page selected on the left, and the divider can be dragged to change the split.

## Limitations

- Bookmarks (outline) and form fields are not kept in the saved file, because they no longer match once the page order changes.
- Document information (title, author, ...) is taken from the source file of the first page.
- Saving reopens the saved file, which clears the undo history.

## Architecture

![ChoboPDF architecture](docs/architecture.svg)

- **UI** (`chobopdf/ui`): main window, thumbnail grid and preview. It never edits directly; it pushes commands onto the undo stack.
- **Model** (`chobopdf/model`): the document is a list of `PageRef(source file, page index, rotation)`. The insert, delete, move and rotate commands change only this list, which is why edits are instant and the source PDFs stay untouched.
- **Thumbnailer** (`chobopdf/render`): opens and renders PDFs with [pypdfium2](https://github.com/pypdfium2-team/pypdfium2) on a single dedicated thread. Only the pages on or near the screen are rendered and kept in an LRU cache; rotation is applied when painting, without re-rendering.
- **SaveJob** (`chobopdf/pdfio`): on save, takes the page list and writes a new PDF with [pikepdf](https://github.com/pikepdf/pikepdf) on its own thread. Page contents are copied as they are, without re-encoding.

The GUI is built with [PySide6](https://doc.qt.io/qtforpython-6/). The repository also holds the pytest unit tests in `tests/` and the icon generator in `tools/make_icon.py`.

## Tests

```bat
.venv\Scripts\python -m pytest
```

## License

[MIT](LICENSE)
