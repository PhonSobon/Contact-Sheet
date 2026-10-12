// REMOVE PAGES (in-place delete, original quality kept)
import { apiFetch, readError } from '../core/api.js';
import { bytesToSize } from '../core/format.js';
import { showStatus } from '../core/notify.js';

export function initRemovePages(){
  const drop = document.getElementById('drop-rmpages');
  const fileInput = document.getElementById('file-rmpages');
  const primary = document.getElementById('drop-rmpages-primary');
  const hint = document.getElementById('rmpages-hint');
  const grid = document.getElementById('rmpages-grid');
  const controls = document.getElementById('controls-rmpages');
  const rangeInput = document.getElementById('rmpages-input');
  const btnClear = document.getElementById('btn-rmpages-clear');
  const btn = document.getElementById('btn-rmpages');
  const status = document.getElementById('status-rmpages');
  const scan = document.getElementById('scan-rmpages');
  const resultsWrap = document.getElementById('results-rmpages');
  const meta = document.getElementById('meta-rmpages');
  const link = document.getElementById('link-rmpages');
  const outNameLabel = document.getElementById('rmpages-out-name');

  let sourceFile = null;
  let pageCount = 0;
  let marked = new Set();   // 1-based page numbers to remove
  let lastUrl = null;

  const setStatus = (msg, kind)=> showStatus(status, msg, kind);

  // Set of page numbers -> "2, 5-7"
  function toRanges(set){
    const nums = Array.from(set).sort((a,b)=>a-b);
    const parts = [];
    for(let i=0;i<nums.length;i++){
      let j = i;
      while(j+1 < nums.length && nums[j+1] === nums[j]+1) j++;
      parts.push(i === j ? String(nums[i]) : nums[i] + '-' + nums[j]);
      i = j;
    }
    return parts.join(', ');
  }

  // "2, 5-7" -> Set, or throws with a readable message
  function fromRanges(text){
    const out = new Set();
    text.replace(/\s+/g, '').split(',').filter(Boolean).forEach(tok=>{
      const m = tok.match(/^(\d+)(?:-(\d+))?$/);
      if(!m) throw new Error('"' + tok + '" isn\'t a valid page or range.');
      let lo = parseInt(m[1], 10), hi = m[2] ? parseInt(m[2], 10) : lo;
      if(lo > hi) [lo, hi] = [hi, lo];
      if(lo < 1 || hi > pageCount) throw new Error('Page "' + tok + '" is out of range — this PDF has ' + pageCount + ' pages.');
      for(let n=lo;n<=hi;n++) out.add(n);
    });
    return out;
  }

  function refresh(){
    grid.querySelectorAll('.page-card').forEach(card=>{
      card.classList.toggle('marked', marked.has(Number(card.dataset.page)));
    });
    const keepCount = pageCount - marked.size;
    btn.disabled = marked.size === 0 || keepCount < 1;
    if(marked.size === 0) setStatus('');
    else if(keepCount < 1) setStatus('You can\'t remove every page — at least one must remain.', 'error');
    else setStatus(marked.size + ' page' + (marked.size===1?'':'s') + ' marked for removal · ' + keepCount + ' will remain.');
  }

  async function loadFile(f){
    if(!f) return;
    if(!(f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf'))){
      setStatus('That doesn\'t look like a PDF.', 'error');
      return;
    }
    setStatus('Reading ' + f.name + '…');
    resultsWrap.style.display = 'none';
    const form = new FormData();
    form.append('files', f);
    form.append('thumb_dpi', '60');

    try{
      const res = await apiFetch('/api/pdf/inspect', { method:'POST', body: form });
      if(!res.ok){
        throw new Error(await readError(res, 'Could not read that PDF.'));
      }
      const data = await res.json();
      const src = data.sources[0];
      sourceFile = f;
      pageCount = src.page_count;
      marked = new Set();
      rangeInput.value = '';

      grid.innerHTML = '';
      src.pages.forEach(p=>{
        const n = p.page_index + 1;
        const card = document.createElement('div');
        card.className = 'page-card selectable';
        card.dataset.page = n;
        card.title = 'Page ' + n + ' — click to remove / keep';
        card.innerHTML = `
          <div class="page-thumb-wrap"><img src="${p.data_url}" alt="page ${n}" /></div>
          <div class="page-foot"><span class="page-label">Page ${n}</span></div>
        `;
        grid.appendChild(card);
      });

      primary.textContent = f.name + ' — ' + pageCount + ' page' + (pageCount===1?'':'s') + ' · ' + bytesToSize(f.size);
      hint.style.display = 'block';
      controls.style.display = 'flex';
      refresh();
    }catch(err){
      setStatus(err.message || 'Something went wrong.', 'error');
    }
  }

  drop.addEventListener('click', ()=>fileInput.click());
  drop.addEventListener('keydown', e=>{ if(e.key==='Enter' || e.key===' '){ e.preventDefault(); fileInput.click(); }});
  fileInput.addEventListener('change', e=>{ loadFile(e.target.files[0]); fileInput.value=''; });
  ['dragenter','dragover'].forEach(evt=> drop.addEventListener(evt, e=>{ e.preventDefault(); drop.classList.add('drag'); }));
  ['dragleave','drop'].forEach(evt=> drop.addEventListener(evt, e=>{ e.preventDefault(); drop.classList.remove('drag'); }));
  drop.addEventListener('drop', e=> loadFile(e.dataTransfer.files[0]));

  grid.addEventListener('click', e=>{
    const card = e.target.closest('.page-card');
    if(!card) return;
    const n = Number(card.dataset.page);
    if(marked.has(n)) marked.delete(n); else marked.add(n);
    rangeInput.value = toRanges(marked);
    refresh();
  });

  rangeInput.addEventListener('input', ()=>{
    try{
      marked = fromRanges(rangeInput.value);
      refresh();
    }catch(err){
      btn.disabled = true;
      setStatus(err.message, 'error');
    }
  });

  btnClear.addEventListener('click', ()=>{
    marked = new Set();
    rangeInput.value = '';
    refresh();
  });

  btn.addEventListener('click', async ()=>{
    if(!sourceFile || marked.size === 0) return;
    btn.disabled = true;
    scan.classList.add('active');
    setStatus('Removing ' + marked.size + ' page' + (marked.size===1?'':'s') + '…');
    resultsWrap.style.display = 'none';

    const form = new FormData();
    form.append('file', sourceFile);
    form.append('pages', toRanges(marked));

    try{
      const res = await apiFetch('/api/pdf/remove-pages', { method:'POST', body: form });
      if(!res.ok){
        throw new Error(await readError(res, 'Could not remove those pages.'));
      }
      const blob = await res.blob();
      if(lastUrl) URL.revokeObjectURL(lastUrl);
      lastUrl = URL.createObjectURL(blob);
      const outName = sourceFile.name.replace(/\.pdf$/i, '') + '-pages-removed.pdf';
      link.href = lastUrl;
      link.download = outName;
      outNameLabel.textContent = outName;
      const remaining = res.headers.get('X-Output-Pages') || (pageCount - marked.size);
      meta.textContent = remaining + ' page' + (remaining==1?'':'s') + ' · ' + bytesToSize(sourceFile.size) + ' → ' + bytesToSize(blob.size) + ' · original quality';
      resultsWrap.style.display = 'block';
      setStatus('Done — removed pages ' + toRanges(marked) + '.', 'ok');
    }catch(err){
      setStatus(err.message || 'Something went wrong.', 'error');
    }finally{
      scan.classList.remove('active');
      btn.disabled = false;
    }
  });
}
