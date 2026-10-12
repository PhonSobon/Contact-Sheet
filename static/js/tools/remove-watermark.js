// REMOVE WATERMARK — PDF mode (detect on upload, then remove what the user
// picks) and the PDF / Image mode switch. Image mode: remove-watermark-image.js.
import { apiFetch, readError } from '../core/api.js';
import { bytesToSize } from '../core/format.js';
import { showStatus } from '../core/notify.js';
import { initRemoveWatermarkImage } from './remove-watermark-image.js';

export function initRemoveWatermark(){
  initModeSwitch();
  initRemoveWatermarkImage();
  initPdfMode();
}

function initModeSwitch(){
  const modes = {
    pdf: { btn: document.getElementById('wm-mode-pdf'), block: document.getElementById('wm-pdf-block'), results: document.getElementById('results-unwatermark') },
    img: { btn: document.getElementById('wm-mode-img'), block: document.getElementById('wm-img-block'), results: document.getElementById('results-unwatermark-img') },
  };
  Object.entries(modes).forEach(([key, m])=> m.btn.addEventListener('click', ()=>{
    Object.entries(modes).forEach(([k, other])=>{
      const on = k === key;
      other.btn.classList.toggle('active', on);
      other.btn.setAttribute('aria-selected', on);
      other.block.style.display = on ? 'block' : 'none';
      // Each mode keeps its results; show only the open mode's.
      if(!on) other.results.dataset.hidden = other.results.style.display === 'block' ? '1' : '';
      if(!on) other.results.style.display = 'none';
      else if(other.results.dataset.hidden === '1') other.results.style.display = 'block';
    });
  }));
}

function bindRange(id){
  const input = document.getElementById(id);
  const out = document.getElementById(id + '-val');
  const sync = ()=>{ out.textContent = input.value; };
  input.addEventListener('input', sync);
  sync();
  return input;
}

function initPdfMode(){
  const drop = document.getElementById('drop-unwatermark');
  const fileInput = document.getElementById('file-unwatermark');
  const primary = document.getElementById('drop-unwatermark-primary');
  const btn = document.getElementById('btn-unwatermark');
  const status = document.getElementById('status-unwatermark');
  const scan = document.getElementById('scan-unwatermark');
  const found = document.getElementById('wm-found');
  const summary = document.getElementById('wm-summary');
  const candidatesEl = document.getElementById('wm-candidates');
  const textInput = document.getElementById('wm-remove-text');
  const stampsSelect = document.getElementById('wm-remove-stamps');
  const scanLight = document.getElementById('wm-pdf-light');
  const scanStrength = bindRange('wm-pdf-strength');
  const scanColorOn = document.getElementById('wm-pdf-color-on');
  const scanColor = document.getElementById('wm-pdf-color');
  const scanTolerance = bindRange('wm-pdf-tolerance');
  const scanHint = document.getElementById('wm-pdf-scan-hint');
  const scanHintDefault = scanHint.textContent;
  const resultsWrap = document.getElementById('results-unwatermark');
  const meta = document.getElementById('meta-unwatermark');
  const link = document.getElementById('link-unwatermark');
  const outNameLabel = document.getElementById('unwatermark-out-name');

  let currentFile = null;
  let lastUrl = null;
  let detectToken = 0;

  const setStatus = (msg, kind)=> showStatus(status, msg, kind);

  function plural(n, word){ return n + ' ' + word + (n === 1 ? '' : 's'); }

  function renderDetection(data){
    const structural = [];
    if(data.marked_watermarks) structural.push('<strong>' + plural(data.marked_watermarks, 'watermark layer') + '</strong>');
    if(data.acrobat_watermarks) structural.push('<strong>' + plural(data.acrobat_watermarks, 'Acrobat watermark') + '</strong>');
    if(data.watermark_annotations) structural.push('<strong>' + plural(data.watermark_annotations, 'watermark annotation') + '</strong>');

    let text = structural.length
      ? structural.join(', ') + ' — these are removed automatically.'
      : 'No tagged watermark layers.';
    text += data.text_candidates.length
      ? ' Text that looks like a watermark is listed below — tick what to remove.'
      : ' No text that looks like a watermark — type it below if you can see one.';
    summary.innerHTML = text;

    // Scanned pages: the watermark is in the page picture, so suggest the cleanup.
    if(data.scanned_pages){
      scanLight.checked = true;
      scanHint.textContent = plural(data.scanned_pages, 'page') + ' of this PDF ' + (data.scanned_pages === 1 ? 'is a' : 'are') +
        ' scanned image' + (data.scanned_pages === 1 ? '' : 's') + ', so "Remove pale watermark" is turned on. ' + scanHintDefault;
    }else{
      scanHint.textContent = scanHintDefault;
    }

    candidatesEl.innerHTML = '';
    data.text_candidates.forEach(c=>{
      const chip = document.createElement('label');
      chip.className = 'wm-chip';
      chip.innerHTML = '<input type="checkbox" /><span class="wm-chip-text"></span><span class="wm-chip-meta"></span>';
      chip.querySelector('input').checked = c.likely;
      chip.querySelector('input').value = c.text;
      chip.querySelector('.wm-chip-text').textContent = c.text;
      chip.querySelector('.wm-chip-text').title = c.text;
      const bits = [plural(c.pages, 'page')];
      if(c.rotated) bits.push('rotated');
      if(c.font_size >= 28) bits.push('large');
      chip.querySelector('.wm-chip-meta').textContent = bits.join(' · ');
      candidatesEl.appendChild(chip);
    });
    found.style.display = 'block';
  }

  async function detect(file){
    const token = ++detectToken;
    found.style.display = 'none';
    scan.classList.add('active');
    setStatus('Looking for watermarks in ' + file.name + '…');
    const form = new FormData();
    form.append('file', file);
    try{
      const res = await apiFetch('/api/pdf/watermark/detect', { method:'POST', body: form });
      if(!res.ok) throw new Error(await readError(res, 'Could not read that PDF.'));
      const data = await res.json();
      if(token !== detectToken) return;  // a newer file was chosen meanwhile
      renderDetection(data);
      setStatus('');
    }catch(err){
      if(token !== detectToken) return;
      setStatus(err.message || 'Could not read that PDF.', 'error');
    }finally{
      if(token === detectToken) scan.classList.remove('active');
    }
  }

  function setFile(f){
    if(!f) return;
    if(!(f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf'))){
      setStatus('That doesn\'t look like a PDF.', 'error');
      return;
    }
    currentFile = f;
    primary.textContent = f.name + ' — ' + bytesToSize(f.size);
    btn.disabled = false;
    resultsWrap.style.display = 'none';
    detect(f);
  }

  function chosenTexts(){
    const picked = [...candidatesEl.querySelectorAll('input:checked')].map(i=> i.value);
    const typed = textInput.value.split(',').map(t=> t.trim()).filter(Boolean);
    return [...new Set([...picked, ...typed])];
  }

  drop.addEventListener('click', ()=>fileInput.click());
  drop.addEventListener('keydown', e=>{ if(e.key==='Enter' || e.key===' '){ e.preventDefault(); fileInput.click(); }});
  fileInput.addEventListener('change', e=>{ setFile(e.target.files[0]); fileInput.value = ''; });
  ['dragenter','dragover'].forEach(evt=> drop.addEventListener(evt, e=>{ e.preventDefault(); drop.classList.add('drag'); }));
  ['dragleave','drop'].forEach(evt=> drop.addEventListener(evt, e=>{ e.preventDefault(); drop.classList.remove('drag'); }));
  drop.addEventListener('drop', e=> setFile(e.dataTransfer.files[0]));

  btn.addEventListener('click', async ()=>{
    if(!currentFile) return;
    btn.disabled = true;
    scan.classList.add('active');
    setStatus('Removing watermark from ' + currentFile.name + '…');
    resultsWrap.style.display = 'none';

    const form = new FormData();
    form.append('file', currentFile);
    form.append('texts', JSON.stringify(chosenTexts()));
    form.append('remove_stamps', stampsSelect.value);
    form.append('images_light', scanLight.checked ? 'true' : 'false');
    form.append('images_light_strength', scanStrength.value);
    form.append('images_color', scanColorOn.checked ? scanColor.value : '');
    form.append('images_tolerance', scanTolerance.value);

    try{
      const res = await apiFetch('/api/pdf/remove-watermark', { method:'POST', body: form });
      if(!res.ok) throw new Error(await readError(res, 'Could not remove the watermark.'));
      const blob = await res.blob();
      const num = h=> Number(res.headers.get(h) || 0);
      const removed = [];
      if(num('X-Removed-Text')) removed.push(plural(num('X-Removed-Text'), 'text watermark'));
      if(num('X-Removed-Marked')) removed.push(plural(num('X-Removed-Marked'), 'watermark layer'));
      if(num('X-Removed-XObjects')) removed.push(plural(num('X-Removed-XObjects'), 'watermark object'));
      if(num('X-Removed-Annotations')) removed.push(plural(num('X-Removed-Annotations'), 'annotation'));

      const parts = [];
      if(removed.length) parts.push('Removed ' + removed.join(', '));
      if(num('X-Cleaned-Images')) parts.push((parts.length ? 'cleaned ' : 'Cleaned ') + plural(num('X-Cleaned-Images'), 'scanned page image'));
      const summaryText = parts.join(' and ');

      if(lastUrl) URL.revokeObjectURL(lastUrl);
      lastUrl = URL.createObjectURL(blob);
      const outName = currentFile.name.replace(/\.pdf$/i, '') + '-no-watermark.pdf';
      link.href = lastUrl;
      link.download = outName;
      outNameLabel.textContent = outName;
      meta.textContent = summaryText + ' · ' + bytesToSize(blob.size);
      resultsWrap.style.display = 'block';
      setStatus(summaryText + '.', 'ok');
    }catch(err){
      setStatus(err.message || 'Something went wrong.', 'error');
    }finally{
      scan.classList.remove('active');
      btn.disabled = false;
    }
  });
}
