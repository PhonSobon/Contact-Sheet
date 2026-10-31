// PDF -> IMAGES
import { apiFetch, readError } from '../core/api.js';
import { bytesToSize } from '../core/format.js';
import { showStatus } from '../core/notify.js';

export function initPdfToImages(){
  const drop = document.getElementById('drop-p2i');
  const fileInput = document.getElementById('file-p2i');
  const primaryText = document.getElementById('drop-p2i-primary');
  const btn = document.getElementById('btn-p2i');
  const status = document.getElementById('status-p2i');
  const scan = document.getElementById('scan-p2i');
  const resultsWrap = document.getElementById('results-p2i');
  const grid = document.getElementById('grid-p2i');
  const meta = document.getElementById('meta-p2i');
  const dpiSelect = document.getElementById('dpi-select');
  const fmtSelect = document.getElementById('fmt-select');
  const btnZip = document.getElementById('btn-download-zip');

  const list = document.getElementById('p2i-list');

  const MAX_FILES = 10;
  let staged = [];
  let zipBase64 = null;
  let zipFilename = 'images.zip';
  let excludedPages = new Set();   // "fileIndex:page" keys
  const covers = new WeakMap();    // File -> { dataUrl, pageCount } once its first page is rendered

  function escapeHtml(str){
    return String(str).replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  // First-page preview per staged PDF. One request per file: hosted servers
  // cap request size, and only page 1 is rendered so it stays small.
  async function loadCover(file){
    if(covers.has(file)) return;
    covers.set(file, null);
    try{
      const form = new FormData();
      form.append('files', file);
      form.append('thumb_dpi', '60');
      form.append('max_pages', '1');
      const res = await apiFetch('/api/pdf/inspect', { method:'POST', body: form });
      if(!res.ok) return;
      const src = (await res.json()).sources[0];
      covers.set(file, { dataUrl: src.pages[0] && src.pages[0].data_url, pageCount: src.page_count });
      if(staged.includes(file)) renderList();
    }catch(_){
      // keep the text placeholder
    }
  }

  function renderList(){
    list.innerHTML = '';
    staged.forEach((file, idx)=>{
      const cover = covers.get(file);
      const thumb = cover && cover.dataUrl
        ? `<img src="${cover.dataUrl}" alt="${escapeHtml(file.name)}" style="max-width:100%;max-height:100%;" />`
        : `<div class="mono" style="color:var(--amber);font-size:24px;">PDF</div>`;
      const pagesNote = cover ? ' · ' + cover.pageCount + ' page' + (cover.pageCount===1?'':'s') : '';
      const el = document.createElement('div');
      el.className = 'film-item';
      el.innerHTML = `
        <div class="thumb-wrap">${thumb}</div>
        <div class="film-foot">
          <span class="film-name" title="${escapeHtml(file.name)}">${idx+1}. ${escapeHtml(file.name)} · ${bytesToSize(file.size)}${pagesNote}</span>
          <div class="film-order">
            <button data-idx="${idx}" class="remove" aria-label="Remove">x</button>
          </div>
        </div>
      `;
      list.appendChild(el);
    });

    const total = staged.reduce((sum, f)=> sum + f.size, 0);
    primaryText.textContent = staged.length
      ? staged.length + ' PDF' + (staged.length===1?'':'s') + ' selected — ' + bytesToSize(total)
      : 'Drop PDFs here, or click to choose files';
    btn.disabled = staged.length === 0;
  }

  function addFiles(fileList){
    const all = Array.from(fileList || []);
    if(all.length === 0) return;
    const pdfs = all.filter(f=> f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf'));
    if(pdfs.length === 0){
      setStatus('That doesn\'t look like a PDF.', 'error');
      return;
    }
    const before = staged.length;
    staged = staged.concat(pdfs).slice(0, MAX_FILES);
    const dropped = before + pdfs.length - staged.length;
    renderList();
    staged.forEach(loadCover);
    resultsWrap.style.display = 'none';
    zipBase64 = null;
    if(dropped > 0) setStatus('Only ' + MAX_FILES + ' PDFs at a time — ' + dropped + ' skipped.', 'error');
    else if(pdfs.length < all.length) setStatus('Skipped files that aren\'t PDFs.', 'error');
    else setStatus('');
  }

  const setStatus = (msg, kind)=> showStatus(status, msg, kind);

  drop.addEventListener('click', ()=>fileInput.click());
  drop.addEventListener('keydown', e=>{ if(e.key==='Enter' || e.key===' '){ e.preventDefault(); fileInput.click(); }});
  fileInput.addEventListener('change', e=>{ addFiles(e.target.files); fileInput.value = ''; });

  ['dragenter','dragover'].forEach(evt=>{
    drop.addEventListener(evt, e=>{ e.preventDefault(); drop.classList.add('drag'); });
  });
  ['dragleave','drop'].forEach(evt=>{
    drop.addEventListener(evt, e=>{ e.preventDefault(); drop.classList.remove('drag'); });
  });
  drop.addEventListener('drop', e=> addFiles(e.dataTransfer.files));

  list.addEventListener('click', e=>{
    const b = e.target.closest('button');
    if(!b) return;
    staged.splice(parseInt(b.dataset.idx, 10), 1);
    renderList();
    resultsWrap.style.display = 'none';
    zipBase64 = null;
    setStatus('');
  });

  function buildForm(){
    const form = new FormData();
    staged.forEach(f=> form.append('files', f));
    form.append('dpi', dpiSelect.value);
    form.append('output_format', fmtSelect.value);
    return form;
  }

  btn.addEventListener('click', async ()=>{
    if(staged.length === 0) return;
    excludedPages = new Set();
    btn.disabled = true;
    scan.classList.add('active');
    const label = staged.length === 1 ? staged[0].name : staged.length + ' PDFs';
    setStatus('Scanning ' + label + ' at ' + dpiSelect.value + ' DPI…');
    resultsWrap.style.display = 'none';

    try{
      const res = await apiFetch('/api/pdf-to-images', { method:'POST', body: buildForm() });
      if(!res.ok){
        throw new Error(await readError(res, 'Conversion failed.'));
      }
      const data = await res.json();
      renderResults(data);
      setStatus('Done — ' + data.page_count + ' page' + (data.page_count===1?'':'s') + ' developed.', 'ok');
    }catch(err){
      setStatus(err.message || 'Something went wrong.', 'error');
    }finally{
      scan.classList.remove('active');
      btn.disabled = staged.length === 0;
    }
  });

  function updateMetaCount(){
    const remaining = grid.querySelectorAll('.print-card').length - excludedPages.size;
    const removedNote = excludedPages.size ? ' · ' + excludedPages.size + ' removed' : '';
    meta.textContent = remaining + ' page' + (remaining===1?'':'s') + ' will be included' + removedNote;
  }

  function renderResults(data){
    grid.innerHTML = '';
    zipBase64 = data.zip_base64;
    zipFilename = data.zip_filename;
    const filesNote = data.file_count > 1 ? data.file_count + ' PDFs · ' : '';
    meta.textContent = filesNote + data.page_count + ' page' + (data.page_count===1?'':'s') + ' · ' + data.dpi + ' DPI · .' + data.format.toUpperCase();

    data.pages.forEach(p=>{
      const key = p.file_index + ':' + p.page_number;
      const card = document.createElement('div');
      card.className = 'print-card';
      card.innerHTML = `
        <div class="sprocket-strip"><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span></div>
        <button type="button" class="remove-page" title="Remove this page">×</button>
        <img src="${p.thumb_data_url}" alt="${escapeHtml(p.filename)}" loading="lazy" />
        <div class="print-caption">
          <span class="fname">${escapeHtml(p.filename)}</span>
          <div class="meta">
            <span>${p.width}×${p.height} · ${bytesToSize(p.size_bytes)}</span>
          </div>
        </div>
      `;
      card.querySelector('.remove-page').addEventListener('click', ()=>{
        if(excludedPages.has(key)){
          excludedPages.delete(key);
          card.classList.remove('removed');
        } else {
          excludedPages.add(key);
          card.classList.add('removed');
        }
        updateMetaCount();
      });
      grid.appendChild(card);
    });

    resultsWrap.style.display = 'block';
  }

  btnZip.addEventListener('click', async ()=>{
    if(!zipBase64) return;

    if(excludedPages.size){
      btnZip.disabled = true;
      setStatus('Rebuilding zip without removed pages…');
      try{
        const form = buildForm();
        form.append('exclude_pages', Array.from(excludedPages).join(','));
        const res = await apiFetch('/api/pdf-to-images', { method:'POST', body: form });
        if(!res.ok){
          throw new Error(await readError(res, 'Conversion failed.'));
        }
        const data = await res.json();
        zipBase64 = data.zip_base64;
        zipFilename = data.zip_filename;
        setStatus('Done — ' + data.page_count + ' page' + (data.page_count===1?'':'s') + ' in the zip.', 'ok');
      }catch(err){
        setStatus(err.message || 'Something went wrong.', 'error');
        btnZip.disabled = false;
        return;
      }
      btnZip.disabled = false;
    }

    const byteChars = atob(zipBase64);
    const byteNumbers = new Array(byteChars.length);
    for(let i=0;i<byteChars.length;i++) byteNumbers[i] = byteChars.charCodeAt(i);
    const byteArray = new Uint8Array(byteNumbers);
    const blob = new Blob([byteArray], {type:'application/zip'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = zipFilename;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
  });
}
