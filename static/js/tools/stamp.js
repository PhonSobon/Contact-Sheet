// STAMP (watermark / page numbers / header & footer)
import { apiFetch, readError } from '../core/api.js';
import { bytesToSize } from '../core/format.js';
import { showStatus } from '../core/notify.js';

export function initStamp(){
  const drop = document.getElementById('drop-stamp');
  const fileInput = document.getElementById('file-stamp');
  const primary = document.getElementById('drop-stamp-primary');
  const btn = document.getElementById('btn-stamp');
  const status = document.getElementById('status-stamp');
  const scan = document.getElementById('scan-stamp');
  const resultsWrap = document.getElementById('results-stamp');
  const meta = document.getElementById('meta-stamp');
  const linkStamp = document.getElementById('link-stamp');
  const outNameLabel = document.getElementById('stamp-out-name');

  let currentFile = null;

  const setStatus = (msg, kind)=> showStatus(status, msg, kind);

  function setFile(f){
    if(!f) return;
    if(!(f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf'))){
      setStatus('That doesn\'t look like a PDF.', 'error');
      return;
    }
    currentFile = f;
    primary.textContent = f.name + ' — ' + bytesToSize(f.size);
    btn.disabled = false;
    setStatus('');
    resultsWrap.style.display = 'none';
  }

  drop.addEventListener('click', ()=>fileInput.click());
  drop.addEventListener('keydown', e=>{ if(e.key==='Enter' || e.key===' '){ e.preventDefault(); fileInput.click(); }});
  fileInput.addEventListener('change', e=> setFile(e.target.files[0]));
  ['dragenter','dragover'].forEach(evt=> drop.addEventListener(evt, e=>{ e.preventDefault(); drop.classList.add('drag'); }));
  ['dragleave','drop'].forEach(evt=> drop.addEventListener(evt, e=>{ e.preventDefault(); drop.classList.remove('drag'); }));
  drop.addEventListener('drop', e=> setFile(e.dataTransfer.files[0]));

  function hexFromColorInput(){
    return document.getElementById('wm-color').value.replace('#','');
  }

  btn.addEventListener('click', async ()=>{
    if(!currentFile) return;

    const wmText = document.getElementById('wm-text').value.trim();
    const headerText = document.getElementById('header-text').value.trim();
    const footerText = document.getElementById('footer-text').value.trim();
    const pnEnabled = document.getElementById('pn-enabled').value === 'on';

    if(!wmText && !headerText && !footerText && !pnEnabled){
      setStatus('Add a watermark, header, footer, or turn on page numbers first.', 'error');
      return;
    }

    btn.disabled = true;
    scan.classList.add('active');
    setStatus('Stamping ' + currentFile.name + '…');
    resultsWrap.style.display = 'none';

    const form = new FormData();
    form.append('file', currentFile);
    form.append('watermark_text', wmText);
    form.append('watermark_opacity', document.getElementById('wm-opacity').value);
    form.append('watermark_size', document.getElementById('wm-size').value);
    form.append('watermark_rotation', document.getElementById('wm-rotation').value);
    form.append('watermark_color', hexFromColorInput());
    form.append('page_numbers', pnEnabled ? 'true' : 'false');
    form.append('page_number_format', document.getElementById('pn-format').value || 'Page {n} of {total}');
    form.append('page_number_position', document.getElementById('pn-position').value);
    form.append('header_text', headerText);
    form.append('header_position', document.getElementById('header-position').value);
    form.append('footer_text', footerText);
    form.append('footer_position', document.getElementById('footer-position').value);

    try{
      const res = await apiFetch('/api/pdf/stamp', { method:'POST', body: form });
      if(!res.ok){
        throw new Error(await readError(res, 'Stamping failed.'));
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const outName = currentFile.name.replace(/\.pdf$/i, '') + '-stamped.pdf';
      linkStamp.href = url;
      linkStamp.download = outName;
      outNameLabel.textContent = outName;
      meta.textContent = bytesToSize(blob.size);
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
