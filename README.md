# ChoboPDF

English | [한국어](README.ko.md)

A Windows desktop tool for organizing the pages of very large PDFs (hundreds of MB): reorder, rotate, delete, merge and extract pages while looking at their thumbnails.

It does one job, page organizing, and is built around three choices:

- **Fast on big files.** Editing only changes an in-memory page list, and the PDF is written once, when you save. Moving, rotating and deleting pages is immediate even in a 500 MB scan.
- **Lossless.** Pages are copied into the saved file as they are, without re-encoding, so images keep their quality.
- **Safe and offline.** Every edit can be undone, a failed or cancelled save leaves the existing file untouched, and nothing is uploaded anywhere.

The user interface is in Korean.

## What's new in 0.1.1

- **Extract pages**: save only the selected pages as a new PDF (`Ctrl+E`).
- **Password-protected PDFs**: asks for the password when a file needs one.
- **Save when quitting**: closing with unsaved changes offers Save and Save as, not only discarding them.
- **Arrow keys in the preview**: `←` / `→` go to the previous / next page.
- **Version label**: the title bar and the help show the version as `V0.1.1`.

## Features

### Open and combine

- **Merging files**: open several PDFs at once and they are joined in file-name order. Numbers are compared by value, so `2.pdf` comes before `10.pdf`.
- **Adding a PDF**: insert the pages of another PDF into the open document. Drop a file from Explorer between two thumbnails to insert it there.
- **Password-protected PDFs**: asks for the password when opening, and again if it is wrong. The same goes for files being merged or added.

### Edit

- **Page editing**: drag to reorder, delete, rotate 90° left or right, cut/copy/paste, duplicate. Works on multi-page selections, and every edit can be undone.
- **Page marks**: put a bookmark ribbon on the top right corner of the pages you are working around, so you do not lose track of them while moving and deleting others. A mark follows its page and is never written to the PDF.

### View

- **Preview**: double-click a page to split the window and show that page large on the right, with 25–400% zoom, fit width and fit page. The arrow keys step through the pages.
- **Thumbnail zoom**: 100–200%, with the status bar slider or Ctrl+wheel.

### Save and export

- **Safe saving**: the file is written in the background to a temporary file that then replaces the target. Shows progress and can be cancelled.
- **Save as a copy**: saving an opened file asks whether to overwrite it or save a copy. A copy is written to another file while you keep working on the original.
- **Extracting pages**: save only the selected pages as a new PDF, in the order and rotation shown, while the open document stays as it is.
- **Pages as JPG**: save the selected pages as JPG images (200 DPI), in the rotation shown.
- **Save when quitting**: closing the window with unsaved changes asks whether to save, save under another name, quit without saving, or stay.

## Install and run

Requires Windows and Python 3.12 or later.

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

`F1` opens the in-app help with the shortcut list and the version; pressing `F1` again closes it.

### Files

| Action | How |
| --- | --- |
| Open | `Ctrl+O`, or drop a PDF on the window |
| Merge several files | `Ctrl+M`, or select several files in Open |
| Add a PDF to the open document | `Ctrl+I` (after the selected pages, or at the end if nothing is selected), or drop it between thumbnails |
| Save (asks: overwrite the original, or save a copy) | `Ctrl+S` |
| Save as (continues in the new file) | `Ctrl+Shift+S` |
| Save a copy (the open document stays as it is) | `Ctrl+Alt+S` |
| Extract the selected pages to a new PDF | `Ctrl+E`, or right-click the pages |
| Save the selected pages as JPG | `Ctrl+J`, or right-click the pages |
| Quit (asks about unsaved changes) | `Ctrl+Q`, or close the window |

- **Merged documents** have no file of their own yet, so `Ctrl+S` asks for a name.
- **Passwords** are asked for once per file and kept in memory only until the file is closed. Cancelling the prompt skips that file; when several files are being opened, the rest still open.
- **Saving a copy** does not count as saving the document: the title keeps its `*` until the document itself is saved.
- **Extracting** works like saving a copy: the open document and its undo history stay as they are. The suggested name is `<document>_추출.pdf`.
- **Copies and extracted pages** cannot be written over a file whose pages are currently open.
- **Quitting with unsaved changes** offers four choices. *Save* (저장) overwrites the original without asking again, or asks for a name if the document is a merge. *Save as* (다른 이름으로 저장) asks for a file. *Don't save* (저장 안 함) drops the changes. *Cancel* (취소) keeps the window open. The window closes only after the file has been written, so a save that fails or is cancelled leaves it open with the changes intact. `Enter` picks *Save as*, so it never overwrites the original.
- **JPG export** asks for a file name when one page is selected. With several, it asks for a folder and names the files `<document>_<page number>.jpg`.

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
| Next / previous page | `Page Down` / `Page Up`, or `→` / `←` |

The zoom, fit and page keys work once the preview has the focus, so click it first. When a zoomed page is wider than the pane, use the scroll bar to move sideways, because the arrow keys change the page. While it is open, the preview follows the page selected on the left, and the divider can be dragged to change the split.

## Limitations

- **Saved files have no password.** Overwriting a protected original leaves it unprotected, and so are copies and extracted pages.
- Bookmarks (outline) and form fields are not kept in the saved file, because they no longer match once the page order changes.
- Document information (title, author, ...) is taken from the source file of the first page.
- Saving reopens the saved file, which clears the undo history.
- Out of scope: annotations, text editing, OCR, compression, printing and text search.

## Architecture

![ChoboPDF architecture](docs/architecture.svg)

The diagram follows three flows through the layers.

- **Edit** (blue): the UI (`chobopdf/ui`) never edits directly. It pushes insert, delete, move and rotate commands onto an undo stack, and they change only the model (`chobopdf/model`), a list of `PageRef(source file, page index, rotation, marked)`. That is why edits are instant and the source PDFs stay untouched. `marked` is the page mark: it rides along with the page but is not part of the document, so it bypasses the undo stack and is never saved.
- **Open and render** (orange): the Thumbnailer (`chobopdf/render`) opens and renders PDFs with [pypdfium2](https://github.com/pypdfium2-team/pypdfium2) on a single dedicated thread, because PDFium is not thread-safe. It reports when a file needs a password, and the window asks for it and opens the file again. It serves thumbnails (only the pages on or near the screen, kept in an LRU cache), the large preview, and JPG export. Rotation is applied when painting a thumbnail, without re-rendering.
- **Save, copy and extract** (green): SaveJob (`chobopdf/pdfio`) takes a snapshot of the page list, either all pages or the selection, and writes a new PDF with [pikepdf](https://github.com/pikepdf/pikepdf) on its own thread. The file is written as `.tmp` and then swapped in. After a normal save the window reopens the result, while a copy or an extraction leaves the open document as it is. A save chosen while quitting closes the window once the file is written.

The GUI is built with [PySide6](https://doc.qt.io/qtforpython-6/). The repository also holds the pytest unit tests in `tests/` and the icon generator in `tools/make_icon.py`.

## Tests

```bat
.venv\Scripts\python -m pytest
```

## License

[MIT](LICENSE)
