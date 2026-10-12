// Saving files the API returns.

export function downloadBlob(blob, filename){
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(()=> URL.revokeObjectURL(url), 1000);
}

export function downloadBase64(base64, filename, mime){
  const bytes = Uint8Array.from(atob(base64), c=> c.charCodeAt(0));
  downloadBlob(new Blob([bytes], { type: mime }), filename);
}
