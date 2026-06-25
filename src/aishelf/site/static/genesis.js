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

  // 前向声明:Task 4 实现，先给安全空壳避免 click 报错
  let openWorld = function () {};

  renderField();
  initAmbient();

  // 暴露给 Task 4 覆盖
  window.__genesis = { setOpenWorld(fn) { openWorld = fn; }, WORLDS };
})();
