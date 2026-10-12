// Light / dark theme toggle. The button shows the mode it switches TO.

const MOON_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>';
const SUN_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
const STORAGE_KEY = 'theme-mode';

export function initTheme(){
  const html = document.documentElement;
  const toggle = document.getElementById('theme-toggle');
  const icon = document.getElementById('theme-icon');
  const label = document.getElementById('theme-label');

  function setTheme(mode){
    const light = mode === 'light';
    html.classList.toggle('light-mode', light);
    icon.innerHTML = light ? MOON_ICON : SUN_ICON;
    label.textContent = light ? 'Dark mode' : 'Light mode';
    toggle.setAttribute('aria-label', light ? 'Switch to dark mode' : 'Switch to light mode');
    try{ localStorage.setItem(STORAGE_KEY, mode); }catch(_){}
  }

  let saved = null;
  try{ saved = localStorage.getItem(STORAGE_KEY); }catch(_){}
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  setTheme(saved || (prefersDark ? 'dark' : 'light'));

  toggle.addEventListener('click', ()=>{
    setTheme(html.classList.contains('light-mode') ? 'dark' : 'light');
  });
}
