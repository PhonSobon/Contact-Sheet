// Sidebar tab switching and the decorative sprocket strips.

/** Each `#tab-<key>` button shows `#panel-<key>`. The open tab is kept in the URL hash. */
export function initTabs(){
  const buttons = [...document.querySelectorAll('.sidebar-nav [role="tab"]')];
  const keyOf = btn => btn.id.replace(/^tab-/, '');

  function activate(key){
    buttons.forEach(btn=>{
      const on = keyOf(btn) === key;
      btn.classList.toggle('active', on);
      btn.setAttribute('aria-selected', on);
      const panel = document.getElementById('panel-' + keyOf(btn));
      if(panel) panel.classList.toggle('active', on);
    });
  }

  buttons.forEach(btn=> btn.addEventListener('click', ()=>{
    activate(keyOf(btn));
    history.replaceState(null, '', '#' + keyOf(btn));
  }));

  const fromHash = location.hash.slice(1);
  if(buttons.some(b=> keyOf(b) === fromHash)) activate(fromHash);
}

export function paintSprockets(count = 14){
  document.querySelectorAll('.sprockets').forEach(el=>{
    el.innerHTML = '';
    for(let i = 0; i < count; i++) el.appendChild(document.createElement('span'));
  });
}
