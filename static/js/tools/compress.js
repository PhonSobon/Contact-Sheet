// COMPRESS
import { apiFetch, readError } from '../core/api.js';
import { bytesToSize } from '../core/format.js';
import { showStatus } from '../core/notify.js';

export function initCompress(){
  // sub-tab toggle
  const subPdf = document.getElementById('subtab-cpdf');
  const subImg = document.getElementById('subtab-cimg');
  const blockPdf = document.getElementById('cpdf-block');
  const blockImg = document.getElementById('cimg-block');
  function activateSub(which){
    const pdf = which === 'pdf';
    subPdf.classList.toggle('active', pdf);
    subImg.classList.toggle('active', !pdf);
    subPdf.setAttribute('aria-selected', pdf);
    subImg.setAttribute('aria-selected', !pdf);
    blockPdf.style.display = pdf ? 'block' : 'none';
    blockImg.style.display = pdf ? 'none' : 'block';
  }
  subPdf.addEventListener('click', ()=>activateSub('pdf'));
  subImg.addEventListener('click', ()=>activateSub('img'));

  // ---- PDF compress ----
  (function(){
    const drop = document.getElementById('drop-cpdf');
    const fileInput = document.getElementById('file-cpdf');
    const primary = document.getElementById('drop-cpdf-primary');
    const modeSelect = document.getElementById('cpdf-mode');
    const dpiField = document.getElementById('cpdf-dpi-field');
    const qualityField = document.getElementById('cpdf-quality-field');
    const dpiSelect = document.getElementById('cpdf-dpi');
    const qualitySelect = document.getElementById('cpdf-quality');
    const btn = document.getElementById('btn-cpdf');
    const status = document.getElementById('status-cpdf');
    const scan = document.getElementById('scan-compress');
    const resultsWrap = document.getElementById('results-cpdf');
    const meta = document.getElementById('meta-cpdf');
    const linkCpdf = document.getElementById('link-cpdf');
    const sizeBadge = document.getElementById('cpdf-size-badge');

    let currentFile = null;

    const setStatus = (msg, kind)=> showStatus(status, msg, kind);
    function toggleRasterFields(){
      const raster = modeSelect.value === 'rasterize';
      dpiField.style.display = raster ? 'flex' : 'none';
      qualityField.style.display = raster ? 'flex' : 'none';
    }
    modeSelect.addEventListener('change', toggleRasterFields);
    toggleRasterFields();

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

    btn.addEventListener('click', async ()=>{
      if(!currentFile) return;
      btn.disabled = true;
      scan.classList.add('active');
      setStatus('Inspecting ' + currentFile.name + '…');
      resultsWrap.style.display = 'none';
      const originalSize = currentFile.size;

      try{
        // Step 1: get the page count/order so we can submit a full "keep everything" plan.
        const inspectForm = new FormData();
        inspectForm.append('files', currentFile);
        inspectForm.append('thumb_dpi', '36');
        const inspectRes = await apiFetch('/api/pdf/inspect', { method:'POST', body: inspectForm });
        if(!inspectRes.ok){
          const err = await inspectRes.json().catch(()=>({detail:'Could not read this PDF.'}));
          throw new Error(err.detail || 'Could not read this PDF.');
        }
        const inspectData = await inspectRes.json();
        const plan = inspectData.sources[0].pages.map(p=> ({ source_index: 0, page_index: p.page_index, rotate: 0 }));

        setStatus('Compressing ' + plan.length + ' page' + (plan.length===1?'':'s') + '…');
        const form = new FormData();
        form.append('files', currentFile);
        form.append('plan', JSON.stringify(plan));
        form.append('compress', modeSelect.value);
        form.append('raster_dpi', dpiSelect.value);
        form.append('raster_quality', qualitySelect.value);
        form.append('output_filename', 'compressed.pdf');

        const res = await apiFetch('/api/pdf/build', { method:'POST', body: form });
        if(!res.ok){
          throw new Error(await readError(res, 'Compression failed.'));
        }
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        linkCpdf.href = url;
        const pct = originalSize > 0 ? Math.round((1 - blob.size/originalSize) * 100) : 0;
        meta.textContent = bytesToSize(originalSize) + ' → ' + bytesToSize(blob.size);
        sizeBadge.textContent = pct > 0 ? ('−' + pct + '% smaller') : (pct < 0 ? ('+' + (-pct) + '% larger — try Optimize instead') : 'same size');
        resultsWrap.style.display = 'block';
        setStatus('Done.', 'ok');
      }catch(err){
        setStatus(err.message || 'Something went wrong.', 'error');
      }finally{
        scan.classList.remove('active');
        btn.disabled = false;
      }
    });
  })();

  // ---- Image compress ----
  (function(){
    const drop = document.getElementById('drop-cimg');
    const fileInput = document.getElementById('file-cimg');
    const primary = document.getElementById('drop-cimg-primary');
    const qualitySelect = document.getElementById('cimg-quality');
    const maxdimSelect = document.getElementById('cimg-maxdim');
    const formatSelect = document.getElementById('cimg-format');
    const btn = document.getElementById('btn-cimg');
    const status = document.getElementById('status-cimg');
    const scan = document.getElementById('scan-compress');
    const resultsWrap = document.getElementById('results-cimg');
    const meta = document.getElementById('meta-cimg');
    const grid = document.getElementById('grid-cimg');
    const btnZip = document.getElementById('btn-download-zip-cimg');

    let staged = [];
    let zipBase64 = null;
    let zipFilename = 'compressed-images.zip';

    const setStatus = (msg, kind)=> showStatus(status, msg, kind);

    function addFiles(fileList){
      const arr = Array.from(fileList).filter(f=>f.type.startsWith('image/'));
      if(arr.length === 0){ setStatus('Those don\'t look like images.', 'error'); return; }
      staged = staged.concat(arr);
      primary.textContent = staged.length + ' image' + (staged.length===1?'':'s') + ' selected';
      btn.disabled = false;
      setStatus('');
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
      setStatus('Compressing ' + staged.length + ' image' + (staged.length===1?'':'s') + '…');
      resultsWrap.style.display = 'none';

      const form = new FormData();
      staged.forEach(f=> form.append('files', f));
      form.append('quality', qualitySelect.value);
      form.append('max_dimension', maxdimSelect.value);
      form.append('output_format', formatSelect.value);

      try{
        const res = await apiFetch('/api/image/compress', { method:'POST', body: form });
        if(!res.ok){
          throw new Error(await readError(res, 'Compression failed.'));
        }
        const data = await res.json();
        zipBase64 = data.zip_base64;
        zipFilename = data.zip_filename;

        grid.innerHTML = '';
        let totalOrig = 0, totalNew = 0;
        data.results.forEach(r=>{
          totalOrig += r.original_bytes;
          totalNew += r.compressed_bytes;
          const pct = r.original_bytes > 0 ? Math.round((1 - r.compressed_bytes/r.original_bytes)*100) : 0;
          const card = document.createElement('div');
          card.className = 'print-card';
          card.innerHTML = `
            <div class="sprocket-strip"><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span></div>
            <img src="${r.data_url}" alt="${r.filename}" loading="lazy" />
            <div class="print-caption">
              <span class="fname">${r.filename}</span>
              <div class="meta">
                <span>${bytesToSize(r.original_bytes)} → ${bytesToSize(r.compressed_bytes)} (${pct>0?'−'+pct+'%':pct+'%'})</span>
                <a href="${r.data_url}" download="${r.filename}">↓</a>
              </div>
            </div>
          `;
          grid.appendChild(card);
        });
        const totalPct = totalOrig > 0 ? Math.round((1 - totalNew/totalOrig)*100) : 0;
        meta.textContent = data.results.length + ' image' + (data.results.length===1?'':'s') + ' · ' + bytesToSize(totalOrig) + ' → ' + bytesToSize(totalNew) + ' (−' + totalPct + '%)';
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
  })();
}
