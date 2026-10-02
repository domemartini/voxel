import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { TransformControls } from "three/addons/controls/TransformControls.js";
import { toCreasedNormals } from "three/addons/utils/BufferGeometryUtils.js";

// messages that never freeze the page (a blocking alert() stops the heartbeat and the server would think the window closed)
(function () {
  const box = document.createElement("div");
  box.style.cssText = "position:fixed;left:50%;top:18px;transform:translateX(-50%);z-index:99;display:flex;flex-direction:column;gap:8px;max-width:560px;width:calc(100% - 40px);pointer-events:none";
  document.addEventListener("DOMContentLoaded", () => document.body.appendChild(box)); if (document.body) document.body.appendChild(box);
  window.alert = (msg) => {
    const d = document.createElement("div"); const err = /erro|falhou|não deu/i.test(msg);
    d.style.cssText = `pointer-events:auto;background:${err ? "#3b1d22" : "#1f2638"};border:1px solid ${err ? "#f87171" : "#4b5b82"};color:#eceef2;padding:12px 38px 12px 14px;border-radius:12px;box-shadow:0 10px 30px rgba(0,0,0,.45);font:13px system-ui;position:relative;white-space:pre-wrap`;
    d.textContent = (err ? "Atenção: " : "") + msg;
    const x = document.createElement("button"); x.textContent = "✕"; x.style.cssText = "position:absolute;right:8px;top:8px;background:none;border:none;color:#aaa;cursor:pointer;font-size:14px"; x.onclick = () => d.remove(); d.appendChild(x);
    box.appendChild(d); setTimeout(() => d.remove(), err ? 30000 : 9000);
  };
})();
const PALETTE = ["#f2c12e", "#9ca3af", "#3b82f6", "#ef4444", "#22c55e", "#a855f7", "#f97316", "#14b8a6", "#ec4899"];
const $ = (id) => document.getElementById(id);
const view = $("view");

// ---------- scene
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
view.appendChild(renderer.domElement);
const scene = new THREE.Scene(); scene.background = new THREE.Color(0x16181d);
const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 10000); camera.up.set(0, 0, 1);
scene.add(new THREE.HemisphereLight(0xffffff, 0x3a3f4a, 1.6));
const sun = new THREE.DirectionalLight(0xffffff, 1.8); scene.add(sun);
const controls = new OrbitControls(camera, renderer.domElement); controls.enableDamping = true;
controls.zoomToCursor = true;                                // a roda aproxima de onde o mouse está (antes ia pro meio do modelo e "travava")
const tctrl = new TransformControls(camera, renderer.domElement); tctrl.setSize(0.8);
tctrl.addEventListener("dragging-changed", (e) => { controls.enabled = !e.value; if (!e.value) saveMarks(); });
scene.add(tctrl.getHelper ? tctrl.getHelper() : tctrl);
function resize() { const w = view.clientWidth, h = view.clientHeight; renderer.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix(); }
addEventListener("resize", resize); resize();

// ---------- state
let groups = [{ name: "Boneco", color: PALETTE[0], points: [] }, { name: "Base", color: PALETTE[1], points: [] }];
const sidesSel = {};
const cutSel = {};                                  // escolha por corte: "A|B" -> auto | 0 | 1 | 2 | 3 | colar
const hiddenG = new Set();
const CK_A = new THREE.Color(0.93, 0.93, 0.95), CK_B = new THREE.Color(0.16, 0.16, 0.2), BASE_C = new THREE.Color(0.78, 0.78, 0.8);
let jointsSeen = false;                            // encaixes já visualizados (guia de etapas)
let delView = null;                               // 1 = triangle marked to be deleted ("xadrez")                       // pieces hidden from view (by group index)
let planes = []; let strokes = []; let history = []; let active = 0; let tool = "point"; let showing = "marks";
let mesh, geom, seg = null, diag = 100, markerGroup = new THREE.Group(), loopGroup = new THREE.Group();
const strokeGroup = new THREE.Group(); const seamGroup = new THREE.Group(); let seams = [];
const dotGeo = new THREE.SphereGeometry(1, 10, 8), dotMat = new THREE.MeshBasicMaterial({ color: 0xff3b3b, transparent: true, opacity: 0.85 });
scene.add(markerGroup); scene.add(loopGroup); scene.add(strokeGroup); scene.add(seamGroup);
const planeObjs = [];
const piecesGroup = new THREE.Group(); scene.add(piecesGroup); piecesGroup.visible = false;
const platesGroup = new THREE.Group(); scene.add(platesGroup); platesGroup.visible = false;
const plBase = new THREE.Group(), plPieces = new THREE.Group(); platesGroup.add(plBase, plPieces);
let layout = null, plMode = null, plSel = null, camSaved = null, plDrag = null, plSrc = null;

// every request says which project this window shows (several windows / server restarts stay safe)
const _fetch = window.fetch.bind(window);
let _downWarned = 0;
window.fetch = (u, o = {}) => {
  if (window.PID) o = { ...o, headers: { ...(o.headers || {}), "X-Project": window.PID } };
  return _fetch(u, o).then((r) => { if (r.status === 402) location.href = "/"; return r; }).catch((e) => {
    if (Date.now() - _downWarned > 20000) { _downWarned = Date.now(); alert("Não deu pra falar com o programa: ele foi fechado. Abra o atalho \"Voxel Cut\" de novo (seu trabalho fica salvo) e depois aperte F5 aqui."); }
    throw e;
  });
};
const JANELA = Math.random().toString(36).slice(2);          // esta janela: avisa que está aberta e avisa quando fecha (aí o Voxel encerra)
const pingar = () => fetch("/api/ping", { method: "POST", body: JSON.stringify({ janela: JANELA }) }).catch(() => {});
setInterval(pingar, 4000); pingar();
addEventListener("pagehide", () => navigator.sendBeacon("/api/bye", JSON.stringify({ janela: JANELA })));
// ---------- load mesh
$("busy").style.display = "block"; $("busy").textContent = "⏳ carregando modelo…";
const meshRes = await fetch("/api/mesh");
if (!meshRes.ok) { location.href = "/"; throw new Error("sem projeto"); }
const buf = await meshRes.arrayBuffer();
const [nv, nt] = new Uint32Array(buf, 0, 2);
const V = new Float32Array(buf, 8, nv * 3), T = new Uint32Array(buf, 8 + nv * 12, nt * 3);
const pos = new Float32Array(nt * 9);
for (let i = 0; i < nt * 3; i++) { const j = T[i] * 3; pos[i * 3] = V[j]; pos[i * 3 + 1] = V[j + 1]; pos[i * 3 + 2] = V[j + 2]; }
geom = new THREE.BufferGeometry();
geom.setAttribute("position", new THREE.BufferAttribute(pos, 3));
geom.setAttribute("color", new THREE.BufferAttribute(new Float32Array(nt * 9).fill(0.78), 3));
geom.computeVertexNormals(); geom.computeBoundingBox();
mesh = new THREE.Mesh(geom, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.75, metalness: 0.0, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 }));
scene.add(mesh);
const bb = geom.boundingBox, ctr = bb.getCenter(new THREE.Vector3()); diag = bb.getSize(new THREE.Vector3()).length();
controls.target.copy(ctr); camera.position.copy(ctr).add(new THREE.Vector3(diag * 1.1, -diag * 0.6, diag * 0.35));
camera.near = diag / 500; camera.far = diag * 20; camera.updateProjectionMatrix();
controls.minDistance = diag / 20000; controls.maxDistance = diag * 8;
controls.update(); controls.saveState();
// spatial grid of display triangles (for live painting)
const tc = new Float32Array(nt * 3);
for (let i = 0; i < nt; i++) for (let k = 0; k < 3; k++) tc[i * 3 + k] = (pos[i * 9 + k] + pos[i * 9 + 3 + k] + pos[i * 9 + 6 + k]) / 3;
const cell = diag * 0.01, grid = new Map(), gk = (x, y, z) => (x * 73856093) ^ (y * 19349663) ^ (z * 83492791);
for (let i = 0; i < nt; i++) {
  const k = gk(Math.floor(tc[i * 3] / cell), Math.floor(tc[i * 3 + 1] / cell), Math.floor(tc[i * 3 + 2] / cell));
  let a = grid.get(k); if (!a) grid.set(k, (a = [])); a.push(i);
}
function trisNear(p, r) {
  const out = [], n = Math.ceil(r / cell), cx = Math.floor(p.x / cell), cy = Math.floor(p.y / cell), cz = Math.floor(p.z / cell), r2 = r * r;
  for (let x = cx - n; x <= cx + n; x++) for (let y = cy - n; y <= cy + n; y++) for (let z = cz - n; z <= cz + n; z++) {
    const a = grid.get(gk(x, y, z)); if (!a) continue;
    for (const i of a) { const dx = tc[i * 3] - p.x, dy = tc[i * 3 + 1] - p.y, dz = tc[i * 3 + 2] - p.z; if (dx * dx + dy * dy + dz * dz < r2) out.push(i); }
  }
  return out;
}
const cursor = new THREE.Mesh(new THREE.RingGeometry(0.92, 1, 48), new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.85, side: THREE.DoubleSide, depthTest: false }));
cursor.renderOrder = 20; cursor.visible = false; scene.add(cursor);
function frameView() { controls.reset(); }
$("frame").onclick = frameView;

// ---------- state from server
let st = await (await fetch("/api/state")).json();
window.PID = st.project;
$("modelname").textContent = `${st.height ? Math.round(st.height) + " mm de altura · " : ""}${nt.toLocaleString("pt-BR")} triângulos na tela`;
$("projname").textContent = st.name; document.title = st.name + " · Voxel Cut";
if (st.marks) { groups = st.marks.groups; planes = st.marks.planes || []; strokes = st.marks.strokes || []; }
const sameGroups = () => st.summary && st.summary.groups.length === groups.length && st.summary.groups.every((g, i) => g.name === groups[i].name);
if (sameGroups()) { await loadSeg(); await loadSeams(); showing = "result"; } else st.summary = null;
await loadDel();
jointsSeen = !!(st.files && st.files.length);
rebuildAll();
$("busy").style.display = "none";
setTimeout(() => {                              // arquivo pintado pra AMS e nada marcado ainda: já mostra o "Separar por cor"
  showCores(); showObjetos();
  if (st.placas_src > 0 && !st.pieces && !groups.some((g) => g.points.length)) setTimeout(() => $("showPlates").click(), 300);   // arquivo com pratos: já mostra como veio
  if (((st.cores && Object.keys(st.cores).length > 1) || st.objetos > 1) && !groups.some((g) => g.points.length)) $("toolSmart").click();
}, 0);

// ---------- UI: groups
function rebuildGroups() {
  const box = $("groups"); box.innerHTML = "";
  groups.forEach((g, i) => {
    const d = document.createElement("div"); d.className = "grp" + (i === active ? " active" : ""); d.style.setProperty("--c", g.color);
    d.innerHTML = `<span class="order">${i + 1}</span><input type="color" value="${g.color}"><input type="text" value="${g.name}"><span class="n${g.points.length ? "" : " zero"}">${g.points.length ? g.points.length + (g.points.length > 1 ? " pts" : " pt") : "sem pontos"}</span>
      <button class="x eye${hiddenG.has(i) ? " off" : ""}" title="${hiddenG.has(i) ? "mostrar a peça" : "esconder a peça (só na tela)"}">${hiddenG.has(i) ? '<svg class="ic s"><use href="#i-eyeoff"/></svg>' : '<svg class="ic s"><use href="#i-eye"/></svg>'}</button><button class="x" title="subir na lista"><svg class="ic s"><use href="#i-up"/></svg></button><button class="x" title="remover"><svg class="ic s"><use href="#i-x"/></svg></button>`;
    const [col, name] = d.querySelectorAll("input"); const [eye, up, del] = d.querySelectorAll("button");
    eye.onclick = (ev) => {
      ev.stopPropagation();
      if (hiddenG.has(i)) hiddenG.delete(i); else {
        if (hiddenG.size >= groups.length - 1) { alert("Deixe pelo menos uma peça visível."); return; }
        hiddenG.add(i);
        if (!seg) alert("Dica: esconder funciona depois de Separar peças (é pelo resultado que o programa sabe o que é cada peça).");
      }
      rebuildGroups(); rebuildMarkers(); paint();
    };
    d.addEventListener("pointerdown", (e) => {
      if (e.target.tagName === "BUTTON" || active === i) return;
      active = i; document.querySelectorAll(".grp").forEach((el, j) => el.classList.toggle("active", j === i)); hint();
    });
    col.oninput = () => { g.color = col.value; d.style.setProperty("--c", g.color); rebuildMarkers(); paint(); saveMarks(); };
    name.onchange = () => {
      let n = name.value.trim() || `Peça ${i + 1}`;
      if (groups.some((o, j) => j !== i && o.name.toLowerCase() === n.toLowerCase())) { alert(`Já existe uma peça chamada "${n}". Use outro nome.`); name.value = g.name; return; }
      g.name = n; saveMarks(); updateSteps();
    };
    up.onclick = () => { if (i > 0) { hiddenG.clear(); [groups[i - 1], groups[i]] = [groups[i], groups[i - 1]]; active = i - 1; seg = null; showing = "marks"; st.summary = null; rebuildAll(); saveMarks(); } };
    del.onclick = () => { if (groups.length > 2 && confirm(`Remover "${g.name}"?`)) { hiddenG.clear(); groups.splice(i, 1); active = 0; seg = null; showing = "marks"; st.summary = null; rebuildAll(); saveMarks(); } };
    box.appendChild(d);
  });
}
function uniqueName() { let i = groups.length; while (groups.some((g) => g.name.toLowerCase() === `peça ${i}`)) i++; return `Peça ${i}`; }
$("addGroup").onclick = () => { seg = null; showing = "marks"; st.summary = null; groups.splice(groups.length - 1, 0, { name: uniqueName(), color: PALETTE[(groups.length + 1) % PALETTE.length], points: [] }); active = groups.length - 2; rebuildAll(); saveMarks(); };
$("undo").onclick = () => { undo(); };
function undo() {
  const h = history.pop() || { t: "srv", vazio: true };   // lista vazia (ex.: reabriu o projeto): tenta o que o programa guardou
  if (h.t === "srv") {                                // corte reto, esponja, separar, separar por cor...: volta o passo guardado no programa
    fetch("/api/desfazer", { method: "POST", body: "{}" }).then((r) => { if (r.ok) poll("desfazer"); else { if (!h.vazio) history.push(h); alert("O programa está ocupado, espere terminar."); } });
    return;
  }
  if (h.t === "pt") groups[h.g].points.pop();
  else if (h.t === "gp") groups[h.g].points.splice(-h.n, h.n);
  else if (h.t === "st") strokes.pop();
  else if (h.t === "mv") { const p = groups[h.to].points.pop(); groups[h.from].points.splice(h.i, 0, p); }
  else if (h.t === "del") groups[h.g].points.splice(h.i, 0, h.p);
  else if (h.t === "dl") { fetch("/api/del_undo", { method: "POST", body: "{}" }).then(async () => { const s2 = await (await fetch("/api/state")).json(); st.deleted = s2.deleted; await loadDel(); paint(); updateSteps(); }); return; }
  else if (h.t === "mp") { fetch("/api/paint_undo", { method: "POST", body: "{}" }).then(async () => { await loadSeg(); paint(); }); return; }
  rebuildAll(); saveMarks();
}
$("clearG").onclick = () => { groups[active].points = []; rebuildAll(); saveMarks(); };

// ---------- markers
function seedR() { return diag * 0.008 * +$("brush").value; }
$("brush").oninput = () => rebuildMarkers();
function rebuildMarkers() {
  markerGroup.clear();
  const r = seedR() * 0.6;
  groups.forEach((g, gi) => hiddenG.has(gi) ? null : g.points.forEach((p) => {
    const m = new THREE.Mesh(new THREE.SphereGeometry(r, 16, 12), new THREE.MeshBasicMaterial({ color: g.color, depthTest: false }));
    m.renderOrder = 10; m.position.set(...p); markerGroup.add(m);
    const ring = new THREE.Mesh(new THREE.SphereGeometry(r * 1.5, 16, 12), new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.45, depthTest: false }));
    ring.renderOrder = 9; ring.position.set(...p); markerGroup.add(ring);
  }));
}
function addMarker(p, color) {
  const r = seedR() * 0.6;
  const m = new THREE.Mesh(new THREE.SphereGeometry(r, 12, 8), new THREE.MeshBasicMaterial({ color, depthTest: false }));
  m.renderOrder = 10; m.position.copy(p); markerGroup.add(m);
}
function addStrokeDot(p, r, color) { const m = new THREE.Mesh(dotGeo, color ? new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.6 }) : dotMat); m.scale.setScalar(r * 0.55); m.position.copy(p); strokeGroup.add(m); }
function rebuildStrokes() {
  strokeGroup.clear();
  strokes.forEach((s) => s.points.forEach((q) => addStrokeDot(new THREE.Vector3(...q), s.radius)));
  const n = strokes.length;
  $("strokes").innerHTML = n ? `${n} traço(s) de corte <button class="x" id="clearStrokes">apagar todos</button>` : "";
  if (n) $("clearStrokes").onclick = () => { strokes = []; history = history.filter((h) => h.t !== "st"); rebuildAll(); saveMarks(); };
}
// ---------- planes
function rebuildPlanes() {
  tctrl.detach(); planeObjs.forEach((o) => scene.remove(o)); planeObjs.length = 0;
  const box = $("planes"); box.innerHTML = planes.length ? "" : `<div class="small" style="margin-top:6px">Sem planos. Com a ferramenta de plano, clique no modelo onde quer um corte reto.</div>`;
  planes.forEach((pl, i) => {
    const o = new THREE.Mesh(new THREE.CircleGeometry(1, 64), new THREE.MeshBasicMaterial({ color: 0x4f8cff, transparent: true, opacity: 0.35, side: THREE.DoubleSide, depthWrite: false }));
    const edge = new THREE.LineLoop(new THREE.EdgesGeometry(new THREE.CircleGeometry(1, 64)), new THREE.LineBasicMaterial({ color: 0x9cc1ff }));
    o.add(edge); o.position.set(...pl.point); o.scale.setScalar(pl.radius);
    o.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), new THREE.Vector3(...pl.normal).normalize());
    o.userData.idx = i; scene.add(o); planeObjs.push(o);
    const d = document.createElement("div"); d.className = "pl";
    d.innerHTML = `<button class="x">editar</button> raio <input type="range" min="${(diag * 0.01).toFixed(1)}" max="${(diag * 0.4).toFixed(1)}" step="0.5" value="${pl.radius}"> <button class="x">✕</button>`;
    const [ed, del] = d.querySelectorAll("button"); const rg = d.querySelector("input");
    ed.onclick = () => { tctrl.attach(o); tctrl.setMode("translate"); hint("plane"); };
    rg.oninput = () => { pl.radius = +rg.value; o.scale.setScalar(pl.radius); };
    rg.onchange = saveMarks;
    del.onclick = () => { planes.splice(i, 1); rebuildPlanes(); saveMarks(); };
    box.appendChild(d);
  });
}
tctrl.addEventListener("objectChange", () => {
  const o = tctrl.object; if (!o) return; const pl = planes[o.userData.idx];
  pl.point = o.position.toArray(); pl.normal = new THREE.Vector3(0, 0, 1).applyQuaternion(o.quaternion).toArray();
});
addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT") return;
  if (e.key === "[" || e.key === "]") { const b = $("brushW"); b.value = Math.min(+b.max, Math.max(+b.min, +b.value * (e.key === "]" ? 1.2 : 1 / 1.2))); $("brushW2").value = b.value; cursor.scale.setScalar(curR()); return; }
  const tk = { 1: "toolPoint", 2: "toolPaint", 3: "toolCut", 4: "toolPlane", 5: "toolManual", 6: "toolSponge", 7: "toolDel" }[e.key];
  if (tk && !e.ctrlKey && !e.altKey) { $(tk).click(); return; }
  if (e.key === "r" || e.key === "R") tctrl.setMode("rotate");
  if (e.key === "t" || e.key === "T") tctrl.setMode("translate");
  if (e.key === "Escape") { tctrl.detach(); hint(); }
  if ((e.key === "Delete" || e.key === "Backspace") && tctrl.object) { planes.splice(tctrl.object.userData.idx, 1); rebuildPlanes(); saveMarks(); }
  if ((e.ctrlKey || e.metaKey) && e.key === "z") undo();
});

// ---------- tools
function setTool(t) {
  tool = t; tctrl.detach();
  for (const [id, k] of [["toolPoint", "point"], ["toolPaint", "paint"], ["toolCut", "cut"], ["toolPlane", "plane"], ["toolSponge", "sponge"], ["toolManual", "manual"], ["toolDel", "del"]]) $(id).classList.toggle("on", t === k);
  const brush = t === "paint" || t === "cut" || t === "sponge" || t === "manual" || t === "del"; cursor.visible = false;
  controls.mouseButtons = brush ? { LEFT: null, MIDDLE: THREE.MOUSE.PAN, RIGHT: THREE.MOUSE.ROTATE } : { LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.PAN };
  document.querySelectorAll("[data-tools]").forEach((el) => { el.hidden = !el.dataset.tools.split(" ").includes(t); });
  document.querySelectorAll(".vtool").forEach((b) => b.classList.toggle("on", b.dataset.t === t));
  const o2 = $("opts2"); o2.hidden = [...o2.children].every((c) => c.hidden);
  showPop(t); hint();
}
$("brushW").oninput = () => { $("brushW2").value = $("brushW").value; };
$("brushW2").oninput = () => { $("brushW").value = $("brushW2").value; };
function updateSteps() {
  const last = groups[groups.length - 1]; $("anchorName").innerHTML = `<span style="color:${last.color}">■</span> ${last.name}`;
  $("delInfo").textContent = st.deleted ? `${st.deleted.toLocaleString("pt-BR")} triângulos no xadrez` : "";
  $("paintedInfo").textContent = st.painted ? `${st.painted.toLocaleString("pt-BR")} triângulos pintados à mão` : "";
  $("step1").classList.toggle("done", groups.slice(0, -1).every((g) => g.points.length) || !!seg);
  $("step2").classList.toggle("done", !!st.summary);
  $("step3").classList.toggle("done", !!st.summary);
  $("step5").classList.toggle("done", !!(st.files && st.files.length));
  updateFlow();
}
$("toolPoint").onclick = () => setTool("point"); $("toolPlane").onclick = () => setTool("plane");
$("toolPaint").onclick = () => setTool("paint"); $("toolCut").onclick = () => setTool("cut");
$("toolSponge").onclick = () => { if (!seg) { alert("Primeiro separe as peças; a esponja alisa as costuras do resultado."); return; } setTool("sponge"); if (showing !== "result") { showing = "result"; paint(); } };
$("toolManual").onclick = () => {
  fetch("/api/marks", { method: "POST", body: JSON.stringify({ groups, planes, strokes }) });
  if (!seg) { seg = new Uint8Array(nt).fill(groups.length - 1); }
  showing = "result"; setTool("manual"); paint();
};
$("toolDel").onclick = () => setTool("del");
$("delWhole").onchange = () => hint();
$("delAuto").onclick = async () => {
  const r = await delOp({ auto: true, frac: 0.03 });
  alert(r.changed ? `Marquei ${r.changed.toLocaleString("pt-BR")} triângulos de pedaços soltos pequenos (xadrez). Confira e desmarque com Shift + pincel se algum for importante.` : "Não achei pedaços soltos pequenos nesse modelo.");
  setTool("del");
};
$("delClear").onclick = async () => {
  if (!confirm("Desmarcar tudo o que está no xadrez?")) return;
  await fetch("/api/del_clear", { method: "POST", body: "{}" }); history.push({ t: "dl" }); st.deleted = 0; await loadDel(); paint(); updateSteps();
};
$("brushW3").oninput = () => { $("brushW").value = $("brushW2").value = $("brushW3").value; };
$("paintClear").onclick = async () => {
  if (!confirm("Apagar a trava da pintura à mão? (as cores continuam até você clicar em Separar de novo)")) return;
  await fetch("/api/paint_clear", { method: "POST", body: "{}" }); st.painted = 0; updateSteps();
};
$("spongeStr").oninput = () => { $("spongeVal").textContent = $("spongeStr").value; };
function brushR() { return diag * 0.006 * +$("brushW").value; }
function curR() { return tool === "sponge" ? Math.max(brushR() * 2, +$("spongeStr").value * 2) : tool === "paint" ? seedR() : brushR(); }
function hint(mode) {
  const h = $("hint");
  if (tool === "nav" && mode !== "plane") { h.innerHTML = `<b>Navegar</b>: arraste para girar · botão direito move · roda = zoom · escolha uma ferramenta para voltar a trabalhar (ou solte o <kbd>Espaço</kbd>)`; return; }
  if (mode === "plane") h.innerHTML = `Plano selecionado: arraste as setas para mover · <kbd>R</kbd> girar · <kbd>T</kbd> mover · <kbd>Del</kbd> apagar · <kbd>Esc</kbd> soltar`;
  else if (tool === "plane") h.innerHTML = `Clique no modelo para criar um plano de corte ali (ele já nasce virado para a câmera). Depois ajuste com as setas e o raio.`;
  else if (tool === "manual") h.innerHTML = `<b style="color:${groups[active].color}">Pintando ${groups[active].name}</b>: pinte os triângulos direto · <kbd>[</kbd> <kbd>]</kbd> tamanho do pincel · troque a peça na lista para pintar outra · botão direito gira`;
  else if (tool === "del") h.innerHTML = `<b>Apagar</b>: pinte o que deve sumir (fica em xadrez) · <kbd>Shift</kbd>+pintar desmarca · ${$("delWhole").checked ? "clique num pedaço solto para marcar ele inteiro" : "ligue \"Pedaço inteiro\" para marcar um pedaço solto num clique"} · botão direito ou <kbd>Espaço</kbd> gira`;
  else if (tool === "sponge") h.innerHTML = `<b>Esponja</b>: passe sobre a costura (linha branca) para alisar o corte ali · força ${$("spongeStr").value} mm · botão direito gira`;
  else if (tool === "cut") h.innerHTML = `<b style="color:#ff6b6b">Pincel de corte</b>: pinte com o botão esquerdo a linha por onde quer cortar (ex.: em volta do ombro) · <kbd>Shift</kbd>+pintar apaga · botão direito gira · roda = zoom`;
  else if (tool === "paint") h.innerHTML = `<b style="color:${groups[active].color}">Pincel de ${groups[active].name}</b>: pinte a área que pertence a essa peça · botão direito gira · roda = zoom`;
  else h.innerHTML = `Clique para marcar <b style="color:${groups[active].color}">${groups[active].name}</b> · clique numa bolinha para passar ela para outra peça · <kbd>Shift</kbd>+clique apaga o ponto mais perto · arraste para girar, botão direito para mover, roda para zoom.`;
}

// ---------- picking
const ray = new THREE.Raycaster(); let down = null; let painting = null;
// raio x malha rápido: triângulos vizinhos em caixas de 128 (ordem de Morton). O raycast do three.js testa os 300 mil um por um
// (12 ms no PC, 40 ms+ em notebook) e rodava várias vezes por movimento do mouse na pincelada.
const PK = (() => {
  const CH = 128, n = nt, lo = [1e30, 1e30, 1e30], hi = [-1e30, -1e30, -1e30];
  for (let i = 0; i < n; i++) for (let k = 0; k < 3; k++) { const v = tc[i * 3 + k]; if (v < lo[k]) lo[k] = v; if (v > hi[k]) hi[k] = v; }
  const sp = (x) => { x &= 0x3ff; x = (x | (x << 16)) & 0x30000ff; x = (x | (x << 8)) & 0x300f00f; x = (x | (x << 4)) & 0x30c30c3; return (x | (x << 2)) & 0x9249249; };
  const key = new Uint32Array(n), ord = new Uint32Array(n);
  const q = (v, k) => Math.min(1023, Math.floor(((v - lo[k]) / ((hi[k] - lo[k]) || 1)) * 1024));
  for (let i = 0; i < n; i++) { key[i] = sp(q(tc[i * 3], 0)) | (sp(q(tc[i * 3 + 1], 1)) << 1) | (sp(q(tc[i * 3 + 2], 2)) << 2); ord[i] = i; }
  ord.sort((a, b) => key[a] - key[b]);
  const nc = Math.ceil(n / CH), box = new Float32Array(nc * 6);
  for (let c = 0; c < nc; c++) {
    let b = [1e30, 1e30, 1e30, -1e30, -1e30, -1e30];
    for (let j = c * CH; j < Math.min(n, (c + 1) * CH); j++) { const t = ord[j] * 9; for (let v = 0; v < 3; v++) for (let k = 0; k < 3; k++) { const x = pos[t + v * 3 + k]; if (x < b[k]) b[k] = x; if (x > b[k + 3]) b[k + 3] = x; } }
    box.set(b, c * 6);
  }
  const hits = [];
  function intersect(o, d) {
    hits.length = 0; const ix = 1 / d.x, iy = 1 / d.y, iz = 1 / d.z;
    for (let c = 0; c < nc; c++) {
      const b = c * 6; let t1 = (box[b] - o.x) * ix, t2 = (box[b + 3] - o.x) * ix, tmin = Math.min(t1, t2), tmax = Math.max(t1, t2);
      t1 = (box[b + 1] - o.y) * iy; t2 = (box[b + 4] - o.y) * iy; tmin = Math.max(tmin, Math.min(t1, t2)); tmax = Math.min(tmax, Math.max(t1, t2));
      t1 = (box[b + 2] - o.z) * iz; t2 = (box[b + 5] - o.z) * iz; tmin = Math.max(tmin, Math.min(t1, t2)); tmax = Math.min(tmax, Math.max(t1, t2));
      if (tmax >= Math.max(tmin, 0)) hits.push(tmin, c);
    }
    const order = []; for (let i = 0; i < hits.length; i += 2) order.push(i);
    order.sort((a, b) => hits[a] - hits[b]);
    let best = 1e30, bi = -1;
    for (const oi of order) {
      if (hits[oi] > best) break;
      const c = hits[oi + 1];
      for (let j = c * CH; j < Math.min(n, (c + 1) * CH); j++) {
        const i = ord[j], t = i * 9;
        const e1x = pos[t + 3] - pos[t], e1y = pos[t + 4] - pos[t + 1], e1z = pos[t + 5] - pos[t + 2], e2x = pos[t + 6] - pos[t], e2y = pos[t + 7] - pos[t + 1], e2z = pos[t + 8] - pos[t + 2];
        const px = d.y * e2z - d.z * e2y, py = d.z * e2x - d.x * e2z, pz = d.x * e2y - d.y * e2x, det = e1x * px + e1y * py + e1z * pz;
        if (Math.abs(det) < 1e-12) continue;
        const f = 1 / det, sx = o.x - pos[t], sy = o.y - pos[t + 1], sz = o.z - pos[t + 2], u = f * (sx * px + sy * py + sz * pz);
        if (u < 0 || u > 1) continue;
        const qx = sy * e1z - sz * e1y, qy = sz * e1x - sx * e1z, qz = sx * e1y - sy * e1x, v = f * (d.x * qx + d.y * qy + d.z * qz);
        if (v < 0 || u + v > 1) continue;
        const dist = f * (e2x * qx + e2y * qy + e2z * qz);
        if (dist > 0 && dist < best) { best = dist; bi = i; }
      }
    }
    if (bi < 0) return null;
    const t = bi * 9, e1 = new THREE.Vector3(pos[t + 3] - pos[t], pos[t + 4] - pos[t + 1], pos[t + 5] - pos[t + 2]), e2 = new THREE.Vector3(pos[t + 6] - pos[t], pos[t + 7] - pos[t + 1], pos[t + 8] - pos[t + 2]);
    const nrm = e1.cross(e2).normalize(); if (nrm.dot(d) > 0) nrm.negate();
    return { distance: best, point: new THREE.Vector3(o.x + d.x * best, o.y + d.y * best, o.z + d.z * best), faceIndex: bi, face: { normal: nrm }, object: mesh };
  }
  return { intersect };
})();
function pickAt(e) {
  const r = renderer.domElement.getBoundingClientRect();
  ray.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), camera);
  if (geom.index) return ray.intersectObject(mesh)[0];                 // peças escondidas (índice filtrado): o raycast do three respeita
  return PK.intersect(ray.ray.origin, ray.ray.direction);
}
function paintAt(e) {
  const hit = pickAt(e); if (!hit) return; const p = hit.point;
  if (tool === "manual") {
    const r = brushR(), ids = trisNear(p, r).filter((i) => !hiddenG.has(seg[i])), c = geom.attributes.color.array, col = new THREE.Color(groups[active].color).lerp(new THREE.Color(0.78, 0.78, 0.8), 0.25);
    for (const i of ids) if (seg[i] !== active) { seg[i] = active; for (let k = 0; k < 3; k++) { c[i * 9 + k * 3] = col.r; c[i * 9 + k * 3 + 1] = col.g; c[i * 9 + k * 3 + 2] = col.b; } }
    geom.attributes.color.needsUpdate = true;
    const s = painting.stroke, last = s.points[s.points.length - 1];
    if (!last || p.distanceTo(new THREE.Vector3(...last)) > r * 0.3) s.points.push(p.toArray().map((x) => +x.toFixed(2)));
    return;
  }
  if (tool === "del") {
    const r = brushR(), er = e.shiftKey, ids = trisNear(p, r).filter((i) => !(seg && hiddenG.has(seg[i]))), c = geom.attributes.color.array;
    if (!delView) delView = new Uint8Array(nt);
    for (const i of ids) if (delView[i] !== (er ? 0 : 1)) { delView[i] = er ? 0 : 1; const col = triColor(i); for (let k = 0; k < 3; k++) { c[i * 9 + k * 3] = col.r; c[i * 9 + k * 3 + 1] = col.g; c[i * 9 + k * 3 + 2] = col.b; } }
    geom.attributes.color.needsUpdate = true;
    const s = painting.stroke, last = s.points[s.points.length - 1]; s.erase = er;
    if (!last || p.distanceTo(new THREE.Vector3(...last)) > r * 0.3) s.points.push(p.toArray().map((x) => +x.toFixed(2)));
    return;
  }
  if (tool === "sponge") {
    const s = painting.stroke, last = s.points[s.points.length - 1];
    if (!last || p.distanceTo(new THREE.Vector3(...last)) > brushR() * 0.4) { s.points.push(p.toArray().map((x) => +x.toFixed(2))); addStrokeDot(p, s.radius, 0x7dd3fc); }
    return;
  }
  if (tool === "cut") {
    if (e.shiftKey) {   // eraser
      const R = brushR() * 1.5; let changed = false;
      strokes.forEach((s) => { const n0 = s.points.length; s.points = s.points.filter((q) => p.distanceTo(new THREE.Vector3(...q)) > R); changed ||= s.points.length !== n0; });
      if (changed) { strokes = strokes.filter((s) => s.points.length); rebuildStrokes(); }
      return;
    }
    const s = painting.stroke, last = s.points[s.points.length - 1];
    if (!last || p.distanceTo(new THREE.Vector3(...last)) > brushR() * 0.4) { s.points.push(p.toArray().map((x) => +x.toFixed(2))); addStrokeDot(p, s.radius); }
  } else {
    const g = groups[active], last = painting.last;
    if (!last || p.distanceTo(last) > seedR() * 0.9) { g.points.push(p.toArray().map((x) => +x.toFixed(3))); painting.n++; painting.last = p.clone(); addMarker(p, g.color); }
  }
}
renderer.domElement.addEventListener("pointerdown", (e) => {
  if (showing === "plates") { down = null; return; }
  down = [e.clientX, e.clientY];
  if (tool === "del" && e.button === 0 && $("delWhole").checked) {       // whole loose piece with one click
    const h = pickAt(e); if (h) delOp({ component: h.point.toArray(), erase: e.shiftKey }); return;
  }
  if ((tool === "cut" || tool === "paint" || tool === "sponge" || tool === "manual" || tool === "del") && e.button === 0) {
    painting = tool === "paint" ? { n: 0, last: null } : { stroke: { points: [], radius: +(tool === "sponge" ? Math.max(brushR() * 2, +$("spongeStr").value * 2) : brushR()).toFixed(2) } };
    painting.xy = [e.clientX, e.clientY]; paintAt(e);
  }
});
let lastHover = 0;
renderer.domElement.addEventListener("pointermove", (e) => {
  const brushT = showing !== "plates" && (tool === "paint" || tool === "cut" || tool === "sponge" || tool === "manual" || tool === "del");
  if (brushT && performance.now() - lastHover > 30) {
    lastHover = performance.now(); const h = pickAt(e);
    if (h) {
      cursor.visible = true; cursor.position.copy(h.point); cursor.scale.setScalar(curR());
      const n = h.face.normal.clone().transformDirection(mesh.matrixWorld); cursor.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), n);
      cursor.material.color.set(tool === "cut" || tool === "del" ? 0xff5555 : tool === "sponge" ? 0x7dd3fc : groups[active].color);
    } else cursor.visible = false;
  }
  if (!painting || !(e.buttons & 1)) return;
  const [x0, y0] = painting.xy || [e.clientX, e.clientY]; const steps = Math.max(1, Math.ceil(Math.hypot(e.clientX - x0, e.clientY - y0) / 3));
  for (let k = 1; k <= steps; k++) paintAt({ clientX: x0 + (e.clientX - x0) * k / steps, clientY: y0 + (e.clientY - y0) * k / steps, shiftKey: e.shiftKey });
  painting.xy = [e.clientX, e.clientY];
});
addEventListener("pointerup", (e) => {
  if (!painting) return; const p = painting; painting = null;
  if (tool === "cut" && p.stroke && p.stroke.points.length) { strokes.push(p.stroke); history.push({ t: "st" }); }
  if (tool === "paint" && p.n) history.push({ t: "gp", g: active, n: p.n });
  if (tool === "del" && p.stroke && p.stroke.points.length) { delOp({ ops: [{ points: p.stroke.points, radius: +brushR().toFixed(3) }], erase: !!p.stroke.erase }); return; }
  if (tool === "sponge" && p.stroke && p.stroke.points.length) { sponge({ strokes: [p.stroke], strength: +$("spongeStr").value }); return; }
  if (tool === "manual" && p.stroke && p.stroke.points.length) {
    fetch("/api/paint", { method: "POST", body: JSON.stringify({ ops: [{ points: p.stroke.points, radius: +brushR().toFixed(3), label: active, skip: [...hiddenG] }] }) })
      .then(() => fetch("/api/state")).then((r) => r.json()).then((s) => { st.painted = s.painted; updateSteps(); });
    history.push({ t: "mp" }); if (!st.summary) st.summary = { groups: groups.map((g) => ({ name: g.name, tris: 0 })), seconds: 0 };
    return;
  }
  rebuildAll(); saveMarks();
});
renderer.domElement.addEventListener("pointerup", (e) => {
  if (!down || showing === "plates" || e.button !== 0 || tool === "cut" || tool === "paint" || tool === "sponge" || tool === "manual" || tool === "nav" || tool === "del") return; const moved = Math.hypot(e.clientX - down[0], e.clientY - down[1]); down = null;
  if (moved > 5 || tctrl.dragging) return;
  const r = renderer.domElement.getBoundingClientRect();
  ray.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), camera);
  const hit = ray.intersectObject(mesh)[0]; if (!hit) return;
  const p = hit.point;
  if (tool === "plane") {
    const n = camera.getWorldDirection(new THREE.Vector3()).negate();
    planes.push({ point: p.toArray(), normal: n.toArray(), radius: +(diag * 0.08).toFixed(1) });
    rebuildPlanes(); tctrl.attach(planeObjs[planeObjs.length - 1]); hint("plane"); saveMarks(); return;
  }
  if (!e.shiftKey && $("showPts").checked) {        // clicked on an existing dot -> menu to move it to another piece
    const r2 = renderer.domElement.getBoundingClientRect(); let best = null, bd = 12;
    groups.forEach((g, gi) => g.points.forEach((q, qi) => {
      const s = new THREE.Vector3(...q).project(camera); if (s.z > 1) return;
      const d = Math.hypot((s.x + 1) / 2 * r2.width - (e.clientX - r2.left), (1 - s.y) / 2 * r2.height - (e.clientY - r2.top));
      if (d < bd) { bd = d; best = [gi, qi]; }
    }));
    if (best) { dotMenu(best[0], best[1], e.clientX - r2.left, e.clientY - r2.top); return; }
  }
  if (e.shiftKey) {
    let best = null, bd = diag * 0.03;
    groups.forEach((g, gi) => g.points.forEach((q, qi) => { const d = p.distanceTo(new THREE.Vector3(...q)); if (d < bd) { bd = d; best = [gi, qi]; } }));
    if (best) { groups[best[0]].points.splice(best[1], 1); rebuildAll(); saveMarks(); }
    return;
  }
  groups[active].points.push(p.toArray().map((x) => +x.toFixed(3))); history.push({ t: "pt", g: active }); rebuildAll(); saveMarks();
});

// ---------- dot menu: move a seed dot to another piece
const selRing = new THREE.Mesh(new THREE.SphereGeometry(1, 20, 14), new THREE.MeshBasicMaterial({ color: 0xffffff, wireframe: true, depthTest: false }));
selRing.renderOrder = 12; selRing.visible = false; scene.add(selRing);
function closeDotMenu() { const m = $("dotMenu"); if (m) m.remove(); selRing.visible = false; }
function dotMenu(gi, qi, x, y) {
  closeDotMenu();
  const q = groups[gi].points[qi]; selRing.position.set(...q); selRing.scale.setScalar(seedR() * 1.3); selRing.visible = true;
  const m = document.createElement("div"); m.id = "dotMenu"; m.className = "dotmenu";
  m.style.left = Math.min(x + 14, view.clientWidth - 220) + "px"; m.style.top = Math.min(y - 10, view.clientHeight - 60 - groups.length * 34) + "px";
  m.innerHTML = `<div class="dm-t">Esta bolinha é de <b style="color:${groups[gi].color}">${groups[gi].name}</b>. Passar para:</div>` +
    groups.map((g, j) => j === gi ? "" : `<button data-j="${j}"><span class="sw" style="background:${g.color}"></span>${g.name}</button>`).join("") +
    `<button data-del="1" class="dm-del"><svg class="ic s"><use href="#i-trash"/></svg>Apagar bolinha</button>`;
  m.addEventListener("pointerdown", (ev) => ev.stopPropagation());
  m.querySelectorAll("button").forEach((b) => b.onclick = () => {
    const p = groups[gi].points.splice(qi, 1)[0];
    if (b.dataset.del) history.push({ t: "del", g: gi, i: qi, p });
    else { const j = +b.dataset.j; groups[j].points.push(p); history.push({ t: "mv", from: gi, i: qi, to: j }); }
    closeDotMenu(); rebuildAll(); saveMarks();
  });
  view.appendChild(m);
}
renderer.domElement.addEventListener("pointerdown", () => closeDotMenu());
addEventListener("keydown", (e) => { if (e.key === "Escape") closeDotMenu(); });
// ---------- coloring
async function loadSeg() {
  const r = await fetch("/api/seg"); if (!r.ok) { seg = null; return; }
  seg = new Uint8Array(await r.arrayBuffer());
}
function triColor(i, cols) {
  if (delView && delView[i]) {                    // checkerboard = will be deleted
    const cs = diag * 0.006, x = Math.floor(tc[i * 3] / cs) + Math.floor(tc[i * 3 + 1] / cs) + Math.floor(tc[i * 3 + 2] / cs);
    return (x & 1) ? CK_A : CK_B;
  }
  if (showing === "result" && seg && seg[i] < groups.length) return (cols ? cols[seg[i]] : new THREE.Color(groups[seg[i]].color)).clone().lerp(BASE_C, 0.25);
  if (showing === "smart" && smart && smart.view[i] >= 0) return smartCols[smart.view[i]];
  return BASE_C;
}
async function loadDel() {
  const r = await fetch("/api/del"); if (!r.ok) { delView = null; return; }
  delView = new Uint8Array(await r.arrayBuffer()); if (!delView.some((x) => x)) delView = null;
}
async function delOp(body) {
  const r = await (await fetch("/api/del", { method: "POST", body: JSON.stringify(body) })).json();
  if (r.changed) history.push({ t: "dl" });
  st.deleted = r.total; await loadDel(); paint(); updateSteps();
  return r;
}
function paint() {
  const c = geom.attributes.color.array; const base = BASE_C;
  const cols = groups.map((g) => new THREE.Color(g.color));
  for (let i = 0; i < nt; i++) {
    const col = triColor(i, cols);
    for (let k = 0; k < 3; k++) { c[i * 9 + k * 3] = col.r; c[i * 9 + k * 3 + 1] = col.g; c[i * 9 + k * 3 + 2] = col.b; }
  }
  geom.attributes.color.needsUpdate = true;
  applyHidden();
  $("showMarks").classList.toggle("on", showing === "marks"); $("showResult").classList.toggle("on", showing === "result");
  markerGroup.visible = strokeGroup.visible = $("showPts").checked && showing !== "pieces" && showing !== "smart"; loopGroup.visible = showing === "result"; seamGroup.visible = showing === "result";
  mesh.visible = showing !== "pieces" && showing !== "plates"; piecesGroup.visible = showing === "pieces"; platesGroup.visible = showing === "plates"; $("showPlates").classList.toggle("on", showing === "plates");
  if (showing === "plates") markerGroup.visible = strokeGroup.visible = false; $("explodeWrap").style.display = showing === "pieces" ? "flex" : "none"; $("showPieces").classList.toggle("on", showing === "pieces");
  $("spongeBox").style.display = seg ? "block" : "none"; $("straightBox").style.display = seg && st.summary ? "block" : "none"; updateSteps();
}
$("showMarks").onclick = () => { leavePlates(); showing = "marks"; paint(); };
$("showPts").onchange = () => paint();
$("showResult").onclick = () => { if (!seg) return; leavePlates(); showing = "result"; paint(); };

function applyHidden() {
  const useSeg = hiddenG.size && seg && showing !== "marks" && showing !== "smart";
  if (!useSeg) { if (geom.index) { geom.setIndex(null); } }
  else {
    const idx = [];
    for (let i = 0; i < nt; i++) if (!hiddenG.has(seg[i])) idx.push(i * 3, i * 3 + 1, i * 3 + 2);
    geom.setIndex(new THREE.BufferAttribute(new Uint32Array(idx), 1));
  }
  piecesGroup.children.forEach((m, k) => { const gi = groups.findIndex((gr) => gr.name === m.userData.name); m.visible = !hiddenG.has(gi >= 0 ? gi : k); });
  loopGroup.children.forEach((m) => { m.visible = true; });
}
function rebuildLoops() {
  loopGroup.clear(); const box = $("result"); box.innerHTML = "";
  if (!st.summary) return;
  const R = seedR();
  const suspicious = (l) => l.size < R * 3.2 && groups.some((g) => g.points.some((p) => new THREE.Vector3(...p).distanceTo(new THREE.Vector3(...l.center)) < R * 1.6));
  const lines = st.loops.filter((l) => l.size >= 0.5).map((l) => suspicious(l)
    ? `<div class="it" style="color:#fca5a5">Atenção: ${groups[l.a]?.name} ↔ ${groups[l.b]?.name}: só contornou um ponto (${l.size.toFixed(1)} mm) — marque mais pontos dessa peça em volta, ou o ponto está no lugar errado</div>`
    : `<div class="it" style="display:flex;align-items:center;gap:6px"><span style="flex:1">• ${groups[l.a]?.name ?? l.a} ↔ ${groups[l.b]?.name ?? l.b}: costura de ${l.size.toFixed(1)} mm</span><button class="x" data-straight="${st.loops.indexOf(l)}" title="deixar este corte reto (plano)">reto</button></div>`);
  const gs = st.summary.groups.map((g, i) => `<div class="it"><span style="color:${groups[i]?.color}">■</span> ${g.name}: ${(g.tris / 1000).toFixed(0)} mil triângulos</div>`);
  box.innerHTML = `<div class="small" style="margin:8px 0 4px">Resultado (${st.summary.seconds}s):</div>${gs.join("")}<div class="small" style="margin:8px 0 4px">${st.loops.filter((l) => l.size >= 0.5).length} costura(s):</div>${lines.join("")}`;
  box.querySelectorAll("[data-straight]").forEach((b) => b.onclick = () => straighten([+b.dataset.straight]));
  st.loops.forEach((l) => {
    const m = new THREE.Mesh(new THREE.TorusGeometry(Math.max(l.size / 2, diag * 0.005), diag * 0.0015, 8, 40), new THREE.MeshBasicMaterial({ color: 0xffffff, depthTest: false }));
    if (!suspicious(l)) return; m.material.color.set(0xff5555);
    m.renderOrder = 11; m.position.set(...l.center); m.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), new THREE.Vector3(...l.normal)); loopGroup.add(m);
  });
}
// ---------- finished pieces (exploded view)
async function loadPieces() {
  piecesGroup.clear(); if (!st.pieces) return false;
  const r = await fetch("/api/pieces"); if (!r.ok) return false;
  const b = await r.arrayBuffer(); let off = 0; const ms = [];
  st.pieces.forEach((p, k) => {
    const v = new Float32Array(b, off, p.nv * 3); off += p.nv * 12; const t = new Uint32Array(b, off, p.nt * 3); off += p.nt * 12;
    let g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.BufferAttribute(v, 3)); g.setIndex(new THREE.BufferAttribute(t, 1));
    g = toCreasedNormals(g, Math.PI / 6); g.computeBoundingBox();      // smooth curves, keep sharp edges (cut face, recess, pins)
    const cor = (groups.find((gr) => gr.name === p.name) ?? groups[k])?.color ?? "#999";     // pelo nome: peças vazias não entram na lista
    const m = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color: cor, roughness: 0.7 }));
    m.userData = p; piecesGroup.add(m); ms.push(m);
  });
  const all = new THREE.Box3(); ms.forEach((m) => all.union(m.geometry.boundingBox)); const C = all.getCenter(new THREE.Vector3());
  ms.forEach((m, k) => { m.userData.dir = k === ms.length - 1 ? new THREE.Vector3() : m.geometry.boundingBox.getCenter(new THREE.Vector3()).sub(C); });
  applyExplode();
  return true;
}
function applyExplode() {
  const f = +$("explode").value;
  piecesGroup.children.forEach((m) => { if (m.userData.dir) m.position.copy(m.userData.dir).multiplyScalar(f).add(new THREE.Vector3(0, 0, m.userData.dir.lengthSq() ? diag * 0.12 * f : 0)); });
}
$("explode").oninput = applyExplode;
$("showPieces").onclick = async () => {
  if (!st.pieces) { alert("As peças prontas aparecem depois de Visualizar encaixes (cartão Encaixe) ou Gerar arquivos."); return; }
  if (!piecesGroup.children.length) await loadPieces();
  leavePlates(); showing = "pieces"; paint();
};
// ---------- painel "Foco": cartão de opções, cartões recolhíveis e guia de etapas
const TOOLINFO = {
  nav: ["i-hand", "Navegar", "N", "Arraste para girar. Botão direito move, a roda aproxima. Segurar Espaço navega em qualquer ferramenta."],
  point: ["i-dot", "Pontos", "1", "Clique em cima de cada parte. Cada cor vira uma peça. Clique numa bolinha para passar ela para outra peça; Shift + clique apaga."],
  paint: ["i-brush", "Marcar área", "2", "Pinte uma região que pertence à peça selecionada na lista."],
  cut: ["i-scissors", "Pincel de corte", "3", "Desenhe a linha por onde o corte deve passar. Shift + pincel apaga o traço."],
  plane: ["i-plane", "Plano", "4", "Clique no modelo para criar um corte reto ali. Arraste as setas para ajustar."],
  manual: ["i-paint", "Pintar à mão", "5", "Pinta os triângulos direto na peça selecionada."],
  sponge: ["i-smooth", "Esponja", "6", "Passe sobre a costura (linha branca) para alisar o corte."],
  del: ["i-eraser", "Apagar", "7", "Pinte o que deve sumir. A área fica em xadrez."],
  straight: ["i-ruler", "Corte reto", "", "Troca costuras onduladas por cortes planos."],
  smart: ["i-spark", "Separador inteligente", "", "Sugere peças pra você começar. Não é um corte final: depois você confere e ajusta."],
};
function showPop(key) {
  const [ic, n, k, d] = TOOLINFO[key] || TOOLINFO.point;
  $("popH").innerHTML = `<svg class="ic s"><use href="#${ic}"/></svg>${n}${k ? `<kbd>${k}</kbd>` : ""}`; $("popD").textContent = d;
  const own = key === "straight" || key === "smart";
  document.querySelectorAll("#pop [data-pop]").forEach((el) => { el.hidden = el.dataset.pop !== key; });
  if (own) document.querySelectorAll("#pop [data-tools]").forEach((el) => { el.hidden = true; });
  document.querySelectorAll("#step2 .tool").forEach((b) => b.classList.toggle("popon", own && b.dataset.k === key));
  const btn = document.querySelector(`#step2 [data-k="${key}"]`), pop = $("pop");
  requestAnimationFrame(() => { const r = btn.getBoundingClientRect(); pop.style.top = Math.max(70, Math.min(innerHeight - pop.offsetHeight - 80, r.top - 8)) + "px"; });
}
document.querySelectorAll(".card > .hd").forEach((h) => h.onclick = () => h.parentElement.classList.toggle("closed"));
function openCard(id) { const c = $(id); c.classList.remove("closed"); setTimeout(() => c.scrollIntoView({ block: "nearest", behavior: "smooth" }), 50); }
function updateFlow() {
  const marked = groups.slice(0, -1).every((g) => g.points.length) || !!seg, sep = !!st.summary, files = !!(st.files && st.files.length);
  const done = [marked, sep, sep && jointsSeen, files], now = done.indexOf(false);
  done.forEach((d, i) => { const e = $("fl" + (i + 1)); e.classList.toggle("done", d); e.classList.toggle("now", i === now); e.querySelector("i").textContent = d ? "✓" : i + 1; });
  $("stepJ").classList.toggle("done", sep && jointsSeen);
  $("flowTxt").textContent = ["Marcar as peças", "Separar peças", "Visualizar encaixes", "Gerar arquivos"][now] ?? "Abrir pasta";
}
$("flowNext").onclick = () => {
  const t = $("flowTxt").textContent;
  if (t === "Marcar as peças") { $("toolPoint").click(); openCard("step1"); }
  else if (t === "Separar peças") { openCard("step3"); $("segment").click(); }
  else if (t === "Visualizar encaixes") { openCard("stepJ"); $("preview").click(); }
  else if (t === "Gerar arquivos") { openCard("step5"); $("finalize").click(); }
  else fetch("/api/open_folder", { method: "POST", body: JSON.stringify({ what: "out" }) });
};
$("goExport").onclick = () => { openCard("step5"); $("finalize").click(); };
// ---------- floating tool bar / navigation mode
const toolBtn = { point: "toolPoint", paint: "toolPaint", cut: "toolCut", plane: "toolPlane", manual: "toolManual", sponge: "toolSponge", del: "toolDel" };
document.querySelectorAll(".vtool").forEach((b) => b.onclick = () => { if (b.dataset.t === "nav") setTool("nav"); else $(toolBtn[b.dataset.t]).click(); });
let spaceNav = null;
addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT" || e.target.tagName === "TEXTAREA") return;
  if (e.code === "Space" && !e.repeat && tool !== "nav") { e.preventDefault(); spaceNav = tool; setTool("nav"); }
  else if (e.code === "Space") e.preventDefault();
  if ((e.key === "n" || e.key === "N") && !e.ctrlKey) setTool(tool === "nav" ? "point" : "nav");
});
addEventListener("keyup", (e) => {
  if (e.code === "Space") e.preventDefault();
  if (e.code === "Space" && spaceNav) { const back = spaceNav; spaceNav = null; if (back === "point") setTool("point"); else $(toolBtn[back])?.click(); }
});
$("toolStraight").onclick = () => {
  if (!seg || !st.summary) { alert("Primeiro separe as peças; o corte reto troca as costuras do resultado por cortes planos."); return; }
  $("straightBox").style.display = "block"; showPop("straight");
};
$("toolSmart").onclick = () => showPop("smart");
// ---------- joint settings (+ live cross-section drawing)
let jointType = "custom", pinType = "round";
function safeName(n) { return n.replace(/[^\p{L}\p{N}_\- ]/gu, "").trim(); }
function buildSides() {
  const box = $("jSides"); if (!box) return;
  const pairs = {};
  (st.summary ? st.loops : []).forEach((l) => { if (groups[l.a] && groups[l.b]) pairs[[l.a, l.b].sort().join(",")] = [l.a, l.b].sort((x, y) => x - y); });
  const list = Object.values(pairs);
  if (!list.length) { box.innerHTML = ""; return; }
  const PINOS = [["auto", "pinos: auto"], ["0", "sem pino (só o encaixe)"], ["1", "1 pino"], ["2", "2 pinos"], ["3", "3 pinos"], ["rabo", "rabo de andorinha (desliza)"], ["colar", "só colar (sem rebaixo)"]];
  box.innerHTML = `<div class="small" style="margin:8px 0 4px">Cada corte: rebaixo e pinos</div>` + list.map(([a, b]) => {
    const A = safeName(groups[a].name), B = safeName(groups[b].name), key = [A, B].sort().join("|"), cur = sidesSel[key] || "auto", pc = cutSel[key] || "auto";
    const dot = (g) => `<span style="color:${g.color}">●</span>`;
    return `<div class="cut"><div class="small" style="color:#cbd3e1">${dot(groups[a])} ${groups[a].name} ↔ ${dot(groups[b])} ${groups[b].name}</div>
      <div class="cutsel"><select data-k="${key}" data-w="side" data-ajuda="lado">
        <option value="auto"${cur === "auto" ? " selected" : ""}>rebaixo: auto</option>
        <option value="${A}"${cur === A ? " selected" : ""}>rebaixo no(a) ${groups[a].name}</option>
        <option value="${B}"${cur === B ? " selected" : ""}>rebaixo no(a) ${groups[b].name}</option></select>
      <select data-k="${key}" data-w="pins" data-ajuda="pinosCorte">${PINOS.map(([v, t]) => `<option value="${v}"${pc === v ? " selected" : ""}>${t}</option>`).join("")}</select></div></div>`;
  }).join("");
  box.querySelectorAll("select").forEach((sel) => sel.addEventListener("change", () => {
    if (sel.dataset.w === "pins") cutSel[sel.dataset.k] = sel.value; else sidesSel[sel.dataset.k] = sel.value;
    if (jointsSeen) $("previewInfo").innerHTML = `<div class="small warn">Mudou um corte: clique em <b>Visualizar encaixes</b> de novo pra aplicar (só refaz os encaixes, é rápido).</div>`;
  }));
}
const J = () => ({ sides: Object.fromEntries(Object.entries(sidesSel).filter(([, v]) => v !== "auto")), cuts: Object.fromEntries(Object.entries(cutSel).filter(([, v]) => v !== "auto").map(([k, v]) => [k, { pins: v }])), plano: $("jFlat").checked, step: $("jStep").checked, step_depth: +$("jStepD").value, round: +$("jRound").value, pin_type: pinType,
  pin_count: $("jCount").value, pin_d: +$("jD").value || 0, pin_len: +$("jL").value, loose: $("jLoose").checked,
  clear: +$("jClear").value, wall: +$("jWall").value, mag_d: +$("jMag").value.split("x")[0], mag_h: +$("jMag").value.split("x")[1], etiqueta: $("jLabel").checked });
function drawMagnet(j) {
  const s = 9, W = 300, cx = 150, cutY = 70, d = j.mag_d, h = j.mag_h, D = j.step ? j.step_depth : 0, c = Math.max(j.clear, 0.05);
  const hw = (d / 2 + c) * s, mw = d / 2 * s, hh = (h + 0.2) * s, bw = 20 + 4 * j.wall, kw = 20;
  let g = "";
  let lower = `M10 ${cutY} H${cx - bw - kw}`; if (D) lower += ` V${cutY + D * s} H${cx + bw + kw} V${cutY}`; lower += ` H${W - 10} V140 H10 Z`;
  g += `<path d="${lower}" fill="#3b4254" stroke="#6b7488"/>`;
  const fl = cutY + D * s; g += `<rect x="${cx - hw}" y="${fl}" width="${2 * hw}" height="${hh}" fill="#12151b"/><rect x="${cx - mw}" y="${fl + 1}" width="${2 * mw}" height="${h * s}" rx="2" fill="#c3cad6"/>`;
  let upper = `M10 ${cutY - 4} H${cx - bw - kw}`; if (D) upper += ` V${cutY - 4 + D * s} H${cx + bw + kw} V${cutY - 4}`; upper += ` H${W - 10} V8 H10 Z`;
  g += `<path d="${upper}" fill="#f2c12e" fill-opacity=".85" stroke="#b8901c"/>`;
  const tp = cutY - 4 + D * s; g += `<rect x="${cx - hw}" y="${tp - hh}" width="${2 * hw}" height="${hh}" fill="#12151b"/><rect x="${cx - mw}" y="${tp - h * s - 1}" width="${2 * mw}" height="${h * s}" rx="2" fill="#c3cad6"/>`;
  g += `<text x="${cx}" y="${tp - 2}" text-anchor="middle" fill="#ef4444" font-size="9" font-weight="700">N</text><text x="${cx}" y="${fl + 9}" text-anchor="middle" fill="#3b82f6" font-size="9" font-weight="700">S</text>`;
  g += `<text x="14" y="22" fill="#1f232c" font-size="11" font-weight="700">peça de cima</text><text x="14" y="134" fill="#cfd6e2" font-size="11">peça de baixo</text>`;
  g += `<text x="${W - 14}" y="22" text-anchor="end" fill="#1f232c" font-size="10" font-weight="600">${[D ? `rebaixo ${j.step_depth} mm` : "sem rebaixo", `ímã ${d} × ${h} mm`, `folga ${j.clear}`].join(" · ")}</text>`;
  return g;
}
function drawJoint() {
  const j = J(), s = 9, W = 300, cx = 150, cutY = 70;              // 9 px per mm
  if (j.pin_type === "magnet") {
    $("jointSvg").innerHTML = drawMagnet(j);
    document.querySelectorAll("#jointOpts [data-s]").forEach((el) => { el.hidden = !j.step; });
    $("jStep").closest("label").hidden = false; $("jCount").closest("label").hidden = false;
    document.querySelectorAll("#jointOpts [data-p]").forEach((el) => { el.hidden = false; });
    document.querySelectorAll("#jointOpts [data-np]").forEach((el) => { el.hidden = true; });
    document.querySelectorAll("#jointOpts [data-mg]").forEach((el) => { el.hidden = false; });
    return;
  }
  document.querySelectorAll("#jointOpts [data-np]").forEach((el) => { el.hidden = false; });
  document.querySelectorAll("#jointOpts [data-mg]").forEach((el) => { el.hidden = true; });
  const central = j.pin_type === "center";                         // pino grande no meio, sem rebaixo (estilo kit de designer)
  const d = (j.pin_d || (central ? 9 : 3)), L = j.pin_type === "none" ? 0 : central ? Math.max(j.pin_len, 0.6 * d) : j.pin_len, D = j.step && !central ? j.step_depth : 0, c = Math.max(j.clear, 0.05);
  const bw = 20 + 4 * j.wall, kw = 20;                             // half widths (drawing units)
  let g = "";
  // lower piece (receives the pocket and the hole)
  let lower = `M10 ${cutY} H${cx - bw - kw}`;
  if (D) lower += ` V${cutY + D * s + c * s} H${cx + bw + kw} V${cutY}`;
  lower += ` H${W - 10} V140 H10 Z`;
  g += `<path d="${lower}" fill="#3b4254" stroke="#6b7488"/>`;
  if (L) {
    const top = cutY + D * s, hw = (d / 2 + c) * s, hl = (L + 0.4) * s;
    g += j.pin_type === "cone" ? `<path d="M${cx - hw} ${top} L${cx - hw * 0.45} ${top + hl} H${cx + hw * 0.45} L${cx + hw} ${top} Z" fill="#12151b"/>`
      : `<rect x="${cx - hw}" y="${top}" width="${2 * hw}" height="${hl}" fill="#12151b"/>`;
  }
  // upper piece (gets the boss and the pin)
  let upper = `M10 ${cutY - 4} H${cx - bw - kw}`;
  if (D) upper += ` V${cutY - 4 + D * s} H${cx + bw + kw} V${cutY - 4}`;
  upper += ` H${W - 10} V8 H10 Z`;
  g += `<path d="${upper}" fill="#f2c12e" fill-opacity=".85" stroke="#b8901c"/>`;
  if (L) {
    const top = cutY - 4 + D * s, hw = d / 2 * s, pl = L * s, ch = j.pin_type === "cone" ? pl * 0.45 : 3;
    const k = j.pin_type === "cone" ? 0.45 : 0.8;
    g += j.loose ? `<rect x="${cx - hw}" y="${top - pl * 0.5 - D * s}" width="${2 * hw}" height="${pl + D * s}" rx="2" fill="#22c55e" stroke="#15803d"/>`
      : `<path d="M${cx - hw} ${top - 1} V${top + pl - ch} L${cx - hw * k} ${top + pl} H${cx + hw * k} L${cx + hw} ${top + pl - ch} V${top - 1} Z" fill="#f2c12e" stroke="#b8901c"/>`;
  }
  g += `<text x="14" y="22" fill="#1f232c" font-size="11" font-weight="700">peça de cima</text><text x="14" y="134" fill="#cfd6e2" font-size="11">peça de baixo</text>`;
  const txt = [D ? `rebaixo ${j.step_depth} mm` : "sem rebaixo", L ? `${j.loose ? "pino solto" : "pino"} ${({ round: "redondo", square: "quadrado", hex: "sextavado", cone: "cônico", center: "central" })[j.pin_type]} ${j.pin_d || "auto"}${j.pin_d ? " mm" : ""} × ${central && !j.pin_d ? "auto" : L + " mm"}` : "sem pino", `folga ${j.clear}`].join(" · ");
  g += `<text x="${W - 12}" y="${cutY - 8}" text-anchor="end" fill="#cfd6e2" font-size="10">${txt}</text>`;
  $("jointSvg").innerHTML = g;
  document.querySelectorAll("#jointOpts [data-s]").forEach((el) => { el.hidden = !j.step || central; });
  $("jStep").closest("label").hidden = central;                     // pino central não usa rebaixo
  $("jCount").closest("label").hidden = central;                    // e é sempre um só
  document.querySelectorAll("#jointOpts [data-p]").forEach((el) => { el.hidden = j.pin_type === "none"; });
}
document.querySelectorAll("#jType button").forEach((b) => b.onclick = () => {
  pinType = b.dataset.t; document.querySelectorAll("#jType button").forEach((x) => x.classList.toggle("on", x === b)); drawJoint();
});
document.querySelectorAll("#jointOpts input, #jointOpts select").forEach((el) => { if (!el.closest("#jSides")) { el.addEventListener("input", drawJoint); el.addEventListener("change", drawJoint); } });
// os ajustes do encaixe ficam salvos no projeto: ao reabrir, volta o que foi usado por último
function carregaJuntas(j) {
  if (!j) return;
  const set = (id, v) => { if (v !== undefined && v !== null && $(id)) { if ($(id).type === "checkbox") $(id).checked = !!v; else $(id).value = v; } };
  set("jFlat", j.plano ?? true); set("jStep", j.step); set("jStepD", j.step_depth); set("jRound", j.round); set("jCount", j.pin_count);
  set("jD", j.pin_d || ""); set("jL", j.pin_len); set("jLoose", j.loose); set("jClear", j.clear); set("jWall", j.wall); set("jLabel", j.etiqueta ?? true);
  if (j.mag_d && j.mag_h) { const v = `${j.mag_d}x${j.mag_h}`; if (![...$("jMag").options].some((o) => o.value === v)) $("jMag").add(new Option(`${j.mag_d} × ${j.mag_h} mm`, v)); $("jMag").value = v; }
  if (j.pin_type) { pinType = j.pin_type; document.querySelectorAll("#jType button").forEach((x) => x.classList.toggle("on", x.dataset.t === pinType)); }
  Object.assign(sidesSel, j.sides || {}); for (const [k, v] of Object.entries(j.cuts || {})) cutSel[k] = String(v.pins ?? "auto");
}
carregaJuntas(st.joints_salvos || st.joints_padrao);
drawJoint(); buildSides();
$("jPadrao").onclick = async () => {
  const j = J(); delete j.sides; delete j.cuts;
  await fetch("/api/padrao", { method: "POST", body: JSON.stringify({ juntas_padrao: j }) });
  alert("Pronto: esses ajustes de encaixe viram o padrão dos projetos novos (folga, pino, rebaixo, ímã).");
};
$("calib").onclick = async () => {
  const r = await (await fetch("/api/calibracao", { method: "POST", body: JSON.stringify({ joints: J() }) })).json();
  if (r.error) { alert("Não deu pra gerar o teste: " + r.error); return; }
  alert(J().pin_type === "magnet"
    ? "Teste de folga gerado (a pasta abriu). Imprima a régua e experimente o seu ímã em cada furo: o número gravado do lado é a folga em centésimos de mm (15 = 0,15). Escolha o furo onde ele entra justo e coloque esse valor em Folga."
    : "Teste de folga gerado (a pasta abriu). Imprima a régua e a chave, e encaixe a chave em cada furo: o número do lado é a folga em centésimos de mm (15 = 0,15). Escolha o furo onde entra firme sem forçar, coloque o valor em Folga e clique em Salvar como padrão.");
};
// ---------- dividir pela mesa: planos retos onde o modelo não cabe na impressora
const IMPRESSORAS = [["256x256x256", "Bambu Lab A1 / P1 / X1 (256)"], ["180x180x180", "Bambu Lab A1 mini (180)"], ["350x320x325", "Bambu Lab H2D"], ["220x220x250", "Creality Ender 3 / K1"],
  ["300x300x300", "Creality K1 Max"], ["250x210x220", "Prusa MK4"], ["180x180x180", "Prusa MINI"], ["225x225x265", "Elegoo Neptune 4"], ["250x250x260", "Anycubic Kobra 3"], ["custom", "Outra (digitar)"]];
IMPRESSORAS.forEach(([v, t], i) => $("mesaSel").add(new Option(t, i)));
try { const m = localStorage.getItem("voxel_mesa"); if (m !== null) $("mesaSel").value = m; const c = JSON.parse(localStorage.getItem("voxel_mesa_custom") || "null"); if (c) [$("mesaW").value, $("mesaD").value, $("mesaH").value] = c; } catch (e) {}
const mesaMostra = () => { $("mesaCustom").hidden = IMPRESSORAS[+$("mesaSel").value][0] !== "custom"; };
$("mesaSel").onchange = () => { mesaMostra(); try { localStorage.setItem("voxel_mesa", $("mesaSel").value); } catch (e) {} }; mesaMostra();
$("mesaRun").onclick = async () => {
  const sel = IMPRESSORAS[+$("mesaSel").value][0];
  const bed = sel === "custom" ? [+$("mesaW").value, +$("mesaD").value, +$("mesaH").value] : sel.split("x").map(Number);
  if (bed.some((v) => !(v > 30))) { alert("Digite largura, profundidade e altura da mesa em mm."); return; }
  try { if (sel === "custom") localStorage.setItem("voxel_mesa_custom", JSON.stringify(bed)); } catch (e) {}
  const size = bb.getSize(new THREE.Vector3()), mm = st.height ? st.height / size.z : 1;
  const D = [size.x * mm, size.y * mm, size.z * mm], B = bed.map((v) => v - 6).sort((a, b) => a - b);
  const cabe = (d) => { const s2 = [...d].sort((a, b) => a - b); return s2.every((v, i) => v <= B[i]); };
  if (cabe(D)) { alert(`O modelo inteiro (${D.map(Math.round).join(" × ")} mm) já cabe nessa mesa. Não precisa dividir.`); return; }
  let melhor = null;
  for (const a of [2, 0, 1]) for (let n = 2; n <= 12; n++) { const d = [...D]; d[a] /= n; if (cabe(d)) { if (!melhor || n < melhor.n) melhor = { a, n }; break; } }
  if (!melhor) { alert("Esse modelo precisa ser dividido em mais de uma direção. Use o Plano para fazer os cortes à mão (clique onde quer cortar)."); return; }
  const hasWork = groups.some((g) => g.points.length) || strokes.length || planes.length;
  if (hasWork && !confirm(`Dividir em ${melhor.n} partes troca as peças e marcações atuais. Continuar?`)) return;
  const { a, n } = melhor, eixo = ["x", "y", "z"][a], lo = bb.min[eixo], L = (bb.max[eixo] - bb.min[eixo]) / n;
  const nrm = [0, 0, 0]; nrm[a] = 1;
  planes = []; for (let k = 1; k < n; k++) { const pt = ctr.toArray(); pt[a] = lo + k * L; planes.push({ point: pt, normal: [...nrm], radius: +(diag * 0.55).toFixed(1) }); }
  // pontos de cada parte: triângulos perto do meio da fatia, bem espalhados
  const novos = [];
  for (let k = 0; k < n; k++) {
    const meio = lo + (k + 0.5) * L, tol = L * 0.2, cand = [];
    for (let i = 0; i < nt; i++) if (Math.abs(tc[i * 3 + a] - meio) < tol) cand.push(i);
    const pts = []; if (cand.length) {
      let first = cand[0]; pts.push(first);
      for (let q = 0; q < 2; q++) { let best = -1, bd = -1; for (let s2 = 0; s2 < cand.length; s2 += Math.max(1, Math.floor(cand.length / 4000))) { const i = cand[s2]; let dm = 1e18; for (const j of pts) { const dx = tc[i * 3] - tc[j * 3], dy = tc[i * 3 + 1] - tc[j * 3 + 1], dz = tc[i * 3 + 2] - tc[j * 3 + 2]; dm = Math.min(dm, dx * dx + dy * dy + dz * dz); } if (dm > bd) { bd = dm; best = i; } } if (best >= 0) pts.push(best); }
    }
    const nome = eixo === "z" ? (k === 0 ? "Base" : `Parte ${k + 1}`) : `Parte ${k + 1}`;
    novos.push({ name: nome, color: PALETTE[k % PALETTE.length], points: pts.map((i) => [tc[i * 3], tc[i * 3 + 1], tc[i * 3 + 2]].map((v) => +v.toFixed(3))) });
  }
  if (novos.some((g) => !g.points.length)) { alert("Não consegui achar pontos em todas as partes. Use o Plano à mão."); return; }
  groups = eixo === "z" ? [...novos.slice(1).reverse(), novos[0]] : novos;     // a última da lista fica com o que sobrar (a de baixo)
  strokes = []; history = []; active = 0; seg = null; st.summary = null;
  for (let i = 0; i + 1 < groups.length; i++) { const k2 = [safeName(groups[i].name), safeName(groups[i + 1].name)].sort().join("|"); cutSel[k2] = "rabo"; }
  await fetch("/api/paint_clear", { method: "POST", body: "{}" }); st.painted = 0;
  showing = "marks"; rebuildAll();
  await fetch("/api/marks", { method: "POST", body: JSON.stringify({ groups, planes, strokes }) });
  alert(`Dividido em ${n} partes de até ${Math.round(D[a] / n)} mm (mesa ${bed.join(" × ")} mm). Agora é só separar: os cortes saem retos, com rabo de andorinha onde couber.`);
  $("anchor").checked = false; $("segment").click();
};
// ---------- smart splitter
let smart = null, smartCols = [], smartLevel = "medio", smartFix = false;
document.querySelectorAll("#smartLevel button").forEach((b) => b.onclick = () => {
  smartLevel = b.dataset.l; document.querySelectorAll("#smartLevel button").forEach((x) => x.classList.toggle("on", x === b));
});
// ---------- separar por cor (3MF pintado pra AMS)
let corModo = "regioes";
function showObjetos() { $("objBox").hidden = !(st.objetos > 1); if (st.objetos > 1) $("objTxt").innerHTML = `Este arquivo tem <b>${st.objetos} objetos</b> separados (kit do designer).`; }
$("objRun").onclick = async () => {
  const hasWork = groups.some((g) => g.points.length) || strokes.length || planes.length;
  if (hasWork && !confirm("Isso troca as peças e marcações atuais pelos objetos do arquivo. Continuar?")) return;
  const r = await (await fetch("/api/object_split", { method: "POST", body: "{}" })).json();
  if (r.error) { alert(r.error); return; }
  groups = r.groups; planes = []; strokes = []; history.push({ t: "srv" }); active = 0; seg = null; st.summary = null;
  const s2 = await (await fetch("/api/state")).json(); st.painted = s2.painted;
  leavePlates(); showing = "marks"; rebuildAll(); $("anchor").checked = false; $("segment").click();
};
function showCores() {
  const c = st.cores, box = $("corBox");
  if (!c || Object.keys(c).length < 2) { box.hidden = true; return; }
  box.hidden = false;
  $("corTxt").innerHTML = `Este arquivo veio <b>pintado pra AMS</b>: ${Object.values(c).map((h) => `<span class="sw" style="display:inline-block;width:11px;height:11px;border-radius:3px;vertical-align:-1px;background:${h}"></span>`).join(" ")}`;
}
document.querySelectorAll("#corModo button").forEach((b) => b.onclick = () => { corModo = b.dataset.m; document.querySelectorAll("#corModo button").forEach((x) => x.classList.toggle("on", x === b)); });
$("corRun").onclick = async () => {
  const hasWork = groups.some((g) => g.points.length) || strokes.length || planes.length;
  if (hasWork && !confirm("Isso troca as peças e marcações atuais pelas cores do arquivo. Continuar?")) return;
  const r = await (await fetch("/api/color_split", { method: "POST", body: JSON.stringify({ modo: corModo }) })).json();
  if (r.error) { alert(r.error); return; }
  groups = r.groups; planes = []; strokes = []; history.push({ t: "srv" }); active = 0; seg = null; st.summary = null;
  const s2 = await (await fetch("/api/state")).json(); st.painted = s2.painted;
  showing = "marks"; rebuildAll(); $("anchor").checked = false; $("segment").click();
};
$("smartRun").onclick = async () => {
  const r = await fetch("/api/smart", { method: "POST", body: JSON.stringify({ level: smartLevel, bed: 256 }) });
  if (!r.ok) { alert("O programa está ocupado, espere terminar."); return; }
  poll("smart");
};
async function loadSmart() {
  const r = await fetch("/api/smart"); if (!r.ok) return;
  smart = await r.json(); smartCols = smart.pieces.map((p) => new THREE.Color(p.color).lerp(new THREE.Color(0.78, 0.78, 0.8), 0.2));
  showing = "smart"; paint(); showSmart();
}
function showSmart() {
  const box = $("smartRes");
  if (!smart) { box.innerHTML = ""; return; }
  const cutTxt = (p) => p.cuts.map((c) => `${Math.round(c.length ?? c.area)} mm`).join(", ");
  const techMsg = smart.technical ? `<div class="small warn" style="margin:10px 0 0">Parece uma peça técnica (${smart.technical}). Nesse tipo de peça o separador não sugere cortes: use o Plano ou o Pincel de corte.</div>` : "";
  box.innerHTML = techMsg + `<div class="small" style="margin:10px 0 4px">Sugestão: <b>${smart.pieces.length} peças</b>${smart.base ? " (base reconhecida)" : ""} · ${smart.seconds}s</div>` +
    smart.pieces.map((p) => `<div class="pc"><span class="sw" style="background:${p.color}"></span><span class="nm">${p.name}</span>
      <span class="st">${p.size.map(Math.round).join("×")} mm${p.fits ? "" : ` <span class="warn">não cabe na mesa</span>`}${p.cuts.length ? `<br>${p.cuts.length > 1 ? "cortes" : "corte"} ${cutTxt(p)}` : ""}</span></div>`).join("") +
    `<button class="btn pri" id="smartUse">Usar esta sugestão</button>
     <button class="btn ghost" id="smartDrop">Descartar</button>
     <div class="small" style="margin-top:6px">É um ponto de partida: confira e ajuste com os pontos, os pincéis e a pintura à mão.</div>`;
  $("smartDrop").onclick = () => { smart = null; showing = seg ? "result" : "marks"; paint(); showSmart(); };
  $("smartUse").onclick = async () => {
    const hasWork = groups.some((g) => g.points.length) || strokes.length || planes.length;
    if (hasWork && !confirm("Isso troca as peças e marcações atuais pela sugestão. Continuar?")) return;
    groups = smart.pieces.map((p) => ({ name: p.name, color: p.color, points: p.points }));
    planes = []; strokes = []; history = []; active = 0; seg = null; st.summary = null;
    await fetch("/api/paint_clear", { method: "POST", body: "{}" }); st.painted = 0;
    smart = null; showSmart(); showing = "marks"; rebuildAll();
    await fetch("/api/marks", { method: "POST", body: JSON.stringify({ groups, planes, strokes }) });
    $("anchor").checked = false; smartFix = true; $("segment").click();
  };
}
function rebuildAll() { buildSides(); rebuildGroups(); rebuildMarkers(); rebuildStrokes(); rebuildPlanes(); paint(); rebuildLoops(); hint(); }

async function sponge(params) {
  if (params.undo) {                                  // "Desfazer último ajuste" = o mesmo desfazer do Ctrl+Z
    const i = history.map((x) => x.t).lastIndexOf("srv"); if (i >= 0) history.splice(i, 1);
    await fetch("/api/desfazer", { method: "POST", body: "{}" }); poll("desfazer"); return;
  }
  await fetch("/api/smooth", { method: "POST", body: JSON.stringify(params) });
  history.push({ t: "srv" }); poll("smooth");
}
async function straighten(loops) {
  const r = await fetch("/api/straight", { method: "POST", body: JSON.stringify({ loops }) });
  if (!r.ok) { alert("O programa está ocupado, espere terminar."); return; }
  history.push({ t: "srv" }); poll("smooth");
}
$("straightAll").onclick = () => {
  if (!confirm("Deixar retos TODOS os cortes que já são quase planos?\n\nCostura comprida ou curva (capa, cabelo, dobra de roupa) é pulada automaticamente. Dá pra desfazer em \"Desfazer último ajuste\".")) return;
  straighten("all");
};
$("smoothAll").onclick = () => sponge({ strength: +$("spongeStr").value });
$("undoSmooth").onclick = () => sponge({ undo: true });
async function loadSeams() {
  seams = await (await fetch("/api/seams")).json(); seamGroup.clear();
  const mat = new THREE.LineBasicMaterial({ color: 0xffffff });
  seams.forEach((s) => {
    const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.Float32BufferAttribute(s.pts, 3));
    seamGroup.add(s.simple ? new THREE.LineLoop(g, mat) : new THREE.Points(g, new THREE.PointsMaterial({ color: 0xffffff, size: diag * 0.002 })));
  });
}
// ---------- server calls
let saveT = null;
function saveMarks() { clearTimeout(saveT); saveT = setTimeout(() => fetch("/api/marks", { method: "POST", body: JSON.stringify({ groups, planes, strokes }) }), 300); }
$("segment").onclick = async () => {
  const empty = groups.filter((g) => !g.points.length);
  if (empty.length) { alert(`Marque pelo menos um ponto em: ${empty.map((g) => g.name).join(", ")}`); return; }
  const body = { groups, planes, strokes, seed_r: +seedR().toFixed(2), auto_smooth: +$("autoSmooth").value };
  if ($("anchor").checked) body.base_below_z = +(bb.min.z + (bb.max.z - bb.min.z) * 0.015).toFixed(2);
  const rs = await fetch("/api/segment", { method: "POST", body: JSON.stringify(body) });
  if (rs.ok) history.push({ t: "srv" });
  poll("segment");
};
$("finalize").onclick = async () => {
  if (!st.summary) { alert("Primeiro clique em Separar peças e confira o resultado."); return; }
  const formats = { stl: $("fmtStl").checked, "3mf": $("fmt3mf").checked };
  if (!formats.stl && !formats["3mf"]) { alert("Escolha pelo menos um formato: STL ou 3MF."); return; }
  await fetch("/api/finalize", { method: "POST", body: JSON.stringify({ joints: J(), plug_min_area: +$("minarea").value, formats }) });
  poll("finalize");
};
$("preview").onclick = async () => {
  if (!st.summary) { alert("Primeiro clique em Separar peças e confira o resultado."); return; }
  const r = await fetch("/api/preview", { method: "POST", body: JSON.stringify({ joints: J(), plug_min_area: +$("minarea").value }) });
  if (!r.ok) { alert("O programa está ocupado, espere terminar."); return; }
  poll("preview");
};
function corteTxt(j) {
  return [j.dovetail ? `rabo de andorinha (canal em ${j.recess_in})` : "", j.step ? `rebaixo em ${j.recess_in} (${j.step.depth_mm} mm)` : "",
    (j.pins || []).length ? `${j.pins.length} pino(s) ${j.pins[0].d_mm} mm` : "", (j.magnets || []).length ? `${j.magnets.length} ímã(s) ${j.magnets[0].d_mm} × ${j.magnets[0].h_mm} mm` : ""].filter(Boolean).join(" + ") || "só colar";
}
function jointSummary(JJ) {
  const npins = JJ.reduce((a, j) => a + (j.pins ? j.pins.length : 0), 0), nstep = JJ.filter((j) => j.step).length, nmag = JJ.reduce((a, j) => a + (j.magnets ? j.magnets.length : 0), 0);
  const nrabo = JJ.filter((j) => j.dovetail).length, nnum = JJ.filter((j) => j.n).length;
  const nglue = JJ.filter((j) => !j.step && !j.dovetail && !(j.pins && j.pins.length) && !(j.magnets && j.magnets.length)).length, loose = JJ.some((j) => (j.pins || []).some((q) => q.loose));
  const line = [nrabo ? `${nrabo} rabo(s) de andorinha` : "", nstep ? `${nstep} rebaixo(s)` : "", npins ? `${npins} pino(s)${loose ? " soltos (Pinos.stl)" : ""}` : "", nmag ? `${nmag} furo(s) de ímã` : "",
    nglue ? `${nglue} só colar (pequeno ou fino demais)` : "", nnum ? `${nnum} com número gravado` : ""].filter(Boolean).join(" · ");
  const per = `<details style="margin:4px 0 6px"><summary>ver cada corte</summary><div class="small" style="margin-top:4px;line-height:1.6">` +
    JJ.map((j) => `${j.n ? `<b>nº ${j.n}</b> ` : ""}${j.piece} ↔ ${j.to}: ` + corteTxt(j)).join("<br>") + `</div></details>`;
  return `<div class="small" style="margin:2px 0 4px">${line}</div>` + per;
}
function fmtMin(m) { return m >= 60 ? `${Math.floor(m / 60)}h${String(m % 60).padStart(2, "0")}` : `${m} min`; }
function estHtml(e) {
  if (!e || !e.pecas || !e.pecas.length) return "";
  const lin = e.pecas.map((p) => `<tr><td>${p.name}</td><td class="n">${p.g} g</td><td class="n">${fmtMin(p.min)}</td><td class="n${p.suporte === "muito" ? " sup-muito" : ""}">${p.suporte === "nenhum" ? "sem suporte" : "suporte " + p.suporte}</td></tr>`).join("");
  return `<details style="margin:6px 0 4px"><summary>Filamento e tempo: ${e.total.g} g · ${e.total.m} m · ${fmtMin(e.total.min)} <span class="small">(aprox.)</span></summary>
    <table class="est">${lin}<tr class="tot"><td>Total</td><td class="n">${e.total.g} g</td><td class="n">${fmtMin(e.total.min)}</td><td class="n">${e.total.m} m</td></tr></table>
    ${e.purga ? `<div class="small" style="color:var(--ok)">Imprimindo cada cor separada você evita ~${e.purga.trocas} trocas de cor e ~${e.purga.g} g de purga no AMS.</div>` : ""}
    <div class="small">Estimativa com PLA, 15% de preenchimento e cada peça deitada como está nos pratos. O valor exato é o do fatiador.</div></details>`;
}
function showPreviewInfo() {
  $("previewInfo").innerHTML = `<div class="ok">Encaixes calculados</div>` + jointSummary(st.joints || []) + estHtml(st.estimativas) +
    `<div class="small">Gire e use o "afastar" no topo para conferir. Gostou? Clique em <b>Gerar arquivos</b>.</div>`;
}
async function poll(kind) {
  $("segment").disabled = $("finalize").disabled = $("preview").disabled = true;
  const b = $("busy"); b.style.display = "block";
  while (true) {
    st = await (await fetch("/api/state")).json();
    const i0 = st.log.map((l) => l.includes("analisando o modelo")).lastIndexOf(true);
    const nj = st.log.slice(Math.max(0, i0)).filter((l) => l.includes("JOINT")).length;
    b.textContent = st.stage[0].toUpperCase() + st.stage.slice(1) + "…" + (kind === "smart" && nj ? ` ${nj} corte(s) encontrado(s)` : ""); showLog();
    if (!st.busy) break;
    await new Promise((r) => setTimeout(r, 1200));
  }
  b.style.display = "none"; $("segment").disabled = $("finalize").disabled = $("preview").disabled = false;
  if (st.error) { alert("Deu erro: " + st.error); return; }
  if (kind === "smart") { await loadSmart(); return; }
  if (kind === "smooth") {
    try { const r = await (await fetch("/api/straight_report")).json(); if (r && r.skipped && r.skipped.length) alert(`Corte reto: ${r.done} costura(s) endireitada(s). Pulei ${r.skipped.length} curva(s) demais pra virar plano: ${r.skipped.join(", ")}.`); else if (r && r.done) alert(`Corte reto: ${r.done} costura(s) endireitada(s).`); } catch (e) {}
  }
  if (kind === "segment") { jointsSeen = false; openCard("step3"); }
  if (kind === "segment" || kind === "smooth") { await loadSeg(); await loadSeams(); showing = "result"; strokeGroup.clear(); rebuildAll(); }
  if (kind === "segment" && smartFix) {       // smart suggestion: drop dots that the cut only circled, then separate once more
    smartFix = false; const R = seedR(); let n = 0;
    for (const l of st.loops) {
      if (l.size >= R * 3.2) continue;
      groups.forEach((g) => { const k = g.points.findIndex((p) => new THREE.Vector3(...p).distanceTo(new THREE.Vector3(...l.center)) < R * 1.6); if (k >= 0 && g.points.length > 1) { g.points.splice(k, 1); n++; } });
    }
    if (n) { await fetch("/api/marks", { method: "POST", body: JSON.stringify({ groups, planes, strokes }) }); $("segment").click(); }
  }
  if (kind === "layout") { await enterPlates(); return; }
  if (kind === "desfazer") {
    if (st.marks) { groups = st.marks.groups; planes = st.marks.planes || []; strokes = st.marks.strokes || []; }
    if (active >= groups.length) active = 0;
    await loadSeg(); if (seg && !st.summary) seg = null;
    if (seg) await loadSeams(); else { seams = []; seamGroup.clear(); }
    showing = seg ? "result" : "marks"; rebuildAll(); showCores(); showObjetos();
    alert(st.desfeito ? `Desfeito: ${st.desfeito}.` : "Nada pra desfazer."); return;
  }
  if (kind === "mesa") { jointsSeen = false; openCard("step3"); }
  if (kind === "export") { const f = st.exported || []; showFiles(); alert(f.length ? `Pronto: ${f.join(", ")}\nNa pasta de saída (Abrir pasta, no cartão Exportar).` : "Exportado."); if (showing === "plates") plPanel(); return; }
  if (kind === "preview") { jointsSeen = true; openCard("stepJ"); piecesGroup.clear(); await loadPieces(); if (showing === "plates") await enterPlates(); else { showing = "pieces"; paint(); } showPreviewInfo(); $("files").innerHTML = ""; }
  if (kind === "finalize") { jointsSeen = true; openCard("step5"); $("previewInfo").innerHTML = ""; piecesGroup.clear(); showFiles(); await loadPieces(); if (showing === "plates") await enterPlates(); else { showing = "pieces"; paint(); } }
}
function showLog() { const l = $("log"); l.textContent = st.log.join("\n"); l.scrollTop = l.scrollHeight; }
function showFiles() {
  const f = $("files"); updateSteps();
  if (!st.files || !st.files.length) { f.innerHTML = ""; return; }
  const sizes = Object.fromEntries((st.pieces || []).map((p) => [p.name + ".stl", p.size]));
  const JJ = st.joints || [];
  f.innerHTML = `<div class="done">Arquivos prontos</div>` + (JJ.length ? jointSummary(JJ) : "") + estHtml(st.estimativas) +
    (st.arquivos_velhos ? `<div class="small warn" id="velhoAviso" style="margin:4px 0">Você mexeu nos pratos ou nos encaixes depois de gerar. Ao abrir no fatiador, o 3MF é atualizado sozinho.</div>` : "") +
    st.files.map((x) => `<div class="file">${x.endsWith(".3mf") ? '<svg class="ic s"><use href="#i-file"/></svg>' : '<svg class="ic s"><use href="#i-cube"/></svg>'}<span class="fn">${x}</span><span class="fs">${sizes[x] ? sizes[x].map(Math.round).join("×") + " mm" : x.endsWith(".3mf") ? "Bambu Studio / Orca" : ""}</span></div>`).join("") +
    `<button class="btn pri" id="slicerGo"><svg class="ic s"><use href="#i-file"/></svg><span id="slicerTxt">Abrir no fatiador</span></button>` +
    `<label class="f" id="slicerRow">Fatiador <select id="slicerSel"><option value="_padrao">Programa padrão</option></select></label>` +
    `<div class="row"><button class="btn" id="openOut"><svg class="ic s"><use href="#i-folder"/></svg>Abrir pasta</button><button class="btn" id="seePieces"><svg class="ic s"><use href="#i-eye"/></svg>Ver peças</button></div>` +
    `<div class="row"><button class="btn" id="guiaBtn"><svg class="ic s"><use href="#i-book"/></svg>Guia de montagem</button><button class="btn" id="calcBtn" title="custo e preço de venda, com os gramas e o tempo deste projeto"><svg class="ic s"><use href="#i-calc"/></svg>Calcular preço</button></div><div class="small" style="margin-top:6px;word-break:break-all">${st.out}</div>`;
  $("openOut").onclick = () => fetch("/api/open_folder", { method: "POST", body: JSON.stringify({ what: "out" }) });
  $("seePieces").onclick = () => $("showPieces").click();
  $("guiaBtn").onclick = guiaMontagem;
  $("calcBtn").onclick = () => { location.href = `/calculadora?projeto=${encodeURIComponent(st.project)}&de=cortar`; };
  carregaFatiadores();
  $("slicerGo").onclick = async () => {
    const app = $("slicerSel").value; try { localStorage.setItem("voxel_fatiador", app); } catch (e) {}
    const b = $("busy"); b.style.display = "block"; b.textContent = "Conferindo os arquivos…";
    let r; try { r = await (await fetch("/api/fatiador", { method: "POST", body: JSON.stringify({ app }) })).json(); } finally { b.style.display = "none"; }
    if (r.refeito) { st.arquivos_velhos = false; const w = $("velhoAviso"); if (w) w.remove(); }
    if (r.error) alert(r.error); else if (!r.ok) alert("Não achei esse fatiador neste computador.");
    else alert((r.refeito ? "Atualizei o 3MF com os pratos do jeito que estão agora. " : "") + `Abrindo no ${app === "_padrao" ? "programa padrão" : app}…`);
  };
}
let FATIADORES = null;
async function carregaFatiadores() {
  if (!FATIADORES) { try { FATIADORES = await (await fetch("/api/fatiadores")).json(); } catch (e) { FATIADORES = []; } }
  const sel = $("slicerSel"); if (!sel) return;
  FATIADORES.forEach((n) => sel.add(new Option(n, n), sel.options[sel.options.length - 1]));      // os instalados antes do "programa padrão"
  let pref = ""; try { pref = localStorage.getItem("voxel_fatiador") || ""; } catch (e) {}
  sel.value = [...sel.options].some((o) => o.value === pref) ? pref : (FATIADORES[0] || "_padrao");
  const txt = () => { $("slicerTxt").textContent = sel.value === "_padrao" ? "Abrir o 3MF" : `Abrir no ${sel.value}`; };
  sel.onchange = () => { txt(); try { localStorage.setItem("voxel_fatiador", sel.value); } catch (e) {} }; txt();
}
// ---------- guia de montagem: vista explodida numerada + passo a passo (imagem PNG na pasta dos arquivos)
async function guiaMontagem() {
  if (!st.pieces) { alert("O guia sai depois de Visualizar encaixes ou Gerar arquivos."); return; }
  if (!piecesGroup.children.length) await loadPieces();
  const antes = { showing, ex: $("explode").value, cam: camera.position.clone(), tg: controls.target.clone() };
  showing = "pieces"; paint(); $("explode").value = 0.9; applyExplode();
  const box = new THREE.Box3(); piecesGroup.children.forEach((m) => box.expandByObject(m));
  const c = box.getCenter(new THREE.Vector3()), sz = box.getSize(new THREE.Vector3()).length();
  controls.target.copy(c); camera.position.copy(c).add(new THREE.Vector3(sz * 0.9, -sz * 1.1, sz * 0.55)); controls.update();
  const W = 1600, Himg = 1100, vistos = scene.children.map((o) => [o, o.visible]);
  scene.children.forEach((o) => { if (o !== piecesGroup && !o.isLight) o.visible = false; });       // só as peças: sem planos, pontos e costuras
  const old = new THREE.Vector2(); renderer.getSize(old); const oldPR = renderer.getPixelRatio();
  renderer.setPixelRatio(1); renderer.setSize(W, Himg, false); camera.aspect = W / Himg; camera.updateProjectionMatrix();
  scene.background = new THREE.Color(0xf4f5f7); renderer.render(scene, camera);
  const shot = document.createElement("canvas"); shot.width = W; shot.height = Himg; shot.getContext("2d").drawImage(renderer.domElement, 0, 0, W, Himg);
  const centros = piecesGroup.children.map((m) => { const b = m.geometry.boundingBox.getCenter(new THREE.Vector3()).add(m.position).project(camera); return [(b.x + 1) / 2 * W, (1 - b.y) / 2 * Himg]; });
  vistos.forEach(([o, v]) => { o.visible = v; });
  scene.background = new THREE.Color(0x16181d); renderer.setPixelRatio(oldPR); renderer.setSize(old.x, old.y); resize();
  camera.position.copy(antes.cam); controls.target.copy(antes.tg); controls.update(); $("explode").value = antes.ex; applyExplode(); showing = antes.showing; paint();
  // ordem de montagem: começa pela última peça (a base) e vai colando o que encosta no que já está montado
  const nomes = st.pieces.map((p) => p.name), JJ = st.joints || [], feito = new Set([nomes[nomes.length - 1]]), passos = [];
  let mudou = true;
  while (mudou) {
    mudou = false;
    for (const j of JJ) {
      const [a, b] = [j.piece, j.to]; const nova = feito.has(a) && !feito.has(b) ? b : feito.has(b) && !feito.has(a) ? a : null;
      if (!nova) continue; feito.add(nova); passos.push({ peca: nova, em: nova === a ? b : a, j }); mudou = true;
    }
  }
  nomes.forEach((n) => { if (!feito.has(n)) passos.push({ peca: n, em: null, j: null }); });
  const num = Object.fromEntries(nomes.map((n, i) => [n, i + 1]));
  const linhas = passos.map((p, i) => `${i + 1}. ${p.em ? `Cole ${p.peca} em ${p.em}` : `${p.peca} (sem encaixe registrado)`}` + (p.j ? ` — ${corteTxt(p.j)}${p.j.n ? ` · número ${p.j.n} gravado nas duas faces` : ""}${p.j.dovetail ? " · entra deslizando pela ponta aberta" : ""}${(p.j.magnets || []).length ? " · confira a polaridade antes de colar os ímãs" : ""}` : ""));
  const Hpag = 140 + Himg + 60 + linhas.length * 34 + 120 + Math.ceil(nomes.length / 3) * 30;
  const cv = document.createElement("canvas"); cv.width = W; cv.height = Hpag; const x = cv.getContext("2d");
  x.fillStyle = "#ffffff"; x.fillRect(0, 0, W, Hpag);
  x.fillStyle = "#0B0E14"; x.font = "700 44px Segoe UI, system-ui, sans-serif"; x.fillText("Guia de montagem", 60, 80);
  x.font = "400 26px Segoe UI, system-ui, sans-serif"; x.fillStyle = "#5b6475"; x.fillText(`${st.name} · ${nomes.length} partes · Voxel Cut`, 60, 120);
  x.drawImage(shot, 0, 140);
  centros.forEach(([cx, cy], i) => {
    const y = cy + 140; x.beginPath(); x.arc(cx, y, 22, 0, 7); x.fillStyle = "#0B0E14"; x.fill(); x.lineWidth = 3; x.strokeStyle = "#ffffff"; x.stroke();
    x.fillStyle = "#fff"; x.font = "700 22px Segoe UI, sans-serif"; x.textAlign = "center"; x.textBaseline = "middle"; x.fillText(String(i + 1), cx, y + 1); x.textAlign = "left"; x.textBaseline = "alphabetic";
  });
  let y = 140 + Himg + 40;
  x.fillStyle = "#0B0E14"; x.font = "700 28px Segoe UI, sans-serif"; x.fillText("Partes", 60, y); y += 16;
  nomes.forEach((n, i) => {
    const col = i % 3, lin = Math.floor(i / 3), px = 60 + col * 500, py = y + 20 + lin * 30;
    x.fillStyle = corDe(n); x.fillRect(px, py - 16, 18, 18); x.fillStyle = "#1f2430"; x.font = "400 22px Segoe UI, sans-serif";
    const p = st.pieces[i]; x.fillText(`${i + 1}  ${n}${p && p.size ? `  (${p.size.map(Math.round).join("×")} mm)` : ""}`, px + 28, py);
  });
  y += 20 + Math.ceil(nomes.length / 3) * 30 + 30;
  x.fillStyle = "#0B0E14"; x.font = "700 28px Segoe UI, sans-serif"; x.fillText("Passo a passo", 60, y); y += 40;
  x.font = "400 22px Segoe UI, sans-serif"; x.fillStyle = "#1f2430";
  linhas.forEach((l) => {
    const pal = l.split(" "); let cur = "";
    for (const w of pal) { if (x.measureText(cur + w).width > W - 140) { x.fillText(cur, 60, y); y += 30; cur = "   "; } cur += w + " "; }
    x.fillText(cur, 60, y); y += 34;
  });
  const r = await (await fetch("/api/guia", { method: "POST", body: JSON.stringify({ png: cv.toDataURL("image/png") }) })).json();
  if (r.ok) alert("Guia de montagem salvo na pasta dos arquivos (e aberto): " + r.arquivo.split(/[\\/]/).pop());
}
function mostrarOut(o) { if (o) { $("outPath").textContent = o; $("outPath").title = o; } }
mostrarOut(st.out);
$("outMudar").onclick = async () => {
  const r = await (await fetch("/api/out_dir", { method: "POST", body: "{}" })).json();
  if (r.cancelado) return;
  st.out = r.out; mostrarOut(r.out); st.files = []; showFiles();
  alert(`Os arquivos deste projeto agora vão para:
${r.out}

Clique em Gerar arquivos pra gravar lá.`);
};
showLog(); if (st.files && st.files.length) showFiles();

let seamsVer = st.seams_version ?? 0;
setInterval(async () => {
  if ($("busy").style.display === "block") return;
  const s2 = await (await fetch("/api/state")).json();
  if (s2.seams_version !== seamsVer) { seamsVer = s2.seams_version; st.loops = s2.loops; st.summary = s2.summary; await loadSeams(); rebuildLoops(); }
}, 1500);
setTool(tool); updateSteps();

function saveThumb() {
  if (!renderer.domElement.width || !renderer.domElement.height || document.hidden) return;
  renderer.render(scene, camera);
  const c = document.createElement("canvas"); c.width = 460; c.height = 340; const x = c.getContext("2d"), src = renderer.domElement;
  const s = Math.max(c.width / src.width, c.height / src.height), w = src.width * s, h = src.height * s;
  x.drawImage(src, (c.width - w) / 2, (c.height - h) / 2, w, h);
  fetch("/api/thumb", { method: "POST", body: JSON.stringify({ jpg: c.toDataURL("image/jpeg", 0.82) }) });
}
setTimeout(saveThumb, 1500);
// ---------- pratos: as peças arrumadas nos pratos da impressora (como vão pro Bambu Studio)
const MESAS = [["", "Da impressora do arquivo"], ["256x256", "256 × 256 (A1, P1, X1)"], ["180x180", "180 × 180 (A1 mini)"], ["350x320", "350 × 320 (H2D)"]];
const plGrid = (n, w) => { const cols = Math.ceil(Math.sqrt(Math.max(1, n))); return (k) => [((k - 1) % cols) * w * 1.2, -Math.floor((k - 1) / cols) * w * 1.2]; };
function textSprite(txt, w) {
  const c = document.createElement("canvas"); c.width = 512; c.height = 96; const x = c.getContext("2d");
  x.font = "600 54px system-ui, sans-serif"; x.fillStyle = "#cfd6e2"; x.textBaseline = "middle"; x.fillText(txt, 6, 50);
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(c), depthTest: false, transparent: true }));
  s.scale.set(w * 0.42, w * 0.42 * 96 / 512, 1); s.center.set(0, 0.5); s.renderOrder = 5; return s;
}
function drawPlates(n, mesa) {
  plBase.clear(); const off = plGrid(n, mesa.w);
  for (let k = 1; k <= n; k++) {
    const [ox, oy] = off(k), g = new THREE.Group(); g.position.set(ox, oy, 0);
    const base = new THREE.Mesh(new THREE.BoxGeometry(mesa.w, mesa.h, 1.2), new THREE.MeshStandardMaterial({ color: 0x232833, roughness: 0.95 }));
    base.position.set(mesa.w / 2, mesa.h / 2, -0.62); g.add(base);
    const pts = [];
    for (let x = 0; x <= mesa.w + 0.01; x += 10) pts.push(x, 0, 0.02, x, mesa.h, 0.02);
    for (let y = 0; y <= mesa.h + 0.01; y += 10) pts.push(0, y, 0.02, mesa.w, y, 0.02);
    const lg = new THREE.BufferGeometry(); lg.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
    g.add(new THREE.LineSegments(lg, new THREE.LineBasicMaterial({ color: 0x343b4a })));
    const bg = new THREE.BufferGeometry(); bg.setAttribute("position", new THREE.Float32BufferAttribute([0, 0, 0.05, mesa.w, 0, 0.05, mesa.w, mesa.h, 0.05, 0, mesa.h, 0.05], 3));
    g.add(new THREE.LineLoop(bg, new THREE.LineBasicMaterial({ color: 0x7b879e })));
    for (const poly of mesa.excluir || []) {
      const sh = new THREE.Shape(poly.map(([a, b]) => new THREE.Vector2(a, b)));
      const ex = new THREE.Mesh(new THREE.ShapeGeometry(sh), new THREE.MeshBasicMaterial({ color: 0x3b1d22 })); ex.position.z = 0.04; g.add(ex);
    }
    const lab = textSprite(`Prato ${k}`, mesa.w); lab.position.set(0, mesa.h + mesa.w * 0.06, 0); g.add(lab);
    plBase.add(g);
  }
}
function framePlates() {
  const b = new THREE.Box3().setFromObject(plBase), c = b.getCenter(new THREE.Vector3()), s = b.getSize(new THREE.Vector3()), span = Math.max(s.x, s.y);
  controls.target.copy(c); camera.position.set(c.x, c.y - span * 0.95, span * 1.3);
  camera.near = span / 500; camera.far = span * 20; camera.updateProjectionMatrix(); controls.update();
}
function leavePlates() {
  if (showing !== "plates") return;
  plDrag = null; controls.enabled = true;
  if (camSaved) { camera.position.copy(camSaved.p); controls.target.copy(camSaved.t); camera.near = diag / 500; camera.far = diag * 20; camera.updateProjectionMatrix(); controls.update(); camSaved = null; }
}
function corDe(name) { return groups.find((g) => g.name === name)?.color ?? "#9ca3af"; }
function placeItem(m, it) {
  const p = m.geometry.attributes.position.array, R = it.R, s = m.userData.s;
  const mn = [1e9, 1e9, 1e9], mx = [-1e9, -1e9, -1e9];
  for (let i = 0; i < p.length; i += 3) {
    const x = p[i] * s, y = p[i + 1] * s, z = p[i + 2] * s;
    for (let r = 0; r < 3; r++) { const q = R[r][0] * x + R[r][1] * y + R[r][2] * z; if (q < mn[r]) mn[r] = q; if (q > mx[r]) mx[r] = q; }
  }
  m.userData.c = [(mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2, mn[2]]; m.userData.half = [(mx[0] - mn[0]) / 2, (mx[1] - mn[1]) / 2];
  setItemMatrix(m, it);
}
function setItemMatrix(m, it, wx, wy) {
  const R = it.R, s = m.userData.s, [cx, cy, cz] = m.userData.c;
  if (wx === undefined) { const [ox, oy] = plGrid(layout.n, layout.mesa.w)(it.placa); wx = ox + it.x; wy = oy + it.y; }
  m.matrixAutoUpdate = false;
  m.matrix.set(R[0][0] * s, R[0][1] * s, R[0][2] * s, wx - cx, R[1][0] * s, R[1][1] * s, R[1][2] * s, wy - cy, R[2][0] * s, R[2][1] * s, R[2][2] * s, -cz, 0, 0, 0, 1);
  m.matrixWorldNeedsUpdate = true;
  const [hx, hy] = m.userData.half, W = layout.mesa.w, H = layout.mesa.h;
  const fora = it.x - hx < -0.5 || it.y - hy < -0.5 || it.x + hx > W + 0.5 || it.y + hy > H + 0.5;
  m.material.emissive.set(fora ? 0x991b1b : plSel === it.name ? 0x1d4ed8 : 0x000000); m.material.emissiveIntensity = plSel === it.name ? 0.55 : 0.8;
  m.userData.fora = fora;
}
function parseStl(buf) {
  const n = new DataView(buf).getUint32(80, true), v = new Float32Array(n * 9); const dv = new DataView(buf);
  for (let i = 0; i < n; i++) for (let k = 0; k < 9; k++) v[i * 9 + k] = dv.getFloat32(84 + i * 50 + 12 + k * 4, true);
  const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.BufferAttribute(v, 3)); g.computeVertexNormals(); return g;
}
async function buildLayout() {
  plPieces.clear(); drawPlates(layout.n, layout.mesa);
  const geo = Object.fromEntries(piecesGroup.children.map((m) => [m.userData.name, m.geometry]));
  for (const it of layout.itens) {
    let g = geo[it.name], s = layout.escala || 1;
    if (!g) { const r = await fetch("/api/stl?name=" + encodeURIComponent(it.name)); if (!r.ok) continue; g = parseStl(await r.arrayBuffer()); s = 1; }
    const m = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color: it.name === "Pinos" ? "#d6d3d1" : corDe(it.name), roughness: 0.7 }));
    m.userData = { name: it.name, s }; plPieces.add(m); placeItem(m, it);
  }
}
async function buildSrc() {
  plSrc = await (await fetch("/api/placas_src")).json();
  const vp = new Int32Array(await (await fetch("/api/view_part")).arrayBuffer());
  layout = { n: plSrc.n, mesa: plSrc.mesa, itens: [] }; plPieces.clear(); drawPlates(plSrc.n, plSrc.mesa);
  const off = plGrid(plSrc.n, plSrc.mesa.w), cnt = {};
  for (let i = 0; i < nt; i++) cnt[vp[i]] = (cnt[vp[i]] || 0) + 1;
  let ci = 0;
  for (const [oid, o] of Object.entries(plSrc.objetos)) {
    const n = cnt[oid] || 0; if (!n) continue;
    const arr = new Float32Array(n * 9), M = o.M, [ox, oy] = off(o.placa), e = plSrc.escala || 1; let j = 0;
    for (let i = 0; i < nt; i++) {
      if (vp[i] !== +oid) continue;
      for (let k = 0; k < 3; k++) {
        const x = pos[i * 9 + k * 3] / e, y = pos[i * 9 + k * 3 + 1] / e, z = pos[i * 9 + k * 3 + 2] / e;
        arr[j++] = x * M[0][0] + y * M[1][0] + z * M[2][0] + M[3][0] + ox; arr[j++] = x * M[0][1] + y * M[1][1] + z * M[2][1] + M[3][1] + oy; arr[j++] = x * M[0][2] + y * M[1][2] + z * M[2][2] + M[3][2];
      }
    }
    const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.BufferAttribute(arr, 3)); g.computeVertexNormals();
    const m = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color: PALETTE[ci++ % PALETTE.length], roughness: 0.7 })); m.userData = { name: plSrc.nomes[oid] || oid, src: true };
    plPieces.add(m);
  }
}
async function enterPlates() {
  if (st.pieces) {
    if (!piecesGroup.children.length) await loadPieces();
    const r = await fetch("/api/layout");
    if (!r.ok) {
      const q = await fetch("/api/layout", { method: "POST", body: JSON.stringify({}) });
      if (!q.ok) { alert("O programa está ocupado, espere terminar."); return; }
      poll("layout"); return;
    }
    layout = await r.json(); plMode = "layout"; if (plSel && !layout.itens.some((it) => it.name === plSel)) plSel = null;
    await buildLayout();
  } else if (st.placas_src) { plMode = "arquivo"; plSel = null; await buildSrc(); }
  else { alert("Os pratos aparecem depois de Visualizar encaixes (quando as peças ficam prontas). Arquivos do Bambu Studio que já vêm com pratos mostram os pratos do arquivo."); return; }
  const first = showing !== "plates";
  if (first) camSaved = { p: camera.position.clone(), t: controls.target.clone() };
  showing = "plates"; paint(); if (first) framePlates(); plPanel(); openCard("stepP");
}
function plItem(name) { return layout.itens.find((it) => it.name === name); }
async function plSave(its, reorganiza) {
  const r = await fetch("/api/layout", { method: "POST", body: JSON.stringify({ itens: its }) });
  if (!r.ok) return;
  const L = await r.json(), mudou = L.n !== layout.n; layout = L;
  if (st.files && st.files.some((f) => f.endsWith(".3mf")) && !st.arquivos_velhos) { st.arquivos_velhos = true; showFiles(); }   // o 3MF da pasta ficou pra trás
  if (reorganiza) { await fetch("/api/layout", { method: "POST", body: JSON.stringify({ auto: true, pratos: { prato: reorganiza } }) }); poll("layout"); return; }
  if (mudou) await buildLayout(); else plPieces.children.forEach((m) => { const it = plItem(m.userData.name); if (it) setItemMatrix(m, it); });
  plPanel();
}
function plMeshOf(name) { return plPieces.children.find((m) => m.userData.name === name); }
function plSelect(name) { plSel = name; plPieces.children.forEach((m) => { const it = plItem(m.userData.name); if (it) setItemMatrix(m, it); }); plPanel(); }
function plRotate() {
  const it = plItem(plSel); if (!it) return; const R = it.R;       // gira 90° em volta do eixo vertical
  it.R = [[-R[1][0], -R[1][1], -R[1][2]], [R[0][0], R[0][1], R[0][2]], R[2].slice()];
  placeItem(plMeshOf(it.name), it); plSave([it]);
}
function plFace() {
  const it = plItem(plSel); if (!it || !it.opcoes || !it.opcoes.length) return;
  const down = (R) => [-R[2][0], -R[2][1], -R[2][2]], d = down(it.R);   // qual face do modelo está virada pra mesa
  let i = it.opcoes.findIndex((R) => { const o = down(R); return o[0] * d[0] + o[1] * d[1] + o[2] * d[2] > 0.99; });
  it.R = it.opcoes[(i + 1) % it.opcoes.length].map((r) => r.slice());
  placeItem(plMeshOf(it.name), it); plSave([it]);
}
function plPanel() {
  const bd = $("platesBd"); if (!bd) return;
  $("stepP").classList.toggle("done", plMode === "layout");
  if (plMode === "arquivo") {
    bd.innerHTML = `<div class="small">Assim as peças estão nos <b>${plSrc.n} prato(s)</b> do arquivo original (mesa ${Math.round(plSrc.mesa.w)} × ${Math.round(plSrc.mesa.h)}).</div>` +
      (st.objetos > 1 ? `<button class="btn" id="plObj"><svg class="ic s"><use href="#i-split"/></svg>Cada objeto vira uma peça</button><div class="small" style="margin-top:6px">Kit que já vem separado: cada objeto do arquivo vira uma peça. Depois é só Visualizar encaixes e arrumar os pratos.</div>` : "") +
      `<div class="small" style="margin-top:8px">Depois de separar e visualizar os encaixes, as peças novas aparecem aqui arrumadas nos pratos.</div>`;
    if ($("plObj")) $("plObj").onclick = () => $("objRun").click();
    return;
  }
  if (plMode !== "layout" || !layout) { bd.innerHTML = `<div class="small">Clique em <b>Pratos</b> no topo para ver as peças arrumadas nos pratos da impressora.</div>`; return; }
  const n = layout.n, it = plItem(plSel), cores = st.cores || {};
  const mesaAtual = layout.mesa_escolhida ? `${Math.round(layout.mesa.w)}x${Math.round(layout.mesa.h)}` : "";
  const porPrato = (k) => layout.itens.filter((i) => i.placa === k);
  let h = `<div class="small">${layout.itens.length} peças em <b>${n} prato(s)</b> · mesa ${Math.round(layout.mesa.w)} × ${Math.round(layout.mesa.h)} mm</div>
    <label class="f">Mesa <select id="plMesa">${MESAS.map(([v, t]) => `<option value="${v}"${v === mesaAtual ? " selected" : ""}>${t}</option>`).join("")}</select></label>` +
    (layout.cores ? `<label class="f" style="justify-content:flex-start;gap:8px"><input type="checkbox" id="plCor"${layout.por_cor ? " checked" : ""}> Um prato para cada cor (sem AMS)</label>` : "") +
    `<button class="btn" id="plAuto"><svg class="ic s"><use href="#i-spark"/></svg>Arrumar tudo de novo</button><div class="sub" style="margin-top:12px">Pratos</div>`;
  for (let k = 1; k <= n; k++) {
    const its = porPrato(k), fil = its.find((i) => i.fil)?.fil, sw = layout.por_cor && fil && cores[fil] ? `<span class="sw" style="background:${cores[fil]}"></span>` : "";
    const aviso = its.some((i) => plMeshOf(i.name)?.userData.fora || i.grande) ? ` <span class="warn" title="tem peça fora da mesa">⚠</span>` : "";
    h += `<div class="plrow">${sw}<b>Prato ${k}</b><span class="small">${its.length} peça(s)${aviso}</span><button class="x" data-re="${k}" title="rearrumar só este prato">rearrumar</button><button class="x" data-ex="${k}" title="exportar só este prato (3MF)"><svg class="ic s"><use href="#i-down"/></svg></button></div>`;
  }
  h += `<div class="sub" style="margin-top:12px">Peça</div>`;
  if (it) {
    h += `<div class="plsel"><span class="sw" style="background:${it.name === "Pinos" ? "#d6d3d1" : corDe(it.name)}"></span><b>${it.name}</b>${it.fixo ? `<span class="small"> · posição do designer</span>` : ""}</div>
      <div class="row"><button class="btn" id="plRot" title="girar 90° (R)">Girar 90°</button><button class="btn" id="plFace" title="deitar a peça em outra face">Outra face</button></div>
      <label class="f">Mandar pro prato <select id="plTo">${Array.from({ length: n }, (_, i) => `<option value="${i + 1}"${i + 1 === it.placa ? " selected" : ""}>Prato ${i + 1}</option>`).join("")}<option value="novo">Prato novo</option></select></label>
      <button class="btn" id="plExP"><svg class="ic s"><use href="#i-down"/></svg>Exportar só esta peça</button>`;
  } else h += `<div class="small">Clique numa peça para girar, deitar em outra face ou mandar pra outro prato. Arraste para mudar de lugar.</div>`;
  h += `<div class="small" style="margin-top:10px">O <b>Gerar arquivos</b> grava o 3MF com todos os pratos assim, pronto pro Bambu Studio.</div>`;
  bd.innerHTML = h;
  $("plMesa").onchange = () => {
    const v = $("plMesa").value, [w, hh] = v ? v.split("x").map(Number) : [0, 0];
    fetch("/api/layout", { method: "POST", body: JSON.stringify({ auto: true, pratos: { mesa: v ? { w, h: hh } : "arquivo", refazer: true } }) }).then(() => poll("layout"));
  };
  if ($("plCor")) $("plCor").onchange = () => fetch("/api/layout", { method: "POST", body: JSON.stringify({ auto: true, pratos: { por_cor: $("plCor").checked, refazer: true } }) }).then(() => poll("layout"));
  $("plAuto").onclick = () => { if (confirm("Arrumar todas as peças de novo? O que você mudou à mão nos pratos se perde.")) fetch("/api/layout", { method: "POST", body: JSON.stringify({ auto: true, pratos: { refazer: true } }) }).then(() => poll("layout")); };
  bd.querySelectorAll("[data-re]").forEach((b) => b.onclick = () => fetch("/api/layout", { method: "POST", body: JSON.stringify({ auto: true, pratos: { prato: +b.dataset.re } }) }).then(() => poll("layout")));
  bd.querySelectorAll("[data-ex]").forEach((b) => b.onclick = () => plExport({ what: "prato", prato: +b.dataset.ex }));
  if (it) {
    $("plRot").onclick = plRotate; $("plFace").onclick = plFace;
    $("plExP").onclick = () => plExport({ what: "peca", name: it.name });
    $("plTo").onchange = () => {
      const v = $("plTo").value, k = v === "novo" ? n + 1 : +v; it.placa = k; it.x = layout.mesa.w / 2; it.y = layout.mesa.h / 2;
      plSave([it], v === "novo" ? null : k);
    };
  }
}
async function plExport(body) {
  const r = await fetch("/api/export", { method: "POST", body: JSON.stringify({ ...body, joints: J(), plug_min_area: +$("minarea").value }) });
  if (!r.ok) { alert("O programa está ocupado, espere terminar."); return; }
  poll("export");
}
function plPick(e) {
  const r = renderer.domElement.getBoundingClientRect();
  ray.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), camera);
  return ray;
}
const chao = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0);
renderer.domElement.addEventListener("pointerdown", (e) => {
  if (showing !== "plates" || plMode !== "layout" || e.button !== 0) return;
  const rr = plPick(e), hit = rr.intersectObjects(plPieces.children)[0];
  if (!hit) { plDrag = { none: true, x: e.clientX, y: e.clientY }; return; }
  const m = hit.object, it = plItem(m.userData.name), p0 = rr.ray.intersectPlane(chao, new THREE.Vector3()); if (!it || !p0) return;
  const [ox, oy] = plGrid(layout.n, layout.mesa.w)(it.placa);
  plDrag = { m, it, p0, w0: [ox + it.x, oy + it.y], moved: false, x: e.clientX, y: e.clientY }; controls.enabled = false;
  if (plSel !== it.name) plSelect(it.name);
});
renderer.domElement.addEventListener("pointermove", (e) => {
  if (!plDrag || plDrag.none || showing !== "plates") return;
  if (!plDrag.moved && Math.hypot(e.clientX - plDrag.x, e.clientY - plDrag.y) < 4) return;
  plDrag.moved = true; const p = plPick(e).ray.intersectPlane(chao, new THREE.Vector3()); if (!p) return;
  const wx = plDrag.w0[0] + p.x - plDrag.p0.x, wy = plDrag.w0[1] + p.y - plDrag.p0.y; plDrag.w = [wx, wy];
  setItemMatrix(plDrag.m, plDrag.it, wx, wy);
});
addEventListener("pointerup", (e) => {
  if (!plDrag) return; const d = plDrag; plDrag = null; controls.enabled = true;
  if (d.none) { if (Math.hypot(e.clientX - d.x, e.clientY - d.y) < 4 && plSel) plSelect(null); return; }
  if (!d.moved || !d.w) return;
  const W = layout.mesa.w, H = layout.mesa.h, off = plGrid(layout.n, W); let alvo = null;
  for (let k = 1; k <= layout.n; k++) { const [ox, oy] = off(k); if (d.w[0] >= ox - 5 && d.w[0] <= ox + W + 5 && d.w[1] >= oy - 5 && d.w[1] <= oy + H + 5) alvo = k; }
  if (!alvo) { setItemMatrix(d.m, d.it); return; }                    // soltou fora dos pratos: volta
  const [ox, oy] = off(alvo); d.it.placa = alvo; d.it.x = +(d.w[0] - ox).toFixed(2); d.it.y = +(d.w[1] - oy).toFixed(2);
  setItemMatrix(d.m, d.it); plSave([d.it]);
});
addEventListener("keydown", (e) => {
  if (showing !== "plates" || !plSel || e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
  if (e.key === "r" || e.key === "R") plRotate();
  if (e.key === "f" || e.key === "F") plFace();
});
$("showPlates").onclick = () => enterPlates();
// ---------- loop
window.cortador = { THREE, mesh, camera, ray, renderer, controls, piecesGroup, platesGroup, PK, paint, rebuildAll, rebuildMarkers, get layout() { return layout; }, get groups() { return groups; }, get active() { return active; }, tctrl };
// plano de recorte da câmera acompanha o zoom: de perto não some pedaço do modelo e dá pra ver cada triângulo
function ajustaNear() {
  const ref = showing === "plates" ? 1000 : diag, dist = camera.position.distanceTo(controls.target);
  const nn = Math.min(ref / 500, Math.max(ref / 200000, dist * 0.02));
  if (Math.abs(camera.near - nn) > 0.25 * nn) { camera.near = nn; camera.updateProjectionMatrix(); }
}
renderer.setAnimationLoop(() => { controls.update(); ajustaNear(); sun.position.copy(camera.position); renderer.render(scene, camera); });
