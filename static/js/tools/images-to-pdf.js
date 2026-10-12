// IMAGES -> PDF
import { apiFetch, readError } from '../core/api.js';
import { bytesToSize } from '../core/format.js';
import { showStatus } from '../core/notify.js';

export function initImagesToPdf(){
  const drop = document.getElementById('drop-i2p');
  const fileInput = document.getElementById('file-i2p');
  const filmstrip = document.getElementById('filmstrip');
  const stageHint = document.getElementById('stage-hint');
  const controls = document.getElementById('controls-i2p');
  const btn = document.getElementById('btn-i2p');
  const status = document.getElementById('status-i2p');
  const scan = document.getElementById('scan-i2p');
  const resultsWrap = document.getElementById('results-i2p');
  const meta = document.getElementById('meta-i2p');
  const linkPdf = document.getElementById('link-pdf');

  let staged = []; // {file, url}

  const setStatus = (msg, kind)=> showStatus(status, msg, kind);

  function addFiles(fileList){
    const arr = Array.from(fileList).filter(f=>f.type.startsWith('image/'));
    if(arr.length === 0){
      setStatus('Those don\'t look like images.', 'error');
      return;
    }
    arr.forEach(f=> staged.push({file:f, url:URL.createObjectURL(f)}));
    renderFilmstrip();
    setStatus('');
  }

  drop.addEventListener('click', ()=>fileInput.click());
  drop.addEventListener('keydown', e=>{ if(e.key==='Enter' || e.key===' '){ e.preventDefault(); fileInput.click(); }});
  fileInput.addEventListener('change', e=>{ addFiles(e.target.files); fileInput.value=''; });

  ['dragenter','dragover'].forEach(evt=>{
    drop.addEventListener(evt, e=>{ e.preventDefault(); drop.classList.add('drag'); });
  });
  ['dragleave','drop'].forEach(evt=>{
    drop.addEventListener(evt, e=>{ e.preventDefault(); drop.classList.remove('drag'); });
  });
  drop.addEventListener('drop', e=> addFiles(e.dataTransfer.files));

  function renderFilmstrip(){
    filmstrip.innerHTML = '';
    staged.forEach((item, idx)=>{
      const el = document.createElement('div');
      el.className = 'film-item';
      el.innerHTML = `
        <div class="thumb-wrap"><img src="${item.url}" alt="${item.file.name}" /></div>
        <div class="film-foot">
          <span class="film-name" title="${item.file.name}">${idx+1}. ${item.file.name}</span>
          <div class="film-order">
            <button data-act="up" data-idx="${idx}" aria-label="Move earlier">↑</button>
            <button data-act="down" data-idx="${idx}" aria-label="Move later">↓</button>
            <button data-act="remove" data-idx="${idx}" class="remove" aria-label="Remove">✕</button>
          </div>
        </div>
      `;
      filmstrip.appendChild(el);
    });

    const hasFiles = staged.length > 0;
    stageHint.style.display = hasFiles ? 'block' : 'none';
    controls.style.display = hasFiles ? 'flex' : 'none';
    btn.disabled = !hasFiles;
    if(!hasFiles) resultsWrap.style.display = 'none';
  }

  filmstrip.addEventListener('click', e=>{
    const b = e.target.closest('button');
    if(!b) return;
    const idx = parseInt(b.dataset.idx, 10);
    const act = b.dataset.act;
    if(act === 'remove'){
      staged.splice(idx,1);
    } else if(act === 'up' && idx > 0){
      [staged[idx-1], staged[idx]] = [staged[idx], staged[idx-1]];
    } else if(act === 'down' && idx < staged.length-1){
      [staged[idx+1], staged[idx]] = [staged[idx], staged[idx+1]];
    }
    renderFilmstrip();
  });

  btn.addEventListener('click', async ()=>{
    if(staged.length === 0) return;
    btn.disabled = true;
    scan.classList.add('active');
    setStatus('Developing ' + staged.length + ' image' + (staged.length===1?'':'s') + ' into a PDF…');
    resultsWrap.style.display = 'none';

    const form = new FormData();
    staged.forEach(item => form.append('files', item.file));

    try{
      const res = await apiFetch('/api/images-to-pdf', { method:'POST', body: form });
      if(!res.ok){
        throw new Error(await readError(res, 'Conversion failed.'));
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      linkPdf.href = url;
      meta.textContent = staged.length + ' page' + (staged.length===1?'':'s') + ' · ' + bytesToSize(blob.size);
      resultsWrap.style.display = 'block';
      setStatus('Done — PDF ready.', 'ok');
    }catch(err){
      setStatus(err.message || 'Something went wrong.', 'error');
    }finally{
      scan.classList.remove('active');
      btn.disabled = false;
    }
  });
}
