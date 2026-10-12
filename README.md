# Contact Sheet — PDF ⇄ Image Converter

One app, one command. FastAPI serves both the API and the page itself.

```
contact-sheet/
├── main.py                      # entry point (`uvicorn main:app`) — re-exports app.main:app
├── requirements.txt
├── app/
│   ├── main.py                  # create_app(): routers, error handlers, serves static/
│   ├── core/
│   │   ├── config.py            # limits (file size, page count) and paths
│   │   ├── errors.py            # unexpected errors -> JSON {"detail": ...}
│   │   ├── pdf_utils.py         # open/validate uploaded PDFs, PDF responses, page ranges
│   │   └── image_utils.py       # open/validate uploaded images
│   ├── services/
│   │   ├── background_removal.py  # u2netp via onnxruntime
│   │   ├── content_stream.py    # minimal PDF content-stream tokenizer
│   │   ├── watermark.py         # PDF watermark detection + removal
│   │   └── image_watermark.py   # image cleanup: inpainting, pale-watermark and colour removal (numpy only)
│   └── routers/                 # one file per feature
│       ├── health.py            # /api/health
│       ├── convert.py           # /api/pdf-to-images, /api/images-to-pdf
│       ├── pdf_merge.py         # /api/pdf/combine, /api/pdf/inspect, /api/pdf/build
│       ├── pdf_pages.py         # /api/pdf/remove-pages
│       ├── pdf_stamp.py         # /api/pdf/stamp
│       ├── pdf_watermark.py     # /api/pdf/watermark/detect, /api/pdf/remove-watermark
│       ├── image_watermark.py   # /api/image/remove-watermark
│       ├── pdf_crop.py          # /api/pdf/crop-resize
│       └── image.py             # /api/image/compress, /api/image/remove-bg
├── model/u2netp.onnx            # background-removal model
├── design/og-image.html         # source of static/og-image.png (link-preview image)
└── static/                      # frontend — plain ES modules, no build step
    ├── index.html               # markup only
    ├── favicon.svg, og-image.png
    ├── css/
    │   ├── base.css             # design tokens (dark + light), element defaults
    │   ├── layout.css           # sidebar + main column
    │   ├── components.css       # frame, drop zone, fields, buttons, results
    │   ├── tools.css            # tool-specific pieces (page grids, stamp, watermark)
    │   ├── notify.css           # toast notifications
    │   └── responsive.css       # small screens, reduced motion
    └── js/
        ├── main.js              # entry: theme, tabs, notifications, starts every tool
        ├── core/
        │   ├── api.js           # apiFetch(), readError(), health check
        │   ├── files.js         # paste (Ctrl/⌘+V) + drop-anywhere for every tool
        │   ├── download.js      # save blobs / base64 files
        │   ├── notify.js        # toasts + showStatus() (every error shows a toast)
        │   ├── theme.js, layout.js, format.js
        └── tools/               # one module per tool, each exports init…()
            ├── remove-watermark.js        # PDF mode + PDF/Image switch
            ├── remove-watermark-image.js  # image mode
            ├── mask-editor.js             # brush / box / eraser / colour-picker canvas
            └── pdf-to-images.js, combine.js, …
```

## Run it

```bash
python3 -m venv venv && source venv/bin/activate   # optional but recommended
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Open **http://127.0.0.1:8000** — that's it. The page and the API are on the same origin, so there's no separate frontend server and no CORS config to worry about.

## Endpoints

| Method | Path                  | Body (multipart/form-data)                                                   | Returns                                                             |
|--------|-----------------------|-------------------------------------------------------------------------------|--------------------------------------------------------------------|
| GET    | `/`                   | —                                                                              | the app (index.html)                                                |
| POST   | `/api/pdf-to-images`  | `files` (1–10 PDFs), `dpi` (int, default 150), `output_format` (`png`/`jpg`/`webp`), `exclude_pages` (`fileIndex:page,...`) | JSON: page thumbnails (base64) + a base64-encoded ZIP of all pages (one folder per PDF when several are uploaded) |
| POST   | `/api/images-to-pdf`  | `files` (one or more images, in desired page order)                          | `application/pdf` binary stream                                     |
| POST   | `/api/pdf/combine`    | `files` (2-10 PDFs, in desired order), `output_filename`                    | `application/pdf` combined binary stream                            |
| POST   | `/api/pdf/inspect`    | `files` (one or more PDFs), `thumb_dpi` (int, default 90)                    | JSON: page thumbnails per source file, for the page editor          |
| POST   | `/api/pdf/build`      | `files`, `plan` (JSON page list), `compress`, `raster_dpi`, `raster_quality`, `output_filename` | `application/pdf` — drives merge, split/extract, delete, reorder, rotate, compress |
| POST   | `/api/pdf/remove-pages` | `file` (PDF), `pages` (1-based pages/ranges to delete, e.g. `2, 5-7`)        | `application/pdf` — pages removed in place, original quality kept (no re-render/compression) |
| POST   | `/api/image/compress` | `files` (one or more images), `quality`, `max_dimension`, `output_format`   | JSON: compressed results (base64) + a base64-encoded ZIP            |
| POST   | `/api/pdf/watermark/detect` | `file` (PDF)                                                     | JSON: watermark layers/annotations found + text that looks like a watermark |
| POST   | `/api/pdf/remove-watermark` | `file` (PDF), `texts` (JSON list, e.g. `["CONFIDENTIAL"]`), `remove_stamps`, scanned pages: `images_light`, `images_light_strength`, `images_color`, `images_tolerance` | `application/pdf` with the watermark removed (422 if nothing removable was found) |
| POST   | `/api/image/remove-watermark` | `files` (1–10 images), optional `masks` (`mask-<index>.png`, white = remove), `light`, `light_strength`, `color`, `tolerance`, `fill` (`auto`/`blend`/`paper`), `output_format` | JSON: cleaned images (base64) + ZIP |
| POST   | `/api/pdf/crop-resize` | `file` (PDF), crop margins, `page_size`, optional custom dimensions         | `application/pdf` cropped/resized PDF                               |
| GET    | `/api/health`         | —                                                                              | `{"status": "ok"}`                                                   |

Interactive API docs at `/docs`.

### How `/api/pdf/build`'s `plan` works

`plan` is a JSON array like:
```json
[
  { "source_index": 0, "page_index": 2, "rotate": 90 },
  { "source_index": 1, "page_index": 0, "rotate": 0 }
]
```
- `source_index` matches the position of the file in the `files` list sent alongside it.
- Pages from more than one `source_index` → **merge**.
- Leaving a page out of the plan → **delete** (keeping only a range → **split/extract**).
- The array's order is the final page order → **reorder**.
- `rotate` is degrees added to whatever rotation the page already has.

`compress` is `"none"`, `"optimize"` (lossless, safe for any PDF), or `"rasterize"` (biggest size reduction — flattens every page to a JPEG, so text is no longer selectable; best for scanned documents).

Limits (adjust in `app/core/config.py` if needed): PDFs up to 40 MB / 400 pages total, images up to 20 MB each / 400 files per PDF, up to 10 PDFs at once in the editor.

## Features

- **PDF → Images** — render every page at a chosen DPI/format, download individually or as a ZIP
- **Images → PDF** — combine photos/screenshots into one PDF, reorder before converting
- **Combine PDF** — drop up to 10 PDFs and see every page in the final order; drag pages (or use ← →) to move them anywhere, even between files, remove pages or whole files, then combine
- **Edit PDF** — drop one or more PDFs into an editable page grid: reorder, rotate, delete pages, drop in more PDFs to merge them, or keep only a subset to split/extract
- **Remove Pages** — click pages (or type ranges like `2, 5-7`) to delete them; the rest of the document — images, fonts, links, bookmarks, forms — is kept byte-for-byte, no compression
- **Compress** — shrink a PDF (lossless "optimize" or aggressive "rasterize") or a batch of images (quality + max-dimension), with before/after size shown
- **Remove Watermark** — finds watermark layers (Word/LibreOffice), Acrobat watermarks, watermark annotations and text watermarks, and removes the ones you pick; text is only removed when the whole text object is the watermark, so body text is kept. For scanned PDFs it can also clean the page images (pale or coloured watermarks). **Image mode**: paint or box over a watermark on photos/screenshots (filled in from the surroundings), or remove pale watermarks / a picked colour automatically, for up to 10 images at once, with press-and-hold before/after comparison
- **Paste & drop anywhere** — every tool accepts files pasted with Ctrl/⌘+V (screenshots included) or dropped anywhere on the page
- **Stamp** — add a diagonal watermark, header/footer text, and page numbers to a PDF, all in one pass
- **Remove Background** — cut the subject out of a photo (transparent PNG), batches of up to 15 at a time

### Remove Background — the fine print

This runs the `u2netp` segmentation model directly through `onnxruntime`, not a color-based crop, so it works on arbitrary photos. Two things to know before deploying:
- **The model is bundled at `model/u2netp.onnx`** so serverless deploys do not need to download it at runtime.
- For Vercel, keep `rembg`, `pymatting`, `scipy`, and `scikit-image` out of `requirements.txt`; those optional alpha-matting dependencies can push the Python function bundle over the size limit.
- **It's CPU-bound and a few seconds per image** — fine for occasional use, but don't expect it to keep up with heavy concurrent traffic without a GPU or a task queue.

## Deploying

Any host that runs an ASGI app (Fly.io, Render, Railway, a plain VM with `uvicorn`/`gunicorn` behind nginx) works — `static/index.html` ships with the same process, so there's nothing extra to deploy or point at each other. If you ever do split the frontend onto a different domain, set `API_BASE` near the top of the `<script>` block in `index.html` to the API's URL, and tighten `allow_origins` in `CORSMiddleware` to that domain.

## Design notes

The UI leans into the literal mechanics of the tool — a PDF becomes photographs, photographs become a PDF — with a darkroom/contact-sheet visual language: sprocket-hole framed panels, an amber scan-line that sweeps during conversion, and monospace technical readouts (dimensions, DPI, file size) styled like camera/scanner output.
