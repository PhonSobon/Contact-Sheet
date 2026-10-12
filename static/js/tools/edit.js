// EDIT PDF (merge / reorder / rotate / delete / split)
import { apiFetch, readError } from '../core/api.js';
import { bytesToSize } from '../core/format.js';
import { showStatus } from '../core/notify.js';

export function initEdit(){
  const drop = document.getElementById('drop-edit');
  const fileInput = document.getElementById('file-edit');
  const primary = document.getElementById('drop-edit-primary');
  const editHint = document.getElementById('edit-hint');
  const pageGrid = document.getElementById('page-grid');
  const controls = document.getElementById('controls-edit');
  const btn = document.getElementById('btn-edit');
  const status = document.getElementById('status-edit');
  const scan = document.getElementById('scan-edit');
  const resultsWrap = document.getElementById('results-edit');
  const meta = document.getElementById('meta-edit');
  const nameInput = document.getElementById('edit-name');
  const compressSelect = document.getElementById('edit-compress');
  const linkEdit = document.getElementById('link-edit');
  const outNameLabel = document.getElementById('edit-out-name');

  let sourceFiles = [];  // File objects, index = source_index sent to the backend
  let pageList = [];     // {source_index, page_index, rotate, data_url, filename, key}
  let keyCounter = 0;

  const setStatus = (msg, kind)=> showStatus(status, msg, kind);

  function updateVisibility(){
    const has = pageList.length > 0;
    editHint.style.display = has ? 'block' : 'none';
    controls.style.display = has ? 'flex' : 'none';
    btn.disabled = !has;
    if(!has) resultsWrap.style.display = 'none';
  }

  function renderGrid(){
    pageGrid.innerHTML = '';
    pageList.forEach((p, idx)=>{
      const card = document.createElement('div');
      card.className = 'page-card';
      card.innerHTML = `
        <div class="page-thumb-wrap"><img src="${p.data_url}" alt="page ${idx+1}" style="transform:rotate(${p.rotate}deg);" /></div>
        <div class="page-foot">
          <span class="page-label" title="${p.filename}">${idx+1}. ${p.filename}</span>
          <div class="page-actions">
            <button data-act="left" data-key="${p.key}" aria-label="Rotate left">↺</button>
            <button data-act="right" data-key="${p.key}" aria-label="Rotate right">↻</button>
            <button data-act="up" data-key="${p.key}" aria-label="Move earlier">↑</button>
            <button data-act="down" data-key="${p.key}" aria-label="Move later">↓</button>
            <button data-act="remove" data-key="${p.key}" class="remove" aria-label="Remove page">✕</button>
          </div>
        </div>
      `;
      pageGrid.appendChild(card);
    });
    updateVisibility();
  }

  async function ingestFiles(fileList){
    const pdfs = Array.from(fileList).filter(f=> f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf'));
    if(pdfs.length === 0){
      setStatus('Those don\'t look like PDFs.', 'error');
      return;
    }
    setStatus('Reading ' + pdfs.length + ' file' + (pdfs.length===1?'':'s') + '…');
    const form = new FormData();
    pdfs.forEach(f=> form.append('files', f));
    form.append('thumb_dpi', '90');

    try{
      const res = await apiFetch('/api/pdf/inspect', { method:'POST', body: form });
      if(!res.ok){
        throw new Error(await readError(res, 'Could not read those PDFs.'));
      }
      const data = await res.json();
      const baseIndex = sourceFiles.length;
      pdfs.forEach(f=> sourceFiles.push(f));

      data.sources.forEach(src=>{
        const srcIdx = baseIndex + src.source_index;
        src.pages.forEach(p=>{
          pageList.push({
            source_index: srcIdx,
            page_index: p.page_index,
            rotate: 0,
            data_url: p.data_url,
            filename: src.filename,
            key: 'k' + (keyCounter++),
          });
        });
      });

      primary.textContent = sourceFiles.length + ' PDF' + (sourceFiles.length===1?'':'s') + ' loaded — ' + pageList.length + ' page' + (pageList.length===1?'':'s') + ' total';
      renderGrid();
      setStatus('');
    }catch(err){
      setStatus(err.message || 'Something went wrong.', 'error');
    }
  }

  drop.addEventListener('click', ()=>fileInput.click());
  drop.addEventListener('keydown', e=>{ if(e.key==='Enter' || e.key===' '){ e.preventDefault(); fileInput.click(); }});
  fileInput.addEventListener('change', e=>{ ingestFiles(e.target.files); fileInput.value=''; });
  ['dragenter','dragover'].forEach(evt=> drop.addEventListener(evt, e=>{ e.preventDefault(); drop.classList.add('drag'); }));
  ['dragleave','drop'].forEach(evt=> drop.addEventListener(evt, e=>{ e.preventDefault(); drop.classList.remove('drag'); }));
  drop.addEventListener('drop', e=> ingestFiles(e.dataTransfer.files));

  pageGrid.addEventListener('click', e=>{
    const b = e.target.closest('button');
    if(!b) return;
    const key = b.dataset.key;
    const idx = pageList.findIndex(p=> p.key === key);
    if(idx === -1) return;
    const act = b.dataset.act;
    if(act === 'remove'){
      pageList.splice(idx,1);
    } else if(act === 'left'){
      pageList[idx].rotate = (pageList[idx].rotate - 90 + 360) % 360;
    } else if(act === 'right'){
      pageList[idx].rotate = (pageList[idx].rotate + 90) % 360;
    } else if(act === 'up' && idx > 0){
      [pageList[idx-1], pageList[idx]] = [pageList[idx], pageList[idx-1]];
    } else if(act === 'down' && idx < pageList.length-1){
      [pageList[idx+1], pageList[idx]] = [pageList[idx], pageList[idx+1]];
    }
    renderGrid();
  });

  btn.addEventListener('click', async ()=>{
    if(pageList.length === 0) return;
    btn.disabled = true;
    scan.classList.add('active');
    setStatus('Building ' + pageList.length + ' page' + (pageList.length===1?'':'s') + '…');
    resultsWrap.style.display = 'none';

    const plan = pageList.map(p=> ({ source_index: p.source_index, page_index: p.page_index, rotate: p.rotate }));
    const form = new FormData();
    sourceFiles.forEach(f=> form.append('files', f));
    form.append('plan', JSON.stringify(plan));
    form.append('compress', compressSelect.value);
    form.append('output_filename', nameInput.value || 'edited.pdf');

    try{
      const res = await apiFetch('/api/pdf/build', { method:'POST', body: form });
      if(!res.ok){
        throw new Error(await readError(res, 'Could not build the PDF.'));
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const outName = (nameInput.value || 'edited.pdf').trim() || 'edited.pdf';
      linkEdit.href = url;
      linkEdit.download = outName;
      outNameLabel.textContent = outName;
      meta.textContent = pageList.length + ' page' + (pageList.length===1?'':'s') + ' · ' + bytesToSize(blob.size);
      resultsWrap.style.display = 'block';
      setStatus('Done.', 'ok');
    }catch(err){
      setStatus(err.message || 'Something went wrong.', 'error');
    }finally{
      scan.classList.remove('active');
      btn.disabled = false;
    }
  });
}
