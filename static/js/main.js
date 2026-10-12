// Entry point: wires up the shell (theme, tabs, notifications) and every tool.
import { checkHealth } from './core/api.js';
import { installGlobalErrorHandlers, notifyError } from './core/notify.js';
import { initFileShortcuts } from './core/files.js';
import { initTheme } from './core/theme.js';
import { initTabs, paintSprockets } from './core/layout.js';

import { initPdfToImages } from './tools/pdf-to-images.js';
import { initImagesToPdf } from './tools/images-to-pdf.js';
import { initCombine } from './tools/combine.js';
import { initEdit } from './tools/edit.js';
import { initRemovePages } from './tools/remove-pages.js';
import { initCompress } from './tools/compress.js';
import { initStamp } from './tools/stamp.js';
import { initRemoveWatermark } from './tools/remove-watermark.js';
import { initCrop } from './tools/crop.js';
import { initRemoveBg } from './tools/remove-bg.js';

installGlobalErrorHandlers();
initTheme();
paintSprockets();
initTabs();
initFileShortcuts();

const tools = {
  'PDF → Images': initPdfToImages,
  'Images → PDF': initImagesToPdf,
  'Combine PDF': initCombine,
  'Edit PDF': initEdit,
  'Remove Pages': initRemovePages,
  'Compress': initCompress,
  'Stamp': initStamp,
  'Remove Watermark': initRemoveWatermark,
  'Crop / Resize': initCrop,
  'Remove BG': initRemoveBg,
};
// One broken tool shouldn't take the others down with it.
for(const [name, init] of Object.entries(tools)){
  try{
    init();
  }catch(err){
    console.error(err);
    notifyError('The ' + name + ' tool failed to start: ' + err.message);
  }
}

// Only speak up when the server can't be reached.
checkHealth().then(ok=>{
  if(!ok) notifyError('The server is not responding, so the tools won\'t work right now. Please try again in a moment.', { title: 'Server unavailable' });
});
