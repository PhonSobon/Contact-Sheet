// Canvas editor for marking a watermark on an image: brush, box, eraser and
// colour picker. Marks are kept as a list of operations per image (so undo is
// exact) and rendered into a mask — white = remove — at up to MASK_MAX_SIDE
// pixels; the server scales the mask to the full image.

const MASK_MAX_SIDE = 2400;
const MARK_COLOR = 'rgba(255, 59, 48, 0.5)';

export class MaskEditor{
  constructor({ canvas, stage, cursor, onChange, onPick }){
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.stage = stage;
    this.cursor = cursor;
    this.onChange = onChange || (()=>{});
    this.onPick = onPick || (()=>{});
    this.tool = 'brush';
    this.screenSize = 28;     // brush diameter in screen pixels
    this.item = null;         // { img, ops, w, h }
    this.mask = document.createElement('canvas');
    this.tint = document.createElement('canvas');
    this.sample = document.createElement('canvas');
    this.active = null;       // op being drawn
    this._bindPointer();
  }

  /** item: { img: HTMLImageElement (loaded), ops: [] } — ops are kept on the item. */
  load(item){
    const { naturalWidth: nw, naturalHeight: nh } = item.img;
    const scale = Math.min(1, MASK_MAX_SIDE / Math.max(nw, nh));
    item.w = Math.max(1, Math.round(nw * scale));
    item.h = Math.max(1, Math.round(nh * scale));
    this.item = item;
    for(const c of [this.canvas, this.mask, this.tint, this.sample]){ c.width = item.w; c.height = item.h; }
    const s = this.sample.getContext('2d', { willReadFrequently: true });
    s.drawImage(item.img, 0, 0, item.w, item.h);
    this._renderMask();
    this.draw();
  }

  setTool(tool){
    this.tool = tool;
    this.stage.dataset.tool = tool;
    this._updateCursorSize();
  }

  setSize(px){ this.screenSize = px; this._updateCursorSize(); }

  hasMarks(item = this.item){ return !!(item && item.ops.length); }

  undo(){
    if(!this.hasMarks()) return;
    this.item.ops.pop();
    this._renderMask(); this.draw(); this.onChange();
  }

  clear(){
    if(!this.hasMarks()) return;
    this.item.ops.length = 0;
    this._renderMask(); this.draw(); this.onChange();
  }

  /** Renders an item's marks into a PNG mask, or null if it has none. */
  static exportMask(item){
    if(!item.ops.length || !item.w) return Promise.resolve(null);
    const c = document.createElement('canvas');
    c.width = item.w; c.height = item.h;
    const ctx = c.getContext('2d');
    ctx.fillStyle = '#000'; ctx.fillRect(0, 0, c.width, c.height);
    item.ops.forEach(op=> MaskEditor._paint(ctx, op, '#fff'));
    return new Promise(resolve=> c.toBlob(resolve, 'image/png'));
  }

  // ---------------------------------------------------------------- drawing

  static _paint(ctx, op, color){
    ctx.save();
    if(op.type === 'erase'){ ctx.globalCompositeOperation = 'destination-out'; color = '#000'; }
    ctx.fillStyle = ctx.strokeStyle = color;
    if(op.type === 'box'){
      const x = Math.min(op.x0, op.x1), y = Math.min(op.y0, op.y1);
      ctx.fillRect(x, y, Math.abs(op.x1 - op.x0), Math.abs(op.y1 - op.y0));
    }else{
      ctx.lineWidth = op.size; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
      const pts = op.pts;
      if(pts.length === 1){
        ctx.beginPath(); ctx.arc(pts[0][0], pts[0][1], op.size / 2, 0, Math.PI * 2); ctx.fill();
      }else{
        ctx.beginPath(); ctx.moveTo(pts[0][0], pts[0][1]);
        for(let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
        ctx.stroke();
      }
    }
    ctx.restore();
  }

  _renderMask(){
    const m = this.mask.getContext('2d');
    m.clearRect(0, 0, this.mask.width, this.mask.height);
    if(this.item) this.item.ops.forEach(op=> MaskEditor._paint(m, op, '#fff'));
  }

  draw(){
    if(!this.item) return;
    const { ctx, canvas } = this;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(this.item.img, 0, 0, canvas.width, canvas.height);

    // Tint the mask red and lay it over the picture.
    const t = this.tint.getContext('2d');
    t.globalCompositeOperation = 'source-over';
    t.clearRect(0, 0, canvas.width, canvas.height);
    t.drawImage(this.mask, 0, 0);
    if(this.active && this.active.type !== 'box') MaskEditor._paint(t, this.active, '#fff');
    t.globalCompositeOperation = 'source-in';
    t.fillStyle = MARK_COLOR;
    t.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(this.tint, 0, 0);

    if(this.active && this.active.type === 'box'){
      const a = this.active;
      ctx.save();
      ctx.fillStyle = MARK_COLOR;
      ctx.fillRect(Math.min(a.x0, a.x1), Math.min(a.y0, a.y1), Math.abs(a.x1 - a.x0), Math.abs(a.y1 - a.y0));
      ctx.setLineDash([6, 4]); ctx.lineWidth = Math.max(1, canvas.width / 600); ctx.strokeStyle = '#fff';
      ctx.strokeRect(Math.min(a.x0, a.x1), Math.min(a.y0, a.y1), Math.abs(a.x1 - a.x0), Math.abs(a.y1 - a.y0));
      ctx.restore();
    }
  }

  // ---------------------------------------------------------------- input

  _toImage(e){
    const r = this.canvas.getBoundingClientRect();
    return [
      Math.max(0, Math.min(this.canvas.width, (e.clientX - r.left) * this.canvas.width / r.width)),
      Math.max(0, Math.min(this.canvas.height, (e.clientY - r.top) * this.canvas.height / r.height)),
    ];
  }

  _imageScale(){
    const r = this.canvas.getBoundingClientRect();
    return r.width ? this.canvas.width / r.width : 1;
  }

  _updateCursorSize(){
    const round = this.tool === 'brush' || this.tool === 'erase';
    this.cursor.style.width = this.cursor.style.height = this.screenSize + 'px';
    this.cursor.style.display = round && this._hover ? 'block' : 'none';
  }

  _moveCursor(e){
    const s = this.stage.getBoundingClientRect();
    this.cursor.style.left = (e.clientX - s.left) + 'px';
    this.cursor.style.top = (e.clientY - s.top) + 'px';
  }

  _bindPointer(){
    const c = this.canvas;
    c.addEventListener('pointerenter', e=>{ this._hover = true; this._updateCursorSize(); this._moveCursor(e); });
    c.addEventListener('pointerleave', ()=>{ this._hover = false; this._updateCursorSize(); });

    c.addEventListener('pointerdown', e=>{
      if(!this.item || e.button !== 0) return;
      e.preventDefault();
      const [x, y] = this._toImage(e);
      if(this.tool === 'pick'){
        const [r, g, b] = this.sample.getContext('2d', { willReadFrequently: true }).getImageData(Math.floor(Math.min(x, c.width - 1)), Math.floor(Math.min(y, c.height - 1)), 1, 1).data;
        this.onPick('#' + [r, g, b].map(v=> v.toString(16).padStart(2, '0')).join(''));
        return;
      }
      try{ c.setPointerCapture(e.pointerId); }catch(_){}  // keeps strokes going past the edge
      this.active = this.tool === 'box'
        ? { type: 'box', x0: x, y0: y, x1: x, y1: y }
        : { type: this.tool, size: this.screenSize * this._imageScale(), pts: [[x, y]] };
      this.draw();
    });

    c.addEventListener('pointermove', e=>{
      this._moveCursor(e);
      if(!this.active) return;
      const [x, y] = this._toImage(e);
      if(this.active.type === 'box'){ this.active.x1 = x; this.active.y1 = y; }
      else this.active.pts.push([x, y]);
      this.draw();
    });

    const finish = ()=>{
      if(!this.active) return;
      const op = this.active;
      this.active = null;
      const tiny = op.type === 'box' && (Math.abs(op.x1 - op.x0) < 3 || Math.abs(op.y1 - op.y0) < 3);
      if(!tiny){
        this.item.ops.push(op);
        MaskEditor._paint(this.mask.getContext('2d'), op, '#fff');
        this.onChange();
      }
      this.draw();
    };
    c.addEventListener('pointerup', finish);
    c.addEventListener('pointercancel', finish);
  }
}
