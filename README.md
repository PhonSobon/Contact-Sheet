# Contact Sheet — PDF ⇄ Image Converter

One app, one command. FastAPI serves both the API and the page itself.

```
contact-sheet/
├── main.py            # FastAPI app: API routes + serves static/index.html
├── requirements.txt
└── static/
    └── index.html      # the whole frontend (no build step, no framework)
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
| POST   | `/api/pdf-to-images`  | `file` (PDF), `dpi` (int, default 150), `output_format` (`png`/`jpg`/`webp`) | JSON: page thumbnails (base64) + a base64-encoded ZIP of all pages  |
| POST   | `/api/images-to-pdf`  | `files` (one or more images, in desired page order)                          | `application/pdf` binary stream                                     |
| POST   | `/api/pdf/inspect`    | `files` (one or more PDFs), `thumb_dpi` (int, default 90)                    | JSON: page thumbnails per source file, for the page editor          |
| POST   | `/api/pdf/build`      | `files`, `plan` (JSON page list), `compress`, `raster_dpi`, `raster_quality`, `output_filename` | `application/pdf` — drives merge, split/extract, delete, reorder, rotate, compress |
| POST   | `/api/image/compress` | `files` (one or more images), `quality`, `max_dimension`, `output_format`   | JSON: compressed results (base64) + a base64-encoded ZIP            |
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

Limits (adjust in `main.py` if needed): PDFs up to 40 MB / 60 pages total, images up to 20 MB each / 60 files per PDF, up to 10 PDFs at once in the editor.

## Features

- **PDF → Images** — render every page at a chosen DPI/format, download individually or as a ZIP
- **Images → PDF** — combine photos/screenshots into one PDF, reorder before converting
- **Edit PDF** — drop one or more PDFs into an editable page grid: reorder, rotate, delete pages, drop in more PDFs to merge them, or keep only a subset to split/extract
- **Compress** — shrink a PDF (lossless "optimize" or aggressive "rasterize") or a batch of images (quality + max-dimension), with before/after size shown

## Deploying

Any host that runs an ASGI app (Fly.io, Render, Railway, a plain VM with `uvicorn`/`gunicorn` behind nginx) works — `static/index.html` ships with the same process, so there's nothing extra to deploy or point at each other. If you ever do split the frontend onto a different domain, set `API_BASE` near the top of the `<script>` block in `index.html` to the API's URL, and tighten `allow_origins` in `CORSMiddleware` to that domain.

## Design notes

The UI leans into the literal mechanics of the tool — a PDF becomes photographs, photographs become a PDF — with a darkroom/contact-sheet visual language: sprocket-hole framed panels, an amber scan-line that sweeps during conversion, and monospace technical readouts (dimensions, DPI, file size) styled like camera/scanner output.