// COMBINE PDF (every page shown, drag to rearrange)
import { apiFetch, readError } from '../core/api.js';
import { bytesToSize } from '../core/format.js';
import { showStatus } from '../core/notify.js';

export function initCombine(){
  const drop = document.getElementById('drop-combine');
  const fileInput = document.getElementById('file-combine');
  const primary = document.getElementById('drop-combine-primary');
  const chips = document.getElementById('combine-sources');
  const grid = document.getElementById('combine-grid');
  const hint = document.getElementById('combine-hint');
  const controls = document.getElementById('controls-combine');
  const btn = document.getElementById('btn-combine');
  const btnReset = document.getElementById('btn-combine-reset');
  const status = document.getElementById('status-combine');
  const scan = document.getElementById('scan-combine');
  const resultsWrap = document.getElementById('results-combine');
  const meta = document.getElementById('meta-combine');
  const nameInput = document.getElementById('combine-name');
  const link = document.getElementById('link-combine');
  const outNameLabel = document.getElementById('combine-out-name');

  const MAX_FILES = 10;
  const MAX_TOTAL_PAGES = 400;
  const COLORS = ['#7c93ff','#f2a541','#3ecf8e','#ff7a72','#c084fc','#22c1d6','#e879a6','#a3b34a','#f97316','#64748b'];

  let sources = [];   // {file, color, page_count, removed}; index = source id
  let pageList = [];  // {key, source, page_index, data_url} in final order
  let cards = new Map();  // key -> card element, reused so moves don't re-decode thumbnails
  let keyCounter = 0;
  let colorCounter = 0;
  let dragKey = null;
  let dropTarget = null;  // {key, before}
  let lastUrl = null;

  const setStatus = (msg, kind)=> showStatus(status, msg, kind);

  function liveSources(){ return sources.filter(s=> !s.removed); }

  function renderChips(){
    chips.innerHTML = '';
    sources.forEach((s, id)=>{
      if(s.removed) return;
      const left = pageList.filter(p=> p.source === id).length;
      const chip = document.createElement('div');
      chip.className = 'source-chip';
      chip.style.setProperty('--src-color', s.color);
      chip.innerHTML = '<span class="dot"></span><span class="name"></span><span class="count"></span><button type="button" aria-label="Remove this file">✕</button>';
      chip.querySelector('.name').textContent = s.file.name;
      chip.querySelector('.name').title = s.file.name;
      chip.querySelector('.count').textContent = left === s.page_count ? left + 'p' : left + '/' + s.page_count + 'p';
      chip.querySelector('button').dataset.source = id;
      chips.appendChild(chip);
    });
  }

  function makeCard(p){
    const s = sources[p.source];
    const card = document.createElement('div');
    card.className = 'page-card draggable';
    card.draggable = true;
    card.dataset.key = p.key;
    card.style.setProperty('--src-color', s.color);
    card.innerHTML = `
      <span class="page-badge"></span>
      <div class="page-thumb-wrap"><img src="${p.data_url}" alt="" draggable="false" /></div>
      <div class="page-foot">
        <span class="page-label"></span>
        <div class="page-actions">
          <button type="button" data-act="left" aria-label="Move earlier">←</button>
          <button type="button" data-act="right" aria-label="Move later">→</button>
          <button type="button" data-act="remove" class="remove" aria-label="Remove page">✕</button>
        </div>
      </div>
    `;
    const label = s.file.name + ' · p.' + (p.page_index + 1);
    card.querySelector('.page-label').textContent = label;
    card.querySelector('.page-label').title = label;
    return card;
  }

  function renderGrid(){
    // Reorder existing cards instead of rebuilding them.
    const live = new Set(pageList.map(p=> p.key));
    cards.forEach((card, key)=>{ if(!live.has(key)){ card.remove(); cards.delete(key); }});
    pageList.forEach((p, idx)=>{
      let card = cards.get(p.key);
      if(!card){ card = makeCard(p); cards.set(p.key, card); }
      card.querySelector('.page-badge').textContent = idx + 1;
      grid.appendChild(card);  // appendChild moves an existing node
    });

    renderChips();
    const n = liveSources().length;
    const has = pageList.length > 0;
    primary.textContent = n
      ? n + ' PDF' + (n===1?'':'s') + ' · ' + pageList.length + ' page' + (pageList.length===1?'':'s') + ' in the combined file — drop more to add'
      : 'Drop PDFs here, or click to choose files';
    hint.style.display = has ? 'block' : 'none';
    controls.style.display = has ? 'flex' : 'none';
    btn.disabled = !has;
    if(!has) resultsWrap.style.display = 'none';
  }

  async function addFiles(fileList){
    let pdfs = Array.from(fileList).filter(f=> f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf'));
    if(pdfs.length === 0){
      setStatus('Those do not look like PDFs.', 'error');
      return;
    }
    const room = MAX_FILES - liveSources().length;
    if(room <= 0){
      setStatus('Up to ' + MAX_FILES + ' PDFs at a time.', 'error');
      return;
    }
    const skipped = Math.max(0, pdfs.length - room);
    pdfs = pdfs.slice(0, room);

    setStatus('Reading ' + pdfs.length + ' file' + (pdfs.length===1?'':'s') + '…');
    scan.classList.add('active');
    const form = new FormData();
    pdfs.forEach(f=> form.append('files', f));
    form.append('thumb_dpi', '60');

    try{
      const res = await apiFetch('/api/pdf/inspect', { method:'POST', body: form });
      if(!res.ok){
        throw new Error(await readError(res, 'Could not read those PDFs.'));
      }
      const data = await res.json();
      const incoming = data.sources.reduce((sum, src)=> sum + src.page_count, 0);
      if(pageList.length + incoming > MAX_TOTAL_PAGES){
        throw new Error('That would be ' + (pageList.length + incoming) + ' pages — the limit is ' + MAX_TOTAL_PAGES + '.');
      }

      data.sources.forEach(src=>{
        const id = sources.length;
        sources.push({ file: pdfs[src.source_index], color: COLORS[colorCounter++ % COLORS.length], page_count: src.page_count, removed: false });
        src.pages.forEach(p=>{
          pageList.push({ key: 'c' + (keyCounter++), source: id, page_index: p.page_index, data_url: p.data_url });
        });
      });

      resultsWrap.style.display = 'none';
      renderGrid();
      if(skipped) setStatus(skipped + ' file' + (skipped===1?' was':'s were') + ' skipped — up to ' + MAX_FILES + ' PDFs at a time.', 'error');
      else setStatus(liveSources().length < 2 ? 'Add another PDF to combine, or rearrange these pages.' : '');
    }catch(err){
      setStatus(err.message || 'Something went wrong.', 'error');
    }finally{
      scan.classList.remove('active');
    }
  }

  function movePage(key, targetKey, before){
    const from = pageList.findIndex(p=> p.key === key);
    if(from === -1 || key === targetKey) return;
    const [item] = pageList.splice(from, 1);
    let to = pageList.findIndex(p=> p.key === targetKey);
    if(to === -1){ pageList.splice(from, 0, item); return; }
    if(!before) to++;
    pageList.splice(to, 0, item);
    resultsWrap.style.display = 'none';
    renderGrid();
  }

  drop.addEventListener('click', ()=>fileInput.click());
  drop.addEventListener('keydown', e=>{ if(e.key==='Enter' || e.key===' '){ e.preventDefault(); fileInput.click(); }});
  fileInput.addEventListener('change', e=>{ addFiles(e.target.files); fileInput.value=''; });
  ['dragenter','dragover'].forEach(evt=> drop.addEventListener(evt, e=>{ e.preventDefault(); drop.classList.add('drag'); }));
  ['dragleave','drop'].forEach(evt=> drop.addEventListener(evt, e=>{ e.preventDefault(); drop.classList.remove('drag'); }));
  drop.addEventListener('drop', e=> addFiles(e.dataTransfer.files));

  chips.addEventListener('click', e=>{
    const b = e.target.closest('button');
    if(!b) return;
    const id = Number(b.dataset.source);
    sources[id].removed = true;
    pageList = pageList.filter(p=> p.source !== id);
    resultsWrap.style.display = 'none';
    renderGrid();
    setStatus('');
  });

  grid.addEventListener('click', e=>{
    const b = e.target.closest('button');
    if(!b) return;
    const key = b.closest('.page-card').dataset.key;
    const idx = pageList.findIndex(p=> p.key === key);
    if(idx === -1) return;
    const act = b.dataset.act;
    if(act === 'remove'){
      const id = pageList[idx].source;
      pageList.splice(idx, 1);
      if(!pageList.some(p=> p.source === id)) sources[id].removed = true;
    } else if(act === 'left' && idx > 0){
      [pageList[idx-1], pageList[idx]] = [pageList[idx], pageList[idx-1]];
    } else if(act === 'right' && idx < pageList.length-1){
      [pageList[idx+1], pageList[idx]] = [pageList[idx], pageList[idx+1]];
    } else {
      return;
    }
    resultsWrap.style.display = 'none';
    renderGrid();
  });

  // ---- drag & drop reordering ----
  function clearIndicators(){
    grid.querySelectorAll('.drop-before, .drop-after').forEach(c=> c.classList.remove('drop-before', 'drop-after'));
  }

  grid.addEventListener('dragstart', e=>{
    const card = e.target.closest('.page-card');
    if(!card) return;
    dragKey = card.dataset.key;
    dropTarget = null;
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', dragKey);  // Firefox won't start a drag without data
    // Fade on the next frame so the drag ghost image isn't faded too —
    // unless the drag already ended (a very quick drop).
    const key = dragKey;
    requestAnimationFrame(()=>{ if(dragKey === key) card.classList.add('dragging'); });
  });

  grid.addEventListener('dragover', e=>{
    if(!dragKey) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    const card = e.target.closest('.page-card');
    if(!card) return;  // over a gap between cards: keep the last indicator
    if(card.dataset.key === dragKey){ clearIndicators(); dropTarget = null; return; }
    const r = card.getBoundingClientRect();
    const before = e.clientX < r.left + r.width / 2;
    if(dropTarget && dropTarget.key === card.dataset.key && dropTarget.before === before) return;
    clearIndicators();
    card.classList.add(before ? 'drop-before' : 'drop-after');
    dropTarget = { key: card.dataset.key, before };
  });

  grid.addEventListener('drop', e=>{
    if(!dragKey) return;
    e.preventDefault();
    if(dropTarget) movePage(dragKey, dropTarget.key, dropTarget.before);
  });

  grid.addEventListener('dragend', ()=>{
    clearIndicators();
    grid.querySelectorAll('.dragging').forEach(c=> c.classList.remove('dragging'));
    dragKey = null;
    dropTarget = null;
  });

  btnReset.addEventListener('click', ()=>{
    // Back to file order, page order — removed pages stay removed.
    pageList.sort((a, b)=> a.source - b.source || a.page_index - b.page_index);
    resultsWrap.style.display = 'none';
    renderGrid();
  });

  btn.addEventListener('click', async ()=>{
    if(pageList.length === 0) return;
    btn.disabled = true;
    scan.classList.add('active');
    setStatus('Combining ' + pageList.length + ' page' + (pageList.length===1?'':'s') + '…');
    resultsWrap.style.display = 'none';

    // Only upload the files that still have pages in the plan.
    const used = [...new Set(pageList.map(p=> p.source))].sort((a,b)=> a-b);
    const remap = new Map(used.map((id, i)=> [id, i]));
    const plan = pageList.map(p=> ({ source_index: remap.get(p.source), page_index: p.page_index, rotate: 0 }));

    const outName = (nameInput.value || 'combined.pdf').trim() || 'combined.pdf';
    const finalName = outName.toLowerCase().endsWith('.pdf') ? outName : outName + '.pdf';
    const form = new FormData();
    used.forEach(id=> form.append('files', sources[id].file));
    form.append('plan', JSON.stringify(plan));
    form.append('compress', 'none');
    form.append('output_filename', finalName);

    try{
      const res = await apiFetch('/api/pdf/build', { method:'POST', body: form });
      if(!res.ok){
        throw new Error(await readError(res, 'Could not combine those PDFs.'));
      }
      const blob = await res.blob();
      if(lastUrl) URL.revokeObjectURL(lastUrl);
      lastUrl = URL.createObjectURL(blob);
      link.href = lastUrl;
      link.download = finalName;
      outNameLabel.textContent = finalName;
      meta.textContent = pageList.length + ' page' + (pageList.length===1?'':'s') + ' from ' + used.length + ' PDF' + (used.length===1?'':'s') + ' · ' + bytesToSize(blob.size);
      resultsWrap.style.display = 'block';
      setStatus('Done.', 'ok');
    }catch(err){
      setStatus(err.message || 'Something went wrong.', 'error');
    }finally{
      scan.classList.remove('active');
      btn.disabled = pageList.length === 0;
    }
  });
}
