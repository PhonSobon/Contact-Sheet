// CROP / RESIZE PDF
import { apiFetch, readError } from '../core/api.js';
import { bytesToSize } from '../core/format.js';
import { showStatus } from '../core/notify.js';

export function initCrop(){
  const drop = document.getElementById('drop-crop');
  const fileInput = document.getElementById('file-crop');
  const primary = document.getElementById('drop-crop-primary');
  const btn = document.getElementById('btn-crop');
  const status = document.getElementById('status-crop');
  const scan = document.getElementById('scan-crop');
  const resultsWrap = document.getElementById('results-crop');
  const meta = document.getElementById('meta-crop');
  const linkCrop = document.getElementById('link-crop');
  const outNameLabel = document.getElementById('crop-out-name');
  const pageSize = document.getElementById('crop-page-size');
  const customFields = Array.from(document.querySelectorAll('.crop-custom-field'));

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

  function numberValue(id){
    const value = Number(document.getElementById(id).value);
    return Number.isFinite(value) ? value : 0;
  }

  function syncCustomFields(){
    const show = pageSize.value === 'custom';
    customFields.forEach(el=>{ el.style.display = show ? 'flex' : 'none'; });
  }

  pageSize.addEventListener('change', syncCustomFields);
  syncCustomFields();

  drop.addEventListener('click', ()=>fileInput.click());
  drop.addEventListener('keydown', e=>{ if(e.key==='Enter' || e.key===' '){ e.preventDefault(); fileInput.click(); }});
  fileInput.addEventListener('change', e=> setFile(e.target.files[0]));
  ['dragenter','dragover'].forEach(evt=> drop.addEventListener(evt, e=>{ e.preventDefault(); drop.classList.add('drag'); }));
  ['dragleave','drop'].forEach(evt=> drop.addEventListener(evt, e=>{ e.preventDefault(); drop.classList.remove('drag'); }));
  drop.addEventListener('drop', e=> setFile(e.dataTransfer.files[0]));

  btn.addEventListener('click', async ()=>{
    if(!currentFile) return;

    const margins = ['crop-top','crop-right','crop-bottom','crop-left'].map(numberValue);
    if(margins.some(v=>v < 0)){
      setStatus('Crop margins cannot be negative.', 'error');
      return;
    }
    if(pageSize.value === 'custom' && (numberValue('crop-custom-width') <= 0 || numberValue('crop-custom-height') <= 0)){
      setStatus('Custom width and height must be greater than zero.', 'error');
      return;
    }

    btn.disabled = true;
    scan.classList.add('active');
    setStatus('Cropping ' + currentFile.name + '…');
    resultsWrap.style.display = 'none';

    const form = new FormData();
    form.append('file', currentFile);
    form.append('unit', document.getElementById('crop-unit').value);
    form.append('margin_top', numberValue('crop-top'));
    form.append('margin_right', numberValue('crop-right'));
    form.append('margin_bottom', numberValue('crop-bottom'));
    form.append('margin_left', numberValue('crop-left'));
    form.append('page_size', pageSize.value);
    form.append('orientation', document.getElementById('crop-orientation').value);
    form.append('custom_width', numberValue('crop-custom-width'));
    form.append('custom_height', numberValue('crop-custom-height'));

    try{
      const res = await apiFetch('/api/pdf/crop-resize', { method:'POST', body: form });
      if(!res.ok){
        throw new Error(await readError(res, 'Crop / resize failed.'));
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const suffix = pageSize.value === 'cropped' ? '-cropped.pdf' : '-resized.pdf';
      const outName = currentFile.name.replace(/\.pdf$/i, '') + suffix;
      linkCrop.href = url;
      linkCrop.download = outName;
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
