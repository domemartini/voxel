// Tutorial: balões que apontam cada parte da tela. Abre sozinho na primeira vez; depois, pelo botão "?" no topo.
const PASSOS = [
  [null, "Bem-vindo ao Voxel Cut", "Em 4 etapas você transforma um modelo inteiro em peças prontas pra imprimir, com encaixe. Leva um minuto pra conhecer a tela."],
  ["#step2", "Ferramentas", "A principal é a de <b>Pontos</b> (tecla 1): clique em cima de cada parte da figura. As outras ajudam a ajustar o corte: pincel de corte, plano, pintar à mão, esponja e corte reto."],
  ["#step1", "Peças", "Cada cor da lista é uma peça. Selecione uma e clique no modelo pra marcar. A <b>última</b> da lista fica com tudo o que sobrar (normalmente a base)."],
  ["#toolSmart", "Atalhos pra começar", "O <b>Separador inteligente</b> sugere as peças, e um 3MF pintado pra AMS separa por cor num clique. Modelo maior que a mesa? Na ferramenta <b>Plano</b> tem <b>Dividir pela mesa</b>."],
  ["#flow", "Siga as etapas", "Indicar › Separar › Encaixar › Exportar. O botão azul sempre mostra o próximo passo."],
  ["#stepJ", "Encaixe", "Pino, rebaixo, <b>ímã</b> ou <b>rabo de andorinha</b>, com o número do corte gravado dentro do encaixe. Use o <b>Teste de folga</b> pra acertar a folga da sua impressora."],
  ["#views", "Ver o resultado", "Alterne entre as marcações, o resultado da separação, as peças prontas (com o “afastar”) e os pratos da impressora."],
  ["#goExport", "Gerar arquivos", "Sai um STL por peça e um 3MF com os pratos. Depois dá pra abrir direto no fatiador e gerar o <b>guia de montagem</b>."],
  ["#tourBtn", "Pronto!", "Pra ver este tutorial de novo, é só clicar aqui. Bom corte!"],
];
const $ = (s) => document.querySelector(s);
let i = 0, raiz = null;

function fechar(visto = true) {
  if (raiz) raiz.remove(); raiz = null;
  removeEventListener("keydown", teclas, true); removeEventListener("resize", mostrar);
  if (visto) fetch("/api/padrao", { method: "POST", body: JSON.stringify({ tutorial_visto: true }) }).catch(() => {});
}
function teclas(e) {
  if (!raiz) return;
  if (e.key === "Escape") { e.stopPropagation(); fechar(); }
  if (e.key === "ArrowRight" || e.key === "Enter") { e.stopPropagation(); e.preventDefault(); ir(1); }
  if (e.key === "ArrowLeft") { e.stopPropagation(); ir(-1); }
}
function ir(d) { i += d; if (i < 0) i = 0; if (i >= PASSOS.length) { fechar(); return; } mostrar(); }
function mostrar() {
  if (!raiz) return;
  const [sel, tit, txt] = PASSOS[i], el = sel && $(sel);
  if (sel === "#stepJ" && el) el.classList.remove("closed");
  let r = el ? el.getBoundingClientRect() : null;
  if (r && (r.width < 2 || r.height < 2)) r = null;
  const hole = raiz.querySelector(".hole"), tip = raiz.querySelector(".tip");
  if (r) { const p = 6; Object.assign(hole.style, { left: r.left - p + "px", top: r.top - p + "px", width: r.width + 2 * p + "px", height: r.height + 2 * p + "px", display: "block" }); }
  else Object.assign(hole.style, { left: innerWidth / 2 + "px", top: innerHeight / 2 + "px", width: "0px", height: "0px", display: "block" });
  tip.innerHTML = `<h4>${tit}</h4><p>${txt}</p><div class="nav"><span class="dots">${i + 1} de ${PASSOS.length}</span>` +
    (i > 0 ? `<button data-a="-1">Voltar</button>` : `<button data-a="x">Pular</button>`) + `<button class="pri" data-a="1">${i === PASSOS.length - 1 ? "Começar" : "Próximo"}</button></div>`;
  tip.querySelectorAll("button").forEach((b) => b.onclick = () => (b.dataset.a === "x" ? fechar() : ir(+b.dataset.a)));
  const tw = 320, th = tip.offsetHeight || 170, m = 14;
  let x, y;
  if (!r) { x = (innerWidth - tw) / 2; y = (innerHeight - th) / 2; }
  else if (r.right + tw + m * 2 < innerWidth && r.left < innerWidth / 2) { x = r.right + m * 2; y = r.top; }
  else if (r.left - tw - m * 2 > 0) { x = r.left - tw - m * 2; y = r.top; }
  else { x = Math.min(innerWidth - tw - m, Math.max(m, r.left + r.width / 2 - tw / 2)); y = r.top > innerHeight / 2 ? r.top - th - m * 2 : r.bottom + m * 2; }
  tip.style.left = Math.max(m, Math.min(innerWidth - tw - m, x)) + "px"; tip.style.top = Math.max(m, Math.min(innerHeight - th - m, y)) + "px";
}
export function abrirTutorial() {
  fechar(false); i = 0;
  raiz = document.createElement("div"); raiz.id = "tour"; raiz.innerHTML = `<div class="hole"></div><div class="tip" role="dialog" aria-label="tutorial"></div>`;
  document.body.appendChild(raiz); addEventListener("keydown", teclas, true); addEventListener("resize", mostrar);
  mostrar(); requestAnimationFrame(mostrar);
}
function quandoPronto(fn, n = 0) {                     // espera a tela do cortador terminar de carregar o modelo
  if ($("#busy") && getComputedStyle($("#busy")).display === "none" && window.cortador) return fn();
  if (n < 120) setTimeout(() => quandoPronto(fn, n + 1), 250);
}
quandoPronto(() => {
  const b = $("#tourBtn"); if (b) b.onclick = abrirTutorial;
  fetch("/api/state").then((r) => r.json()).then((s) => { if (!s.tutorial_visto) setTimeout(abrirTutorial, 600); }).catch(() => {});
});
