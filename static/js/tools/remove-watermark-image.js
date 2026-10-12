// REMOVE WATERMARK — image mode: mark the watermark (or use automatic
// cleanup), then send every image with its mask to the API.
import { apiFetch, readError } from '../core/api.js';
import { downloadBase64 } from '../core/download.js';
import { bytesToSize } from '../core/format.js';
import { showStatus } from '../core/notify.js';
import { MaskEditor } from './mask-editor.js';

const MAX_IMAGES = 10;
const IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/webp'];
const $ = id=> document.getElementById(id);

function bindRange(input, output){
  const sync = ()=>{ output.textContent = input.value; };
  input.addEventListener('input', sync);
  sync();
}

function loadImage(file){
  return new Promise((resolve, reject)=>{
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = ()=> resolve({ img, url });
    img.onerror = ()=>{ URL.revokeObjectURL(url); reject(new Error('\'' + file.name + '\' couldn\'t be opened as an image.')); };
    img.src = url;
  });
}

export function initRemoveWatermarkImage(){
  const drop = $('drop-unwatermark-img');
  const fileInput = $('file-unwatermark-img');
  const primary = $('drop-unwatermark-img-primary');
  const editorWrap = $('wm-editor');
  const thumbs = $('wm-thumbs');
  const btn = $('btn-unwatermark-img');
  const status = $('status-unwatermark-img');
  const scan = $('scan-unwatermark');
  const resultsWrap = $('results-unwatermark-img');
  const grid = $('grid-unwatermark-img');
  const meta = $('meta-unwatermark-img');
  const sizeInput = $('wm-brush-size');
  const toolButtons = [...document.querySelectorAll('.wm-toolbar [data-tool]')];
  const light = $('wm-img-light'), strength = $('wm-img-strength');
  const colorOn = $('wm-img-color-on'), color = $('wm-img-color'), tolerance = $('wm-img-tolerance');
  const fill = $('wm-img-fill'), format = $('wm-img-format');
  const stageHint = $('wm-stage-hint');

  const setStatus = (msg, kind)=> showStatus(status, msg, kind);
  bindRange(sizeInput, $('wm-brush-size-val'));
  bindRange(strength, $('wm-img-strength-val'));
  bindRange(tolerance, $('wm-img-tolerance-val'));

  let items = [];       // { file, img, url, ops, w, h }
  let current = -1;
  let zip = null;

  const editor = new MaskEditor({
    canvas: $('wm-canvas'), stage: $('wm-stage'), cursor: $('wm-cursor'),
    onChange: ()=> renderThumbs(),
    onPick: hex=>{
      color.value = hex;
      colorOn.checked = true;
      setStatus('Picked ' + hex + ' — every pixel close to this colour will be removed. Adjust Tolerance if needed.');
    },
  });

  // ---------------------------------------------------------------- tools
  const HINTS = {
    brush: 'Paint over the watermark — the marked area (red) is filled in from its surroundings.',
    box: 'Drag a rectangle over the watermark.',
    erase: 'Paint over marks to remove them.',
    pick: 'Click the watermark to remove its colour from every image.',
  };
  function setTool(tool){
    toolButtons.forEach(b=>{
      const on = b.dataset.tool === tool;
      b.classList.toggle('active', on);
      b.setAttribute('aria-checked', on);
    });
    editor.setTool(tool);
    stageHint.textContent = HINTS[tool];
  }
  toolButtons.forEach(b=> b.addEventListener('click', ()=> setTool(b.dataset.tool)));
  sizeInput.addEventListener('input', ()=> editor.setSize(Number(sizeInput.value)));
  $('wm-undo').addEventListener('click', ()=> editor.undo());
  $('wm-clear').addEventListener('click', ()=> editor.clear());

  document.addEventListener('keydown', e=>{
    if(editorWrap.offsetParent === null || current < 0) return;   // image mode not visible
    if(e.target.closest('input, textarea, select, [contenteditable]')) return;
    if((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z'){ e.preventDefault(); editor.undo(); return; }
    if(e.ctrlKey || e.metaKey || e.altKey) return;
    const tool = { b: 'brush', r: 'box', e: 'erase', i: 'pick' }[e.key.toLowerCase()];
    if(tool){ setTool(tool); return; }
    if(e.key === '[' || e.key === ']'){
      sizeInput.value = Number(sizeInput.value) + (e.key === ']' ? 6 : -6);
      sizeInput.dispatchEvent(new Event('input'));
    }
  });

  // ---------------------------------------------------------------- images
  function renderThumbs(){
    thumbs.innerHTML = '';
    items.forEach((it, i)=>{
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'wm-thumb' + (i === current ? ' active' : '');
      b.title = it.file.name;
      b.setAttribute('aria-label', 'Edit ' + it.file.name);
      b.innerHTML = '<img alt="" />' + (it.ops.length ? '<span class="wm-thumb-badge">marked</span>' : '') +
        '<span class="wm-thumb-remove" role="button" aria-label="Remove image">✕</span>';
      b.querySelector('img').src = it.url;
      b.addEventListener('click', e=>{
        if(e.target.closest('.wm-thumb-remove')) removeItem(i);
        else select(i);
      });
      thumbs.appendChild(b);
    });
    primary.textContent = items.length
      ? items.length + ' image' + (items.length === 1 ? '' : 's') + ' — drop or paste more to add'
      : 'Drop images here, or click to choose files';
    editorWrap.style.display = items.length ? 'block' : 'none';
    btn.disabled = !items.length;
  }

  function select(i){
    current = i;
    editor.load(items[i]);
    renderThumbs();
  }

  function removeItem(i){
    URL.revokeObjectURL(items[i].url);
    items.splice(i, 1);
    if(!items.length){ current = -1; renderThumbs(); return; }
    select(Math.min(i, items.length - 1));
  }

  async function addFiles(fileList){
    const all = [...fileList];
    const images = all.filter(f=> IMAGE_TYPES.includes(f.type) || /\.(png|jpe?g|webp)$/i.test(f.name));
    if(!images.length){ setStatus('Those don\'t look like PNG, JPG or WEBP images.', 'error'); return; }
    const room = MAX_IMAGES - items.length;
    if(room <= 0){ setStatus('Up to ' + MAX_IMAGES + ' images at a time.', 'error'); return; }

    const added = [];
    for(const file of images.slice(0, room)){
      try{
        const { img, url } = await loadImage(file);
        added.push({ file, img, url, ops: [] });
      }catch(err){
        setStatus(err.message, 'error');
      }
    }
    if(!added.length) return;
    items.push(...added);
    resultsWrap.style.display = 'none';
    select(items.length - added.length);
    const skipped = images.length - Math.min(images.length, room);
    if(skipped) setStatus(skipped + ' image' + (skipped === 1 ? ' was' : 's were') + ' skipped — up to ' + MAX_IMAGES + ' at a time.', 'error');
    else if(images.length < all.length) setStatus('Skipped files that aren\'t images.', 'error');
    else setStatus('');
  }

  drop.addEventListener('click', ()=> fileInput.click());
  drop.addEventListener('keydown', e=>{ if(e.key === 'Enter' || e.key === ' '){ e.preventDefault(); fileInput.click(); }});
  fileInput.addEventListener('change', e=>{ addFiles(e.target.files); fileInput.value = ''; });
  ['dragenter', 'dragover'].forEach(evt=> drop.addEventListener(evt, e=>{ e.preventDefault(); drop.classList.add('drag'); }));
  ['dragleave', 'drop'].forEach(evt=> drop.addEventListener(evt, e=>{ e.preventDefault(); drop.classList.remove('drag'); }));
  drop.addEventListener('drop', e=> addFiles(e.dataTransfer.files));

  // ---------------------------------------------------------------- run
  function autoOn(){ return light.checked || colorOn.checked; }

  btn.addEventListener('click', async ()=>{
    if(!items.length) return;
    const unmarked = items.filter(it=> !it.ops.length);
    if(unmarked.length && !autoOn()){
      setStatus(unmarked.length === items.length
        ? 'Paint over the watermark first, or turn on an automatic cleanup option below.'
        : '\'' + unmarked[0].file.name + '\' has no marks — paint over its watermark, remove it from the list, or turn on an automatic cleanup option.', 'error');
      if(unmarked.length !== items.length) select(items.indexOf(unmarked[0]));
      return;
    }

    btn.disabled = true;
    scan.classList.add('active');
    resultsWrap.style.display = 'none';
    setStatus('Removing watermark from ' + items.length + ' image' + (items.length === 1 ? '' : 's') + '…');

    try{
      const form = new FormData();
      for(let i = 0; i < items.length; i++){
        form.append('files', items[i].file);
        const mask = await MaskEditor.exportMask(items[i]);
        if(mask) form.append('masks', mask, 'mask-' + i + '.png');
      }
      form.append('light', light.checked ? 'true' : 'false');
      form.append('light_strength', strength.value);
      form.append('color', colorOn.checked ? color.value : '');
      form.append('tolerance', tolerance.value);
      form.append('fill', fill.value);
      form.append('output_format', format.value);

      const res = await apiFetch('/api/image/remove-watermark', { method: 'POST', body: form });
      if(!res.ok) throw new Error(await readError(res, 'Could not remove the watermark.'));
      const data = await res.json();
      zip = { base64: data.zip_base64, name: data.zip_filename };
      renderResults(data.results);
      setStatus('Cleaned ' + data.results.length + ' image' + (data.results.length === 1 ? '' : 's') + '.', 'ok');
    }catch(err){
      setStatus(err.message || 'Something went wrong.', 'error');
    }finally{
      scan.classList.remove('active');
      btn.disabled = !items.length;
    }
  });

  function renderResults(results){
    grid.innerHTML = '';
    results.forEach(r=>{
      const source = items[r.index];
      const card = document.createElement('div');
      card.className = 'print-card transparent wm-result';
      card.innerHTML = `
        <div class="sprocket-strip"><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span></div>
        <img alt="" title="Press and hold to compare with the original" />
        <div class="print-caption">
          <span class="fname"></span>
          <div class="meta"><span></span><a download>↓</a></div>
          <div class="wm-result-actions">
            <button type="button" data-act="compare">Hold to compare</button>
            <button type="button" data-act="again">Keep editing</button>
          </div>
        </div>`;
      const img = card.querySelector('img');
      img.src = r.data_url;
      img.alt = r.filename;
      card.querySelector('.fname').textContent = r.filename;
      card.querySelector('.meta span').textContent = r.width + '×' + r.height + ' · ' + bytesToSize(r.size_bytes);
      const a = card.querySelector('a');
      a.href = r.data_url; a.download = r.filename;

      // Press and hold (image or button) to see the original.
      const show = on=>{ if(source) img.src = on ? source.url : r.data_url; };
      [img, card.querySelector('[data-act="compare"]')].forEach(el=>{
        el.addEventListener('pointerdown', ()=> show(true));
        ['pointerup', 'pointerleave', 'pointercancel'].forEach(evt=> el.addEventListener(evt, ()=> show(false)));
      });

      // Continue from the result: it replaces the original in the editor.
      card.querySelector('[data-act="again"]').addEventListener('click', async ()=>{
        const blob = await (await fetch(r.data_url)).blob();
        const file = new File([blob], r.filename, { type: blob.type });
        const { img: loaded, url } = await loadImage(file);
        const i = items.indexOf(source);
        if(i === -1) return;
        URL.revokeObjectURL(source.url);
        items[i] = { file, img: loaded, url, ops: [] };
        select(i);
        editorWrap.scrollIntoView({ behavior: 'smooth', block: 'start' });
        setStatus('Now editing the cleaned ' + file.name + ' — mark anything that\'s left.');
      });
      grid.appendChild(card);
    });
    meta.textContent = results.length + ' image' + (results.length === 1 ? '' : 's') + ' cleaned · press and hold an image to compare';
    resultsWrap.style.display = 'block';
  }

  $('btn-zip-unwatermark-img').addEventListener('click', ()=>{
    if(zip) downloadBase64(zip.base64, zip.name, 'application/zip');
  });

  // Re-fit the canvas overlay cursor if the layout changes.
  window.addEventListener('resize', ()=> editor.setSize(Number(sizeInput.value)));
}
