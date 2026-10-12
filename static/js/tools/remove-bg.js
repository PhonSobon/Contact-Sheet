// REMOVE BACKGROUND
import { apiFetch, readError } from '../core/api.js';
import { bytesToSize } from '../core/format.js';
import { showStatus } from '../core/notify.js';

export function initRemoveBg(){
  const drop = document.getElementById('drop-removebg');
  const fileInput = document.getElementById('file-removebg');
  const primary = document.getElementById('drop-removebg-primary');
  const btn = document.getElementById('btn-removebg');
  const status = document.getElementById('status-removebg');
  const scan = document.getElementById('scan-removebg');
  const resultsWrap = document.getElementById('results-removebg');
  const meta = document.getElementById('meta-removebg');
  const grid = document.getElementById('grid-removebg');
  const btnZip = document.getElementById('btn-download-zip-removebg');

  let staged = [];
  let zipBase64 = null;
  let zipFilename = 'no-background.zip';

  const setStatus = (msg, kind)=> showStatus(status, msg, kind);

  function addFiles(fileList){
    const arr = Array.from(fileList).filter(f=>f.type.startsWith('image/'));
    if(arr.length === 0){ setStatus('Those don\'t look like images.', 'error'); return; }
    staged = staged.concat(arr);
    if(staged.length > 15){
      setStatus('Up to 15 images at a time — trimmed to the first 15.', 'error');
      staged = staged.slice(0, 15);
    }
    primary.textContent = staged.length + ' image' + (staged.length===1?'':'s') + ' selected';
    btn.disabled = false;
    resultsWrap.style.display = 'none';
  }

  drop.addEventListener('click', ()=>fileInput.click());
  drop.addEventListener('keydown', e=>{ if(e.key==='Enter' || e.key===' '){ e.preventDefault(); fileInput.click(); }});
  fileInput.addEventListener('change', e=>{ addFiles(e.target.files); fileInput.value=''; });
  ['dragenter','dragover'].forEach(evt=> drop.addEventListener(evt, e=>{ e.preventDefault(); drop.classList.add('drag'); }));
  ['dragleave','drop'].forEach(evt=> drop.addEventListener(evt, e=>{ e.preventDefault(); drop.classList.remove('drag'); }));
  drop.addEventListener('drop', e=> addFiles(e.dataTransfer.files));

  btn.addEventListener('click', async ()=>{
    if(staged.length === 0) return;
    btn.disabled = true;
    scan.classList.add('active');
    setStatus('Cutting out ' + staged.length + ' subject' + (staged.length===1?'':'s') + ' — a few seconds each…');
    resultsWrap.style.display = 'none';

    const form = new FormData();
    staged.forEach(f=> form.append('files', f));

    try{
      const res = await apiFetch('/api/image/remove-bg', { method:'POST', body: form });
      if(!res.ok){
        throw new Error(await readError(res, 'Background removal failed.'));
      }
      const data = await res.json();
      zipBase64 = data.zip_base64;
      zipFilename = data.zip_filename;

      grid.innerHTML = '';
      data.results.forEach(r=>{
        const card = document.createElement('div');
        card.className = 'print-card transparent';
        card.innerHTML = `
          <div class="sprocket-strip"><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span></div>
          <img src="${r.data_url}" alt="${r.filename}" loading="lazy" />
          <div class="print-caption">
            <span class="fname">${r.filename}</span>
            <div class="meta">
              <span>${r.width}×${r.height} · ${bytesToSize(r.size_bytes)}</span>
              <a href="${r.data_url}" download="${r.filename}">↓</a>
            </div>
          </div>
        `;
        grid.appendChild(card);
      });
      meta.textContent = data.results.length + ' image' + (data.results.length===1?'':'s') + ' cut out';
      resultsWrap.style.display = 'block';
      setStatus('Done.', 'ok');
    }catch(err){
      setStatus(err.message || 'Something went wrong.', 'error');
    }finally{
      scan.classList.remove('active');
      btn.disabled = false;
    }
  });

  btnZip.addEventListener('click', ()=>{
    if(!zipBase64) return;
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
