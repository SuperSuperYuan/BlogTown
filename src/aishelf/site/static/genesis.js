(function () {
  "use strict";
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const WORLDS = [
    { id: "thera",     name: "忒拉",       size: 1.2, hue: 28,  depth: 0, x: 38, y: 44 },
    { id: "okeanos",   name: "俄刻阿诺斯", size: 1.0, hue: 200, depth: 1, x: 60, y: 36 },
    { id: "hyperion",  name: "许珀里翁",   size: 1.35,hue: 48,  depth: 0, x: 52, y: 58 },
    { id: "tartaros",  name: "塔尔塔罗斯", size: 0.8, hue: 280, depth: 1, x: 30, y: 62 },
    { id: "aither",    name: "埃忒尔",     size: 0.7, hue: 190, depth: 1, x: 68, y: 56 },
    { id: "nyx",       name: "倪克斯",     size: 0.95,hue: 250, depth: 0, x: 46, y: 30 },
    { id: "hemera",    name: "赫墨拉",     size: 0.85,hue: 40,  depth: 1, x: 64, y: 66 },
    { id: "pontos",    name: "彭托斯",     size: 1.05,hue: 210, depth: 0, x: 56, y: 48 },
    { id: "eos",       name: "厄俄斯",     size: 0.75,hue: 16,  depth: 1, x: 40, y: 56 },
    { id: "selene",    name: "塞勒涅",     size: 0.9, hue: 220, depth: 0, x: 50, y: 40 },
    { id: "helios",    name: "赫利俄斯",   size: 1.25,hue: 36,  depth: 0, x: 62, y: 44 },
    { id: "rhea",      name: "瑞亚",       size: 0.8, hue: 150, depth: 1, x: 34, y: 38 },
    { id: "kronos",    name: "克洛诺斯",   size: 1.1, hue: 268, depth: 0, x: 58, y: 60 },
    { id: "okeanis",   name: "俄刻阿尼斯", size: 0.7, hue: 196, depth: 1, x: 44, y: 64 },
    { id: "phoibe",    name: "福柏",       size: 0.85,hue: 300, depth: 1, x: 48, y: 50 },
    { id: "tethys",    name: "忒提斯",     size: 0.95,hue: 174, depth: 0, x: 54, y: 34 },
  ];

  const field = document.getElementById("gx-field");

  function renderField() {
    field.innerHTML = "";
    WORLDS.forEach((w, i) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "gx-planet gx-depth-" + w.depth;
      b.dataset.id = w.id;
      b.style.cssText =
        "left:" + w.x + "%;top:" + w.y + "%;" +
        "--s:" + w.size + ";--hue:" + w.hue + ";--i:" + i + ";";
      b.innerHTML = '<span class="gx-orb"></span><span class="gx-pname">' + w.name + "</span>";
      b.addEventListener("click", () => openWorld(w));
      field.appendChild(b);
    });
  }

  function initAmbient() {
    if (reduce) return;
    // 流星:每 8–14s 随机一道
    function shoot() {
      const s = document.createElement("div");
      s.className = "gx-meteor";
      s.style.cssText = "top:" + (5 + Math.random() * 40) + "%;left:" + (40 + Math.random() * 55) + "%;";
      document.getElementById("genesis").appendChild(s);
      setTimeout(() => s.remove(), 1400);
      setTimeout(shoot, 8000 + Math.random() * 6000);
    }
    setTimeout(shoot, 3000);
  }

  // ── 状态机 ──────────────────────────────────────────────────
  const PHASES = [
    { god:"卡俄斯 Chaos",        cause:"质料因",     layer:"规则层", q:"世界由什么构成", color:"#b388ff", corner:"gx-tl" },
    { god:"盖亚 Gaia",           cause:"形式因",     layer:"实体层", q:"世界如何成形",   color:"#3ee0b0", corner:"gx-tr" },
    { god:"厄洛斯 Eros",         cause:"动力因",     layer:"关系层", q:"世界为何运转",   color:"#ff6b9d", corner:"gx-bl" },
    { god:"谟涅摩绪涅 Mnemosyne", cause:"目的/意义因", layer:"事件层", q:"世界留下什么",   color:"#ffd166", corner:"gx-br" },
  ];

  const root = document.getElementById("genesis");
  const stage = document.getElementById("gx-stage");
  const inscription = document.getElementById("gx-inscription");
  const pipsEl = document.getElementById("gx-pips");
  const legendEl = document.getElementById("gx-legend");
  const gods = Array.from(document.querySelectorAll(".gx-god"));
  let timers = [];
  let current = null;

  pipsEl.innerHTML = PHASES.map((p,i) => '<span class="gx-pip" data-i="'+i+'" style="--c:'+p.color+'"></span>').join("");
  legendEl.innerHTML = PHASES.map(p => '<span class="gx-leg" style="--c:'+p.color+'"><i></i>'+p.cause+' · '+p.layer+'</span>').join("");
  const pips = Array.from(pipsEl.children);

  function clearTimers(){ timers.forEach(clearTimeout); timers = []; }
  function resetVisuals(){
    stage.className = "gx-stage";
    gods.forEach(g => g.classList.remove("gx-on"));
    pips.forEach(p => p.classList.remove("gx-on"));
    inscription.textContent = "";
    root.removeAttribute("data-tint");
  }

  function flash(){
    if (reduce) return;
    const f = document.createElement("div");
    f.className = "gx-flash";
    stage.appendChild(f);
    setTimeout(() => f.remove(), 360);
  }

  function applyPhase(i){
    stage.classList.add("gx-p" + (i + 1));      // 累积:层渐次显现
    const ph = PHASES[i];
    gods.forEach(g => { if (g.classList.contains(ph.corner)) g.classList.add("gx-on"); });
    pips[i].classList.add("gx-on");
    root.setAttribute("data-tint", i);           // 整屏微泛该色（CSS 处理）
    inscription.textContent = ph.cause + " · " + ph.layer + " ——「" + ph.q + "」";
    flash();
  }

  function finalize(){ stage.classList.add("gx-final"); legendEl.hidden = false; inscription.textContent = current ? current.name : ""; }

  function runFrom(i){
    clearTimers();
    if (i >= PHASES.length){ finalize(); return; }
    applyPhase(i);
    timers.push(setTimeout(() => runFrom(i + 1), 1200));   // 每相位 ~1.2s
  }

  function openWorld(world){
    current = world;
    resetVisuals();
    stage.hidden = false;
    root.classList.add("gx-creating");           // 标题/星球场淡出由 CSS 处理
    if (reduce){ ["gx-p1","gx-p2","gx-p3","gx-p4"].forEach(c=>stage.classList.add(c)); gods.forEach(g=>g.classList.add("gx-on")); pips.forEach(p=>p.classList.add("gx-on")); finalize(); return; }
    requestAnimationFrame(() => runFrom(0));
  }
  function replay(){ clearTimers(); resetVisuals(); if (reduce){ openWorld(current); } else { requestAnimationFrame(() => runFrom(0)); } }
  function skip(){ clearTimers(); resetVisuals(); ["gx-p1","gx-p2","gx-p3","gx-p4"].forEach(c=>stage.classList.add(c)); gods.forEach(g=>g.classList.add("gx-on")); pips.forEach(p=>p.classList.add("gx-on")); finalize(); }
  function closeWorld(){ clearTimers(); resetVisuals(); stage.hidden = true; legendEl.hidden = true; root.classList.remove("gx-creating"); current = null; }

  document.getElementById("gx-replay").addEventListener("click", replay);
  document.getElementById("gx-skip").addEventListener("click", skip);
  document.getElementById("gx-close").addEventListener("click", closeWorld);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !stage.hidden) closeWorld(); });
  stage.addEventListener("click", (e) => { if (e.target === stage) closeWorld(); });  // 点空白关闭
  // ────────────────────────────────────────────────────────────

  renderField();
  initAmbient();

  window.__genesis = { WORLDS, openWorld, PHASES };
})();
