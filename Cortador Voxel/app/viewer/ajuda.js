// Balões de ajuda com desenho: parar o mouse em cima de uma opção mostra o que ela faz (corte visto de lado ou de cima).
// Cores iguais ao desenho do encaixe: peça de cima amarela, peça de baixo cinza, medida em vermelho.
const CIMA = 'fill="#f2c12e" fill-opacity=".9" stroke="#b8901c"', BAIXO = 'fill="#3b4254" stroke="#6b7488"', FURO = 'fill="#12151b"';
const TXT = (x, y, t, a = "start", c = "#cfd6e2") => `<text x="${x}" y="${y}" fill="${c}" font-size="10" text-anchor="${a}">${t}</text>`;
const SETA = (x1, y1, x2, y2) => `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="#ef4444" stroke-width="1.6" marker-start="url(#aj-p)" marker-end="url(#aj-p)"/>`;
const DEFS = `<defs><marker id="aj-p" viewBox="0 0 6 6" refX="3" refY="3" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0 0 6 3 0 6z" fill="#ef4444"/></marker></defs>`;
// peça de cima com ressalto + peça de baixo com rebaixo (vista de lado)
const ENCAIXE = (gap = 14, alt = 18) => `<path d="M20 12 H220 V48 H152 V${48 + alt} H88 V48 H20 Z" ${CIMA}/>
  <path d="M20 ${62 + gap} H84 V${62 + gap + alt + 4} H156 V${62 + gap} H220 V112 H20 Z" ${BAIXO}/>`;
const PEGADA = (pinos) => `<rect x="25" y="18" width="190" height="84" rx="26" ${BAIXO}/>` + pinos;
const circ = (x, y, r) => `<circle cx="${x}" cy="${y}" r="${r}" ${CIMA}/>`;
const quad = (x, y, r) => `<rect x="${x - r}" y="${y - r}" width="${2 * r}" height="${2 * r}" ${CIMA}/>`;
const hexa = (x, y, r) => `<polygon points="${[0, 1, 2, 3, 4, 5].map((i) => `${x + r * Math.cos(i * Math.PI / 3)},${y + r * Math.sin(i * Math.PI / 3)}`).join(" ")}" ${CIMA}/>`;

const AJUDA = {
  jFlat: ["Corte reto", "Onde a peça encosta na outra, o corte vira um plano reto: a peça assenta inteira na mesa e imprime sem árvore de suporte embaixo.",
    `<path d="M15 14 H105 V58 Q60 92 15 58 Z" ${CIMA}/><path d="M15 60 Q60 94 105 60 V110 H15 Z" ${BAIXO}/>${TXT(60, 118, "curvo", "middle")}
     <path d="M135 14 H225 V66 H135 Z" ${CIMA}/><path d="M135 70 H225 V110 H135 Z" ${BAIXO}/>${TXT(180, 118, "reto", "middle")}`],
  jStep: ["Encaixe no formato do corte", "A peça de cima ganha um ressalto com o contorno do corte e a de baixo um rebaixo igual, onde ele entra. Alinha as peças sozinho, sem precisar de pino.",
    ENCAIXE() + TXT(226, 40, "ressalto", "end", "#1f232c") + TXT(226, 104, "rebaixo", "end")],
  jStepD: ["Altura do encaixe", "Quanto o ressalto sai da peça de cima (e a fundura do rebaixo). Pata pequena: 1 a 1,5 mm. Peça grande: 2 a 3 mm.",
    ENCAIXE() + SETA(166, 48, 166, 66) + TXT(172, 61, "altura", "start", "#fecaca")],
  jRound: ["Arredondamento", "Arredonda os cantos do ressalto (visto de cima). Encaixa mais fácil e não fica ponta fina que quebra.",
    `<path d="M20 30 L70 18 L105 45 L90 95 L35 100 L15 60 Z" ${CIMA}/>${TXT(60, 116, "0 mm: cantos vivos", "middle")}
     <path d="M140 30 L190 18 L225 45 L210 95 L155 100 L135 60 Z" fill="#f2c12e" fill-opacity=".9" stroke="#f2c12e" stroke-linejoin="round" stroke-width="14"/>${TXT(180, 116, "arredondado", "middle")}`],
  jWall: ["Parede na borda", "Quanto o ressalto fica pra dentro da borda do corte (visto de cima). Parede maior deixa a borda mais forte; em peça pequena (pata) use 0,4, senão não sobra espaço pro encaixe.",
    PEGADA(`<rect x="55" y="42" width="130" height="36" rx="12" ${CIMA}/>`) + SETA(25, 60, 55, 60) + TXT(30, 54, "parede", "start", "#fecaca") + TXT(120, 64, "ressalto", "middle", "#1f232c")],
  jClear: ["Folga", "Espaço deixado entre o que entra (ressalto, pino) e o buraco, pra encaixar sem forçar. 0,15 mm serve pra maioria das impressoras; se ficou apertado, aumente pra 0,2.",
    `<rect x="20" y="58" width="200" height="54" ${BAIXO}/><rect x="92" y="58" width="56" height="40" ${FURO}/><rect x="20" y="14" width="200" height="38" ${CIMA}/>
     <rect x="100" y="50" width="40" height="44" ${CIMA}/>${SETA(84, 80, 100, 80)}${SETA(140, 80, 156, 80)}${TXT(60, 84, "folga", "end", "#fecaca")}`],
  "jType:none": ["Sem pino", "Só o encaixe no formato do corte (se estiver ligado) ou só colar. Bom pra peça pequena.", PEGADA("")],
  "jType:round": ["Pino redondo", "Um ou mais pinos redondos alinham as peças. O furo fica na outra peça, com a folga.", PEGADA(circ(85, 60, 13) + circ(155, 60, 13))],
  "jType:square": ["Pino quadrado", "Como o redondo, mas não deixa a peça girar mesmo com um pino só.", PEGADA(quad(85, 60, 12) + quad(155, 60, 12))],
  "jType:hex": ["Pino sextavado", "Trava o giro e é fácil de imprimir em pé.", PEGADA(hexa(85, 60, 14) + hexa(155, 60, 14))],
  "jType:cone": ["Pino cônico", "Pino que afina na ponta: entra fácil e se centraliza sozinho.",
    `<rect x="20" y="14" width="200" height="40" ${CIMA}/><path d="M100 54 H140 L130 100 H110 Z" ${CIMA}/><rect x="20" y="70" width="200" height="42" fill="#3b4254" fill-opacity=".6" stroke="#6b7488"/>`],
  "jType:center": ["Pino central", "Um pino grande no meio do corte, como nos kits de designer: alinha e ainda deixa girar pra posar (ombro, pescoço, cintura).", PEGADA(circ(120, 60, 24))],
  jCount: ["Quantidade de pinos", "Automático coloca 2 (ou 3 em corte grande). Um pino só deixa a peça girar; dois já travam.",
    PEGADA(circ(70, 60, 10) + circ(120, 45, 10) + circ(170, 72, 10)) + TXT(120, 116, "ex.: 3 pinos", "middle")],
  jD: ["Diâmetro do pino", "Largura do pino. Em branco o programa escolhe pelo tamanho do corte.",
    `<rect x="20" y="14" width="200" height="40" ${CIMA}/><rect x="98" y="54" width="44" height="48" ${CIMA}/>${SETA(98, 110, 142, 110)}${TXT(150, 114, "diâmetro", "start", "#fecaca")}`],
  jL: ["Profundidade do pino", "Quanto o pino entra na outra peça. Mais fundo segura melhor, mas precisa de espaço dentro dela.",
    `<rect x="20" y="14" width="200" height="40" ${CIMA}/><rect x="98" y="54" width="44" height="48" ${CIMA}/>${SETA(152, 54, 152, 102)}${TXT(158, 82, "profundidade", "start", "#fecaca")}`],
  jLoose: ["Pino solto", "O pino é impresso à parte (arquivo Pinos.stl) e as duas peças ganham furo. Bom quando o pino fixo quebraria ou atrapalharia a impressão.",
    `<rect x="20" y="14" width="90" height="40" ${CIMA}/><rect x="52" y="30" width="26" height="24" ${FURO}/><rect x="20" y="70" width="90" height="42" ${BAIXO}/><rect x="52" y="70" width="26" height="26" ${FURO}/>
     <rect x="160" y="28" width="26" height="70" rx="4" fill="#22c55e" stroke="#15803d"/>${TXT(173, 116, "pino solto", "middle")}`],
  lado: ["Em qual peça fica o rebaixo", "O buraco (rebaixo) vai numa das duas peças e o ressalto/pino na outra. Automático põe o buraco na peça maior (a base, o corpo).",
    ENCAIXE() + TXT(226, 104, "buraco aqui", "end")],
  pinosCorte: ["Pinos neste corte", "Muda só este corte: sem pino (só o encaixe), 1, 2 ou 3 pinos, rabo de andorinha (corte reto e largo) ou só colar. Mudar isso refaz só os encaixes, é rápido.",
    PEGADA(circ(120, 60, 12)) + TXT(120, 116, "só este corte", "middle")],
  "jType:magnet": ["Ímã", "Abre um furo do tamanho do ímã de neodímio nas duas peças, um de frente pro outro. Cole os ímãs (conferindo a polaridade) e a peça encaixa e destaca quando quiser.",
    `<rect x="20" y="14" width="200" height="44" ${CIMA}/><rect x="98" y="34" width="44" height="24" ${FURO}/><rect x="101" y="37" width="38" height="20" rx="3" fill="#c3cad6"/>
     <rect x="20" y="64" width="200" height="46" ${BAIXO}/><rect x="98" y="64" width="44" height="24" ${FURO}/><rect x="101" y="65" width="38" height="20" rx="3" fill="#c3cad6"/>
     ${TXT(120, 51, "N", "middle", "#ef4444")}${TXT(120, 79, "S", "middle", "#3b82f6")}`],
  jMag: ["Tamanho do ímã", "Diâmetro × altura do ímã redondo que você tem. O furo sai com a folga a mais, pra colar sem forçar. Use o Teste de folga pra acertar.",
    `<rect x="70" y="40" width="100" height="40" rx="6" fill="#c3cad6" stroke="#8b93a3"/>${SETA(70, 96, 170, 96)}${TXT(120, 112, "diâmetro", "middle", "#fecaca")}${SETA(184, 40, 184, 80)}${TXT(190, 64, "altura", "start", "#fecaca")}`],
  jLabel: ["Número do corte", "Grava o número do corte nas duas faces que se encontram, dentro do encaixe: na hora de colar você sabe o que vai com o quê, e depois de montado não aparece.",
    `<rect x="20" y="20" width="200" height="80" rx="20" ${BAIXO}/><text x="120" y="76" font-size="44" font-weight="700" fill="#12151b" text-anchor="middle" font-family="monospace">3</text>${TXT(120, 114, "corte nº 3, nas duas peças", "middle")}`],
  calib: ["Teste de folga", "Gera uma régua com 6 furos de folgas diferentes (0,05 a 0,30 mm, número gravado do lado) e uma chave com o seu pino. Imprima, teste e use a folga do furo que encaixou melhor.",
    `<rect x="20" y="30" width="200" height="50" rx="4" ${BAIXO}/>${[0, 1, 2, 3, 4, 5].map((k) => `<circle cx="${40 + k * 32}" cy="48" r="${7 + k * 0.6}" ${FURO}/>${TXT(40 + k * 32, 74, String(5 + k * 5), "middle")}`).join("")}
     <rect x="90" y="92" width="60" height="16" rx="3" ${CIMA}/>`],
  jPadrao: ["Salvar como padrão", "Os ajustes de encaixe de agora (folga, pino, rebaixo, ímã) passam a ser o ponto de partida dos projetos novos.", PEGADA(circ(120, 60, 14))],
  rabo: ["Rabo de andorinha", "Uma lingueta em trapézio atravessa o corte e entra deslizando por uma ponta: não sai puxando. Precisa de corte reto e largo, como os do Dividir pela mesa.",
    `<path d="M20 14 H220 V54 H150 L162 78 H78 L90 54 H20 Z" ${CIMA}/><path d="M20 60 H86 L74 84 H166 L154 60 H220 V112 H20 Z" ${BAIXO}/>`],
  mesaSel: ["Dividir pela mesa", "Escolha a impressora: se o modelo não couber, ele é cortado reto em partes que cabem, com rabo de andorinha onde der.",
    `<rect x="20" y="88" width="200" height="20" fill="#232833" stroke="#7b879e"/><rect x="90" y="10" width="60" height="78" ${CIMA}/><line x1="80" y1="36" x2="160" y2="36" stroke="#ef4444" stroke-dasharray="4 3" stroke-width="2"/><line x1="80" y1="62" x2="160" y2="62" stroke="#ef4444" stroke-dasharray="4 3" stroke-width="2"/>`],
  minarea: ["Corte pequeno só cola", "Corte com área menor que isso não ganha encaixe nem pino: é pequeno demais, fica só colado.",
    PEGADA(`<rect x="100" y="52" width="16" height="12" rx="3" fill="#ef4444"/>`) + TXT(120, 116, "pequeno demais: cola", "middle")],
  autoSmooth: ["Suavização automática", "Alisa a linha do corte na superfície, pra ela não sair serrilhada seguindo os triângulos.",
    `<path d="M15 60 L30 50 L42 64 L58 48 L70 66 L86 50 L100 62" fill="none" stroke="#f2c12e" stroke-width="3"/>${TXT(58, 90, "0 mm: serrilhado", "middle")}
     <path d="M135 58 C160 50 180 66 225 56" fill="none" stroke="#f2c12e" stroke-width="3"/>${TXT(180, 90, "suavizado", "middle")}`],
  anchor: ["Forçar o fundo", "A faixa mais baixa do modelo sempre fica na última peça (a base). Evita que um pé comprido 'roube' o fundo.",
    `<path d="M95 10 H145 V80 H95 Z" ${CIMA}/><rect x="40" y="80" width="160" height="30" ${BAIXO}/><rect x="40" y="100" width="160" height="10" fill="#ef4444" fill-opacity=".7"/>${TXT(120, 118, "fundo fica na base", "middle")}`],
};

const box = document.createElement("div");
box.style.cssText = "position:fixed;z-index:60;width:270px;padding:10px 12px 12px;border-radius:12px;background:rgba(20,24,33,.97);border:1px solid rgba(255,255,255,.14);box-shadow:0 14px 36px rgba(0,0,0,.55);pointer-events:none;display:none;color:#eceef2;font:12px system-ui,'Segoe UI',sans-serif";
document.body.appendChild(box);
function chave(el) {
  if (!el || !el.closest) return null;
  const aj = el.closest("[data-ajuda]"); if (aj) return aj.dataset.ajuda;
  const bt = el.closest("#jType button"); if (bt) return "jType:" + bt.dataset.t;
  const b2 = el.closest("button[id]"); if (b2 && AJUDA[b2.id]) return b2.id;
  const lb = el.closest("label"); if (!lb) return null;
  const inp = lb.querySelector("input,select"); return inp && AJUDA[inp.id] ? inp.id : null;
}
let atual = null, tempo = null;
document.addEventListener("mouseover", (e) => {
  const k = chave(e.target);
  if (k === atual) return;
  atual = k; clearTimeout(tempo); box.style.display = "none";
  if (!k || !AJUDA[k]) return;
  const alvo = e.target.closest("label,button,[data-ajuda],select") || e.target;
  tempo = setTimeout(() => {
    const [t, d, svg] = AJUDA[k];
    box.innerHTML = `<div style="font-weight:600;font-size:13px;margin-bottom:6px">${t}</div>` +
      `<svg viewBox="0 0 240 120" style="width:100%;display:block;background:#0f131b;border:1px solid rgba(255,255,255,.08);border-radius:8px">${DEFS}${svg}</svg>` +
      `<div style="color:#aab4c5;margin-top:7px;line-height:1.45">${d}</div>`;
    box.style.display = "block";
    const r = alvo.getBoundingClientRect(), h = box.offsetHeight;
    const x = r.left - 282 > 8 ? r.left - 282 : Math.min(innerWidth - 280, r.right + 12);
    box.style.left = x + "px"; box.style.top = Math.max(8, Math.min(innerHeight - h - 8, r.top + r.height / 2 - h / 2)) + "px";
  }, 350);
});
document.addEventListener("mousedown", () => { clearTimeout(tempo); box.style.display = "none"; atual = null; });
