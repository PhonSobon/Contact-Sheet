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
|--------|-----------------------|-------------------------------------------------------------------------------|----------------------------------------------------------------------|
| GET    | `/`                   | —                                                                              | the app (index.html)                                                 |
| POST   | `/api/pdf-to-images`  | `file` (PDF), `dpi` (int, default 150), `output_format` (`png`/`jpg`/`webp`) | JSON: page thumbnails (base64) + a base64-encoded ZIP of all pages   |
| POST   | `/api/images-to-pdf`  | `files` (one or more images, in desired page order)                          | `application/pdf` binary stream                                      |
| GET    | `/api/health`         | —                                                                              | `{"status": "ok"}`                                                    |

Interactive API docs at `/docs`.

Limits (adjust in `main.py` if needed): PDFs up to 40 MB / 60 pages, images up to 20 MB each / 60 files per PDF.

## Deploying

Any host that runs an ASGI app (Fly.io, Render, Railway, a plain VM with `uvicorn`/`gunicorn` behind nginx) works — `static/index.html` ships with the same process, so there's nothing extra to deploy or point at each other. If you ever do split the frontend onto a different domain, set `API_BASE` near the top of the `<script>` block in `index.html` to the API's URL, and tighten `allow_origins` in `CORSMiddleware` to that domain.

## Design notes

The UI leans into the literal mechanics of the tool — a PDF becomes photographs, photographs become a PDF — with a darkroom/contact-sheet visual language: sprocket-hole framed panels, an amber scan-line that sweeps during conversion, and monospace technical readouts (dimensions, DPI, file size) styled like camera/scanner output.