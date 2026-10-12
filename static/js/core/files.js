// Paste (Ctrl/⌘+V) and drop-anywhere for every tool.
//
// Files are handed to the open tool's own file <input>, exactly as if the
// user had picked them, so each tool needs no extra code. When a tool has
// several drop zones (e.g. PDF / Image modes), the one whose `accept` matches
// is used; `data-mode-button="<id>"` on a drop zone names the mode button to
// click first so its section is shown.

import { notify, notifyError } from './notify.js';

const IS_MAC = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);

function accepts(input, file){
  const rules = (input.accept || '').split(',').map(r=> r.trim().toLowerCase()).filter(Boolean);
  if(!rules.length) return true;
  const name = (file.name || '').toLowerCase();
  const type = (file.type || '').toLowerCase();
  return rules.some(rule=>
    rule.startsWith('.') ? name.endsWith(rule)
    : rule.endsWith('/*') ? type.startsWith(rule.slice(0, -1))
    : type === rule);
}

function activePanel(){ return document.querySelector('section.panel.active'); }

function toolName(panel){
  const h = panel && panel.querySelector('.content-header h2');
  return h ? h.textContent.trim() : 'this tool';
}

function describe(input){
  const a = input.accept || '';
  if(a.includes('pdf') && a.includes('image')) return 'PDFs or images';
  if(a.includes('pdf')) return 'PDFs';
  if(a.includes('image')) return 'images (PNG, JPG, WEBP)';
  return 'these files';
}

/** Hands files to the open tool. Returns how many were accepted. */
export function deliverFiles(fileList, { source = 'drop' } = {}){
  const files = [...fileList];
  const panel = activePanel();
  if(!panel || !files.length) return 0;
  const zones = [...panel.querySelectorAll('.dropzone')].filter(z=> z.querySelector('input[type=file]'));
  if(!zones.length){ notifyError(toolName(panel) + ' doesn\'t take files.'); return 0; }

  // Prefer a visible zone that takes these files, then any zone that does.
  const scored = zones.map(zone=>{
    const input = zone.querySelector('input[type=file]');
    const ok = files.filter(f=> accepts(input, f));
    return { zone, input, ok, visible: zone.offsetParent !== null };
  }).filter(z=> z.ok.length);
  const pick = scored.find(z=> z.visible) || scored[0];
  if(!pick){
    const want = describe(zones[0].querySelector('input[type=file]'));
    notifyError(toolName(panel) + ' takes ' + want + ' — ' + (files.length === 1 ? 'that file isn\'t one.' : 'none of those files are.'));
    return 0;
  }

  if(!pick.visible && pick.zone.dataset.modeButton){
    const btn = document.getElementById(pick.zone.dataset.modeButton);
    if(btn) btn.click();
  }
  const chosen = pick.input.multiple ? pick.ok : pick.ok.slice(0, 1);
  const dt = new DataTransfer();
  chosen.forEach(f=> dt.items.add(f));
  pick.input.files = dt.files;
  pick.input.dispatchEvent(new Event('change', { bubbles: true }));

  const skipped = files.length - chosen.length;
  if(source === 'paste'){
    notify('Pasted ' + chosen.length + ' file' + (chosen.length === 1 ? '' : 's') + ' into ' + toolName(panel) + '.' +
      (skipped ? ' ' + skipped + ' skipped.' : ''), 'info', { title: 'Pasted' });
  }else if(skipped){
    notify(skipped + ' file' + (skipped === 1 ? ' was' : 's were') + ' skipped — ' + toolName(panel) + ' takes ' + describe(pick.input) + (pick.input.multiple ? '.' : ', one at a time.'), 'info');
  }
  return chosen.length;
}

/** Clipboard items -> Files. Screenshots arrive without a name, so give them one. */
function clipboardFiles(data){
  const out = [];
  for(const item of data.items || []){
    if(item.kind !== 'file') continue;
    const f = item.getAsFile();
    if(!f) continue;
    if(!f.name || f.name === 'image.png'){
      const ext = (f.type.split('/')[1] || 'png').replace('jpeg', 'jpg');
      const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
      out.push(new File([f], 'pasted-' + stamp + '.' + ext, { type: f.type }));
    }else{
      out.push(f);
    }
  }
  return out;
}

function addPasteHints(){
  const keys = IS_MAC ? '<kbd>⌘</kbd><kbd>V</kbd>' : '<kbd>Ctrl</kbd><kbd>V</kbd>';
  document.querySelectorAll('.dropzone').forEach(zone=>{
    if(zone.querySelector('.paste-hint')) return;
    const hint = document.createElement('div');
    hint.className = 'paste-hint';
    hint.innerHTML = 'or paste with ' + keys;
    const secondary = zone.querySelector('.secondary');
    (secondary || zone).insertAdjacentElement(secondary ? 'afterend' : 'beforeend', hint);
  });
}

function initDropOverlay(){
  const overlay = document.createElement('div');
  overlay.className = 'drop-overlay';
  overlay.innerHTML = '<div class="drop-overlay-card"><div class="drop-overlay-title">Drop to add</div><div class="drop-overlay-sub"></div></div>';
  document.body.appendChild(overlay);
  const sub = overlay.querySelector('.drop-overlay-sub');
  let depth = 0;

  const hasFiles = e=> e.dataTransfer && [...e.dataTransfer.types].includes('Files');
  const hide = ()=>{
    depth = 0;
    overlay.classList.remove('show');
    document.querySelectorAll('.dropzone.drag').forEach(z=> z.classList.remove('drag'));
  };

  window.addEventListener('dragenter', e=>{
    if(!hasFiles(e)) return;
    depth++;
    sub.textContent = 'into ' + toolName(activePanel());
    overlay.classList.add('show');
  });
  window.addEventListener('dragleave', e=>{
    if(!hasFiles(e)) return;
    if(--depth <= 0) hide();
  });
  window.addEventListener('dragover', e=>{
    if(!hasFiles(e)) return;
    e.preventDefault();   // allows dropping; without it the browser opens the file
    e.dataTransfer.dropEffect = 'copy';
  });
  window.addEventListener('drop', e=>{
    if(!hasFiles(e)) return;
    e.preventDefault();
    e.stopPropagation();
    hide();
    deliverFiles(e.dataTransfer.files);
  }, true);  // capture: one handler for the whole page, drop zones included
}

export function initFileShortcuts(){
  addPasteHints();
  initDropOverlay();
  document.addEventListener('paste', e=>{
    const files = clipboardFiles(e.clipboardData || {});
    if(!files.length) return;   // plain text paste: leave it to the text field
    e.preventDefault();
    deliverFiles(files, { source: 'paste' });
  });
}
