# 创世 / 四因创世（Genesis）页 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增一个零依赖的纯前端「玩法」原型页 `/genesis`——四位原初神（四因说）逐层为星球叠加规则/实体/关系/事件，点击星球回放创世动画。

**Architecture:** 服务端用 FastAPI 渲染一个静态模板 `genesis.html`（无数据查询）；页面本体的样式与逻辑放在 `static/genesis.css` 与 `static/genesis.js`，由模板在内容块里引入；`base.html` 加一个 `{% block head %}` 供注入样式。星球/相位数据硬编码在 JS。视觉验证用无头 Chrome 截图（CSS/动画不写单测，只有路由有冒烟测试）。

**Tech Stack:** Python 3 / FastAPI / Jinja2（已有）；前端纯原生 HTML + CSS + vanilla JS（无库、无构建）；pytest（路由冒烟测试）。

## Global Constraints

- 零前端依赖:不引入 Three.js 或任何 JS 库/构建步骤（spec「非目标」）。
- 不接真实数据、不碰数据库/契约/嵌入:星球与文案硬编码（spec「非目标」）。
- 复用宇宙系列深空视觉语言;底 `#080b16`，正文 `#e6ebf5`，结构金 `#c9a86a`，高光金 `#f0dca0`。
- 四因之色(verbatim):卡俄斯 `#b388ff`、盖亚 `#3ee0b0`、厄洛斯 `#ff6b9d`、谟涅摩绪涅 `#ffd166`。
- 角落映射(verbatim):tl=卡俄斯、tr=盖亚、bl=厄洛斯、br=谟涅摩绪涅;创世顺序 tl→tr→bl→br。
- `prefers-reduced-motion: reduce` 必须处理:关闭漂浮/流星/脉动/逐帧创世，直达成品态。
- 网络/数据测试一律遵循项目惯例;本页只加一个返回 200 的冒烟测试。
- 站点用 `PYTHONPATH=src python -m aishelf.site` 跑在 `127.0.0.1:8001`（截图验证用）。

---

## File Structure

- Create `src/aishelf/site/templates/genesis.html` — 页面标记;在内容块内引入本页 css/js。
- Create `src/aishelf/site/static/genesis.css` — 本页全部样式(场景/四角神/星球/创世动画 keyframes/回纹/reduced-motion)。
- Create `src/aishelf/site/static/genesis.js` — WORLDS/PHASES 数据、星球渲染、漂浮/流星氛围、创世动画状态机、控件与键盘。
- Modify `src/aishelf/site/templates/base.html` — 在 `</head>` 前加 `{% block head %}{% endblock %}`。
- Modify `src/aishelf/site/app.py` — 新增 `GET /genesis` 路由。
- Modify `src/aishelf/site/templates/_topbar.html` — 「玩法」下拉首位加 `创世`。
- Create `tests/unit/test_genesis.py` — `/genesis` 冒烟测试。

---

## Task 1: 脚手架 —— 路由、head block、模板骨架、导航、冒烟测试

**Files:**
- Modify: `src/aishelf/site/templates/base.html`
- Modify: `src/aishelf/site/app.py`（在其它 `@app.get(... HTMLResponse)` 页路由附近，如 `/islands` 之后）
- Modify: `src/aishelf/site/templates/_topbar.html`
- Create: `src/aishelf/site/templates/genesis.html`
- Create: `src/aishelf/site/static/genesis.css`（先放占位:深空底）
- Create: `src/aishelf/site/static/genesis.js`（先放空 IIFE）
- Test: `tests/unit/test_genesis.py`

**Interfaces:**
- Produces: 路由 `GET /genesis` → 200，HTML 含 `class="genesis"`、`创世`、`COSMOGONY`、`卡俄斯`；模板引入 `/static/genesis.css` 与 `/static/genesis.js`；`base.html` 暴露 `{% block head %}`。

- [ ] **Step 1: 写失败测试**

`tests/unit/test_genesis.py`:
```python
from fastapi.testclient import TestClient
from aishelf.site.app import app

client = TestClient(app)


def test_genesis_page_renders():
    r = client.get("/genesis")
    assert r.status_code == 200
    body = r.text
    assert 'class="genesis"' in body
    assert "创世" in body
    assert "COSMOGONY" in body
    assert "卡俄斯" in body  # 四神之一
    assert "/static/genesis.css" in body
    assert "/static/genesis.js" in body
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/unit/test_genesis.py -v`
Expected: FAIL（404 —— 路由不存在）

- [ ] **Step 3: 加 head block 到 base.html**

把 `base.html` 的 `</head>` 前一行改为含 head block（保留两条已有样式链接）:
```html
  <link rel="stylesheet" href="/static/topbar.css" />
  <link rel="stylesheet" href="/static/style.css" />
  {% block head %}{% endblock %}
</head>
```

- [ ] **Step 4: 加路由到 app.py**

在 `/islands` 路由后新增:
```python
@app.get("/genesis", response_class=HTMLResponse)
def genesis(request: Request):
    return templates.TemplateResponse("genesis.html", {"request": request})
```
（与同文件其它页路由一致使用现有 `templates`/`Request` 导入;若该页函数签名惯例不同，照抄同文件相邻 HTMLResponse 路由的签名风格。）

- [ ] **Step 5: 写模板骨架 genesis.html**

```html
{% extends "base.html" %}
{% block title %}创世 · Atlas{% endblock %}
{% block head %}<link rel="stylesheet" href="/static/genesis.css" />{% endblock %}
{% block content %}
<section class="genesis" id="genesis">
  <div class="gx-meander gx-m-tl"></div><div class="gx-meander gx-m-tr"></div>
  <div class="gx-meander gx-m-bl"></div><div class="gx-meander gx-m-br"></div>

  <header class="gx-title">
    <p class="eyebrow">COSMOGONY · 四因创世</p>
    <h1>创世</h1>
  </header>

  <div class="gx-god gx-tl" data-phase="0" aria-label="卡俄斯 Chaos · 质料因 · 规则层"></div>
  <div class="gx-god gx-tr" data-phase="1" aria-label="盖亚 Gaia · 形式因 · 实体层"></div>
  <div class="gx-god gx-bl" data-phase="2" aria-label="厄洛斯 Eros · 动力因 · 关系层"></div>
  <div class="gx-god gx-br" data-phase="3" aria-label="谟涅摩绪涅 Mnemosyne · 目的因 · 事件层"></div>

  <div class="gx-field" id="gx-field"></div>

  <div class="gx-stage" id="gx-stage" data-phase="0" hidden>
    <div class="gx-globe" id="gx-globe">
      <div class="gx-layer gx-layer-rule"></div>
      <div class="gx-layer gx-layer-entity"></div>
      <div class="gx-layer gx-layer-relation"></div>
      <div class="gx-layer gx-layer-history"></div>
    </div>
    <p class="gx-inscription" id="gx-inscription"></p>
    <div class="gx-pips" id="gx-pips"></div>
    <div class="gx-legend" id="gx-legend" hidden></div>
    <div class="gx-controls">
      <button type="button" id="gx-replay">重放</button>
      <button type="button" id="gx-skip">跳过</button>
      <button type="button" id="gx-close" aria-label="关闭">✕</button>
    </div>
  </div>
</section>
<script src="/static/genesis.js"></script>
{% endblock %}
```

- [ ] **Step 6: 占位 css/js**

`static/genesis.css`:
```css
main:has(.genesis) { max-width: none; padding: 0; }
.genesis { position: relative; min-height: calc(100dvh - 56px); background: #080b16; color: #e6ebf5; overflow: hidden; }
.genesis .eyebrow { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; letter-spacing: .28em; color: #c9a86a; margin: 0 0 4px; text-transform: uppercase; }
.genesis h1 { margin: 0; font-size: 30px; font-weight: 800; background: linear-gradient(100deg, #fff 8%, #f0dca0 55%, #c9a86a 92%); -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent; color: transparent; }
.gx-title { position: absolute; top: 18px; left: 0; right: 0; text-align: center; z-index: 5; }
```
`static/genesis.js`:
```js
(function () {
  "use strict";
  // 后续任务填充
})();
```

- [ ] **Step 7: 加导航**

`_topbar.html` 的 `.nav-pop` 内，第一项改为创世（放在图谱前）:
```html
    <div class="nav-pop">
      <a href="/genesis">创世</a>
      <a href="/graph">图谱</a>
```

- [ ] **Step 8: 运行测试确认通过**

Run: `pytest tests/unit/test_genesis.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add src/aishelf/site/templates/base.html src/aishelf/site/app.py src/aishelf/site/templates/_topbar.html src/aishelf/site/templates/genesis.html src/aishelf/site/static/genesis.css src/aishelf/site/static/genesis.js tests/unit/test_genesis.py
git commit -m "feat(site): /genesis 页脚手架（路由+骨架+导航+冒烟测试）"
```

---

## Task 2: 场景外壳 + 四角神（星座线稿 + 标签 + 悬停点亮）

**Files:**
- Modify: `src/aishelf/site/templates/genesis.html`（往四个 `.gx-god` 里填 SVG 星座 + 标签）
- Modify: `src/aishelf/site/static/genesis.css`（场景星尘/暖角晕/四角神样式/hover）

**Interfaces:**
- Consumes: Task 1 的 `.gx-god[data-phase]` 容器与角落 class（gx-tl/tr/bl/br）。
- Produces: 每个 `.gx-god` 内含 `<svg class="gx-constellation">`（星点 `<circle>` + 连线 `<line>`，`stroke`/`fill=currentColor`）与 `.gx-god-label`；CSS 变量 `--c`（因之色）设在各角 god 上，`.gx-god.gx-on` 表示「已点亮」（Task 4 用 JS 添加）。

- [ ] **Step 1: 四角神填充 SVG + 标签**（genesis.html）

每个 `.gx-god` 形如（以卡俄斯为例，其余替换 viewBox 内点集/标签/角 class）:
```html
<div class="gx-god gx-tl" data-phase="0" style="--c:#b388ff" aria-label="卡俄斯 Chaos · 质料因 · 规则层">
  <svg class="gx-constellation" viewBox="0 0 100 100" aria-hidden="true">
    <!-- 混沌:向内螺旋汇聚的散乱星群（8–14 点 + 连线，示意即可） -->
    <polyline class="gx-cl-line" points="12,18 30,10 46,26 28,40 50,52 70,38 62,60 84,72"/>
    <g class="gx-cl-stars">
      <circle cx="12" cy="18" r="1.6"/><circle cx="30" cy="10" r="2"/><circle cx="46" cy="26" r="1.4"/>
      <circle cx="28" cy="40" r="1.8"/><circle cx="50" cy="52" r="2.2"/><circle cx="70" cy="38" r="1.5"/>
      <circle cx="62" cy="60" r="1.7"/><circle cx="84" cy="72" r="2"/>
    </g>
  </svg>
  <div class="gx-god-label"><b>卡俄斯 Chaos</b><span>质料因 · 规则层</span></div>
</div>
```
- tr=盖亚 `--c:#3ee0b0`「形式因 · 实体层」（点集走环抱母体/山-球轮廓:稳定三角+弧）。
- bl=厄洛斯 `--c:#ff6b9d`「动力因 · 关系层」（展翼/交缠双弧:对称 V + 两道弧）。
- br=谟涅摩绪涅 `--c:#ffd166`「目的/意义因 · 事件层」（单臂螺旋）。
各角点集随意手撒，符合意象即可（无须写实）。

- [ ] **Step 2: 写场景 + 四角神样式**（genesis.css 追加）

要点（按 spec 视觉直觉写具体值）:
```css
/* 星尘:复用宇宙系列做法的一层固定星点（呼吸闪烁），reduced-motion 下静止 */
.genesis::before { content:""; position:absolute; inset:0; z-index:0; pointer-events:none;
  background-image: /* ~12 个 radial-gradient 星点，参照 style.css 宇宙系列 */ ; animation: gx-stars 7s ease-in-out infinite; }
@keyframes gx-stars { 0%,100%{opacity:.55} 50%{opacity:.95} }
/* 四角暖晕:各角一团极淡因之色 */
.gx-god { position:absolute; width:230px; z-index:4; color:var(--c); }
.gx-tl{top:64px;left:26px} .gx-tr{top:64px;right:26px;text-align:right}
.gx-bl{bottom:46px;left:26px} .gx-br{bottom:46px;right:26px;text-align:right}
.gx-constellation{ width:140px; height:140px; opacity:.45; filter:drop-shadow(0 0 5px var(--c)); transition:opacity .25s, filter .25s; }
.gx-constellation .gx-cl-stars circle{ fill:var(--c); }
.gx-constellation .gx-cl-line{ fill:none; stroke:var(--c); stroke-width:.7; opacity:.5; }
.gx-god-label b{ display:block; color:#e6ebf5; font-size:13px; }
.gx-god-label span{ font-family:ui-monospace,Menlo,monospace; font-size:11px; letter-spacing:.06em; color:var(--c); }
/* hover 或 已点亮 → 整幅亮起 */
.gx-god:hover .gx-constellation, .gx-god.gx-on .gx-constellation{ opacity:1; filter:drop-shadow(0 0 12px var(--c)); }
@media (prefers-reduced-motion: reduce){ .genesis::before{ animation:none } }
```
（星尘 `background-image` 直接复用 `style.css` 宇宙系列里的那组 radial-gradient 星点值。）

- [ ] **Step 3: 截图验证 rest 态四角**

Run（站点已在 8001 跑;否则 `PYTHONPATH=src python -m aishelf.site &`）:
```bash
SC=/private/tmp/.../scratchpad
"$CHROME" --headless --disable-gpu --hide-scrollbars --force-device-scale-factor=2 --window-size=1400,900 --screenshot="$SC/genesis_rest.png" "http://127.0.0.1:8001/genesis"
```
Expected: 深空底;四角各一幅对应色的星座 + 神名/因/层标签;顶部居中金渐变「创世」+ 眉标。读图确认四角颜色 = 紫/青绿/玫红/金且位置 tl/tr/bl/br 正确。

- [ ] **Step 4: Commit**

```bash
git add src/aishelf/site/templates/genesis.html src/aishelf/site/static/genesis.css
git commit -m "feat(site): /genesis 场景外壳 + 四角星座神"
```

---

## Task 3: 中央星球场 + Rest 氛围（数据、渲染、漂浮、流星）

**Files:**
- Modify: `src/aishelf/site/static/genesis.js`（WORLDS 数据 + renderField + initAmbient）
- Modify: `src/aishelf/site/static/genesis.css`（星球样式 + 漂浮/流星 keyframes）

**Interfaces:**
- Consumes: Task 1 的 `#gx-field`。
- Produces: 全局（IIFE 内）`WORLDS`（数组，元素 `{id:string, name:string, size:number/*0.6–1.4*/, hue:number/*0–360*/, depth:0|1, x:number/*%*/, y:number/*%*/}`）；`renderField()` 把每颗星球渲染为 `<button class="gx-planet" data-id>` 注入 `#gx-field`，点击调用 `openWorld(world)`（Task 4 定义，本任务先留 `window.__openWorld` 钩子或前向声明）；`initAmbient()` 启动漂浮/流星（reduced-motion 下不启动）。

- [ ] **Step 1: 写 WORLDS 数据 + 渲染**（genesis.js，替换占位 IIFE 体）

```js
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
```
> 说明:`Math.random()` 在站点前端可用（plan 注意事项里禁的是 workflow 脚本环境，浏览器 JS 不受限）。

- [ ] **Step 2: 星球 + 氛围样式**（genesis.css 追加）

```css
.gx-field{ position:absolute; inset:0; z-index:2; }
.gx-planet{ position:absolute; transform:translate(-50%,-50%); border:none; background:none; cursor:pointer; padding:0;
  width:calc(46px * var(--s)); height:calc(46px * var(--s)); }
.gx-orb{ display:block; width:100%; height:100%; border-radius:50%;
  background: radial-gradient(circle at 32% 30%, hsl(var(--hue) 90% 80%), hsl(var(--hue) 70% 50%) 55%, hsl(var(--hue) 60% 22%) 100%);
  box-shadow: 0 0 16px -2px hsl(var(--hue) 80% 60% / .7); transition: transform .2s, box-shadow .2s; }
.gx-pname{ position:absolute; left:50%; top:108%; transform:translateX(-50%); white-space:nowrap;
  font-size:12px; color:#cdd9f2; opacity:0; transition:opacity .18s; pointer-events:none; }
.gx-planet:hover .gx-orb, .gx-planet:focus-visible .gx-orb{ transform:scale(1.12); box-shadow:0 0 26px 0 hsl(var(--hue) 85% 65% / .85); }
.gx-planet:hover .gx-pname, .gx-planet:focus-visible .gx-pname{ opacity:1; }
/* 视差漂浮:前景快、后景慢 */
.gx-depth-0{ animation: gx-drift-a calc(16s + var(--i) * 1s) ease-in-out infinite alternate; }
.gx-depth-1{ animation: gx-drift-b calc(26s + var(--i) * 1s) ease-in-out infinite alternate; opacity:.8; filter:saturate(.85); }
@keyframes gx-drift-a{ from{margin:0 0} to{margin:-14px 10px} }
@keyframes gx-drift-b{ from{margin:0 0} to{margin:10px -8px} }
/* 流星 */
.gx-meteor{ position:absolute; width:120px; height:2px; z-index:1; pointer-events:none;
  background:linear-gradient(90deg, transparent, #fff); transform:rotate(18deg); opacity:0;
  animation: gx-shoot 1.3s ease-out forwards; }
@keyframes gx-shoot{ 0%{opacity:0;transform:translate(0,0) rotate(18deg)} 12%{opacity:.9} 100%{opacity:0; transform:translate(-320px,120px) rotate(18deg)} }
@media (prefers-reduced-motion: reduce){ .gx-depth-0,.gx-depth-1{ animation:none } }
```

- [ ] **Step 3: 截图验证星球场**

Run: 截图 `/genesis` → `genesis_field.png`。
Expected: 中央约 16 颗发光星球，大小/色相各异、分两层深度；hover 单颗（截图看不到 hover，至少确认静态布局合理、不溢出、不挡四角神）。

- [ ] **Step 4: Commit**

```bash
git add src/aishelf/site/static/genesis.js src/aishelf/site/static/genesis.css
git commit -m "feat(site): /genesis 中央星球场 + 漂浮/流星氛围"
```

---

## Task 4: 创世动画（高潮）—— 状态机 + 分层星球 + 铭文 + 控件 + 键盘 + reduced-motion

**Files:**
- Modify: `src/aishelf/site/static/genesis.js`（PHASES + openWorld/setPhase/closeWorld/replay/skip + 键盘）
- Modify: `src/aishelf/site/static/genesis.css`（stage/globe 四层/inscription/pips/legend/controls + 各层进入 keyframes）

**Interfaces:**
- Consumes: Task 1 的 `#gx-stage`/`#gx-globe`/`.gx-layer-*`/`#gx-inscription`/`#gx-pips`/`#gx-legend`/`#gx-replay`/`#gx-skip`/`#gx-close`、四个 `.gx-god[data-phase]`；Task 3 的 `WORLDS`、`window.__genesis.setOpenWorld`。
- Produces: `openWorld(world)` 显示 stage 并按相位推进；累积 class `.gx-p1..gx-p4` 控制四层渐次显现，`.gx-final` 成品态；JS 给对应 `.gx-god` 加 `gx-on`；`closeWorld()` 复位。

- [ ] **Step 1: 写状态机**（genesis.js —— 在 IIFE 内、`window.__genesis` 之前替换前向声明那段）

```js
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

  function applyPhase(i){
    stage.classList.add("gx-p" + (i + 1));      // 累积:层渐次显现
    const ph = PHASES[i];
    gods.forEach(g => { if (g.classList.contains(ph.corner)) g.classList.add("gx-on"); });
    pips[i].classList.add("gx-on");
    root.setAttribute("data-tint", i);           // 整屏微泛该色（CSS 处理）
    inscription.textContent = ph.cause + " · " + ph.layer + " ——「" + ph.q + "」";
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
  function replay(){ resetVisuals(); if (reduce){ openWorld(current); } else { requestAnimationFrame(() => runFrom(0)); } }
  function skip(){ clearTimers(); resetVisuals(); ["gx-p1","gx-p2","gx-p3","gx-p4"].forEach(c=>stage.classList.add(c)); gods.forEach(g=>g.classList.add("gx-on")); pips.forEach(p=>p.classList.add("gx-on")); finalize(); }
  function closeWorld(){ clearTimers(); resetVisuals(); stage.hidden = true; legendEl.hidden = true; root.classList.remove("gx-creating"); current = null; }

  document.getElementById("gx-replay").addEventListener("click", replay);
  document.getElementById("gx-skip").addEventListener("click", skip);
  document.getElementById("gx-close").addEventListener("click", closeWorld);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !stage.hidden) closeWorld(); });
  stage.addEventListener("click", (e) => { if (e.target === stage) closeWorld(); });  // 点空白关闭
```
然后把文件末尾的 `window.__genesis = {...}` 改为也接好 openWorld（不再用 setOpenWorld 钩子）:
```js
  window.__genesis = { WORLDS, openWorld, PHASES };
```
并删除 Task 3 里那行 `let openWorld = function(){}` 前向声明（现在 openWorld 是真正的函数声明，提升可用）。

> 注:`openWorld` 用 `function` 声明（hoisted），Task 3 的 `renderField` 里 `() => openWorld(w)` 能正确引用。确保 PHASES/状态机这段在 `renderField()` 调用之前或同一作用域（函数声明提升保证可用）。

- [ ] **Step 2: 给星球聚焦/回车支持**（genesis.js，renderField 内已是 `<button>`，补键盘触发）

`<button>` 原生支持 Enter/Space 触发 click，无需额外代码。确认 `.gx-planet` 是 `<button>` 即可（Task 3 已是）。

- [ ] **Step 3: 写 stage/globe/四层/铭文/控件样式**（genesis.css 追加）

```css
.gx-stage{ position:absolute; inset:0; z-index:8; display:flex; flex-direction:column;
  align-items:center; justify-content:center; background:radial-gradient(60% 60% at 50% 45%, rgba(8,11,22,.55), rgba(8,11,22,.92)); }
.gx-stage[hidden]{ display:none; }
/* 标题/星球场在创世时淡出退后 */
.gx-creating .gx-title{ opacity:0; transform:translateY(-10px); transition:.5s; }
.gx-creating .gx-field{ opacity:.12; filter:blur(2px); transition:.6s; pointer-events:none; }
/* 球与四层 */
.gx-globe{ position:relative; width:300px; height:300px; border-radius:50%; }
.gx-layer{ position:absolute; inset:0; border-radius:50%; opacity:0; transition:opacity .6s; }
.gx-layer-rule{ background:
  repeating-linear-gradient(0deg, transparent 0 14px, rgba(179,136,255,.5) 14px 15px),
  repeating-linear-gradient(90deg, transparent 0 14px, rgba(179,136,255,.5) 14px 15px);
  -webkit-mask:radial-gradient(circle, #000 99%, transparent 100%); mask:radial-gradient(circle, #000 99%, transparent 100%);
  box-shadow:inset 0 0 30px rgba(179,136,255,.5); }
.gx-layer-entity{ background:radial-gradient(circle at 50% 50%, rgba(62,224,176,.18), transparent 70%);
  box-shadow:inset 0 0 0 1px rgba(62,224,176,.4); }
.gx-layer-entity::before{ content:""; position:absolute; inset:0; border-radius:50%;
  background-image:radial-gradient(2px 2px at 30% 40%, #3ee0b0, transparent), radial-gradient(2px 2px at 64% 30%, #3ee0b0, transparent), radial-gradient(2px 2px at 50% 66%, #3ee0b0, transparent), radial-gradient(2px 2px at 40% 60%, #3ee0b0, transparent), radial-gradient(2px 2px at 70% 58%, #3ee0b0, transparent); }
.gx-layer-relation{ background:conic-gradient(from 0deg, transparent, rgba(255,107,157,.25), transparent 40%);
  box-shadow:inset 0 0 24px rgba(255,107,157,.4); }
.gx-layer-history{ box-shadow:0 0 0 2px rgba(255,209,102,.5), 0 0 26px rgba(255,209,102,.5);
  background:conic-gradient(rgba(255,209,102,.0) 0 70%, rgba(255,209,102,.35) 78%, rgba(255,209,102,0) 86%); }
/* 累积显现 + 关系层旋转 */
.gx-stage.gx-p1 .gx-layer-rule{ opacity:1; }
.gx-stage.gx-p2 .gx-layer-entity{ opacity:1; }
.gx-stage.gx-p3 .gx-layer-relation{ opacity:1; animation:gx-spin 8s linear infinite; }
.gx-stage.gx-p4 .gx-layer-history{ opacity:1; animation:gx-spin 22s linear infinite reverse; }
@keyframes gx-spin{ to{ transform:rotate(360deg) } }
/* 铭文 */
.gx-inscription{ margin-top:30px; min-height:1.4em; color:#f0dca0; letter-spacing:.14em; font-size:15px;
  border-bottom:1px solid rgba(201,168,106,.4); padding-bottom:8px; }
/* 进度点 */
.gx-pips{ display:flex; gap:10px; margin-top:18px; }
.gx-pip{ width:9px; height:9px; border-radius:50%; border:1px solid var(--c); opacity:.4; transition:.3s; }
.gx-pip.gx-on{ background:var(--c); opacity:1; box-shadow:0 0 10px var(--c); }
/* 图例 + 控件 */
.gx-legend{ display:flex; gap:14px; margin-top:16px; font-size:12px; color:#9aa5bf; }
.gx-leg i{ display:inline-block; width:9px; height:9px; border-radius:50%; background:var(--c); margin-right:5px; box-shadow:0 0 8px var(--c); }
.gx-controls{ position:absolute; right:22px; bottom:22px; display:flex; gap:10px; }
.gx-controls button{ background:rgba(122,160,255,.08); border:1px solid rgba(201,168,106,.4); color:#e6ebf5;
  border-radius:9px; padding:.4rem .9rem; cursor:pointer; font:inherit; }
.gx-controls button:hover{ border-color:#c9a86a; }
/* 整屏相位泛色 */
.genesis[data-tint="0"] .gx-stage{ box-shadow:inset 0 0 220px rgba(179,136,255,.18); }
.genesis[data-tint="1"] .gx-stage{ box-shadow:inset 0 0 220px rgba(62,224,176,.16); }
.genesis[data-tint="2"] .gx-stage{ box-shadow:inset 0 0 220px rgba(255,107,157,.16); }
.genesis[data-tint="3"] .gx-stage{ box-shadow:inset 0 0 220px rgba(255,209,102,.16); }
@media (prefers-reduced-motion: reduce){ .gx-layer{ transition:none } .gx-stage.gx-p3 .gx-layer-relation,.gx-stage.gx-p4 .gx-layer-history{ animation:none } }
```

- [ ] **Step 4: 截图验证创世各相位**

注入相位 class 后截图（用一个临时本地 HTML 引线上 css/js，或直接在浏览器 devtools 手动加 class；headless 可加一个查询参数驱动 —— 但本期最简:写一段临时脚本给 stage 依次加 `gx-p1..gx-p4 gx-final` 并截图）。
Run（示例:用 Chrome 加载 `/genesis` 后 evaluate 注入；若不便，至少截 `skip()` 成品态）:
```bash
"$CHROME" --headless --disable-gpu --window-size=1400,900 --virtual-time-budget=2000 --screenshot="$SC/genesis_final.png" \
  "http://127.0.0.1:8001/genesis"
```
Expected:点击某星球后（或注入 class 后）——四角对应神依次点亮、中央球逐层叠出线框/实体点/玫红关系/金色历史环、底部四点进度走满、铭文显示对应「因·层·问」、成品态显示世界名 + 四色图例。读图确认四层颜色与四因色一致、关系/历史层在转。

- [ ] **Step 5: 运行全部单测确保未回归**

Run: `pytest tests/unit/test_genesis.py -v`
Expected: PASS（路由仍 200）。

- [ ] **Step 6: Commit**

```bash
git add src/aishelf/site/static/genesis.js src/aishelf/site/static/genesis.css
git commit -m "feat(site): /genesis 创世动画（四相位状态机 + 分层星球 + 控件）"
```

---

## Task 5: 「酷」强化层 + 收尾（金色回纹 meander + 过场闪光 + 聚光 + reduced-motion 全量核验）

**Files:**
- Modify: `src/aishelf/site/static/genesis.css`（meander 回纹、相位过场闪光、入场聚光 vignette）
- Modify: `src/aishelf/site/static/genesis.js`（相位切换时触发一次金/白闪光元素）

**Interfaces:**
- Consumes: Task 1 的 `.gx-meander.gx-m-*` 四角元素；Task 4 的 `applyPhase`。
- Produces: 四角金色回纹（rest 静默、创世时一缕流光）；`applyPhase` 末尾插入 `flash()` 过场。

- [ ] **Step 1: 回纹 meander 四角**（genesis.css 追加）

用渐变/边框拼出希腊钥匙纹的 L 形角饰（纯 CSS，描金）:
```css
.gx-meander{ position:absolute; width:120px; height:120px; z-index:6; pointer-events:none; opacity:.5;
  background:
    linear-gradient(#c9a86a,#c9a86a) left top/100% 2px no-repeat,
    linear-gradient(#c9a86a,#c9a86a) left top/2px 100% no-repeat,
    linear-gradient(#c9a86a,#c9a86a) 14px 14px/60px 2px no-repeat,
    linear-gradient(#c9a86a,#c9a86a) 14px 14px/2px 40px no-repeat,
    linear-gradient(#c9a86a,#c9a86a) 14px 52px/40px 2px no-repeat; }
.gx-m-tl{ top:14px; left:14px; }
.gx-m-tr{ top:14px; right:14px; transform:scaleX(-1); }
.gx-m-bl{ bottom:14px; left:14px; transform:scaleY(-1); }
.gx-m-br{ bottom:14px; right:14px; transform:scale(-1,-1); }
/* 创世时回纹流光 */
.gx-creating .gx-meander{ opacity:.9; animation:gx-meander-glow 2.4s ease-in-out infinite; }
@keyframes gx-meander-glow{ 0%,100%{ filter:drop-shadow(0 0 0 transparent) } 50%{ filter:drop-shadow(0 0 6px #f0dca0) } }
@media (prefers-reduced-motion: reduce){ .gx-creating .gx-meander{ animation:none } }
```

- [ ] **Step 2: 过场闪光**（genesis.js —— `applyPhase` 末尾加 `flash()`，并实现）

```js
  function flash(){
    if (reduce) return;
    const f = document.createElement("div");
    f.className = "gx-flash";
    stage.appendChild(f);
    setTimeout(() => f.remove(), 360);
  }
```
在 `applyPhase(i)` 末尾调用 `flash();`。

- [ ] **Step 3: 闪光 + 入场聚光样式**（genesis.css 追加）

```css
.gx-flash{ position:absolute; inset:0; pointer-events:none; background:radial-gradient(circle at 50% 45%, rgba(255,255,255,.5), transparent 45%); animation:gx-flash .36s ease-out forwards; }
@keyframes gx-flash{ 0%{opacity:0} 25%{opacity:1} 100%{opacity:0} }
/* 入场聚光:stage 出现时四周压暗（已在 .gx-stage 背景的 radial 里，强化一点 vignette） */
.gx-stage::after{ content:""; position:absolute; inset:0; pointer-events:none; box-shadow:inset 0 0 200px 40px rgba(0,0,0,.6); }
@media (prefers-reduced-motion: reduce){ .gx-flash{ display:none } }
```

- [ ] **Step 4: reduced-motion 全量核验**

Run（模拟 reduce）:
```bash
"$CHROME" --headless --disable-gpu --window-size=1400,900 --force-prefers-reduced-motion \
  --screenshot="$SC/genesis_reduce.png" "http://127.0.0.1:8001/genesis"
```
（若该 flag 不被支持，则在 DevTools/emulation 下核验。）
Expected: 无漂浮/流星/脉动;点击星球后直接呈现成品态(四层静态共显 + 图例 + 世界名)，无逐帧、无闪光。

- [ ] **Step 5: 终检截图（rest + 创世 + 成品）**

Run: 重截 `genesis_rest.png` / 触发创世截 `genesis_creating.png` / 成品 `genesis_final.png`，逐张读图确认:四角神色正确、回纹描金到位、创世四相位叠层与泛色对、铭文/进度/图例/控件齐全、不溢出不挡。

- [ ] **Step 6: 运行全部单测**

Run: `pytest -q`
Expected: PASS（无回归）。

- [ ] **Step 7: Commit**

```bash
git add src/aishelf/site/static/genesis.css src/aishelf/site/static/genesis.js
git commit -m "feat(site): /genesis 酷化层（金色回纹 + 过场闪光 + 聚光）+ 收尾"
```

---

## Self-Review

**Spec coverage:**
- 页面身份/路由/导航/全宽 → Task 1。✅
- 配色(深空×金、四因色) → Global Constraints + Task 2/4。✅
- 布局/标题/四角神(星座线稿+hover+光束) → Task 2。✅ （光束:hover 时四角增亮已含;独立"射向中央光束"作为 hover 装饰在 Task 2 CSS 的 drop-shadow/暖晕里体现，足够示意。）
- 中央星球场 + rest 氛围(漂浮/流星/视差) → Task 3。✅
- 创世动画四相位(逐层叠、铭文、进度、控件、键盘、成品态) → Task 4。✅
- 酷化层(回纹 meander、过场闪光、聚光、相位泛色) → Task 4(泛色) + Task 5(回纹/闪光/聚光)。✅
- reduced-motion → Task 2/3/4/5 均含，Task 5 全量核验。✅
- 数据形态(WORLDS/PHASES) → Task 3/4，与 spec 字段一致。✅
- 测试(冒烟 200) → Task 1；视觉截图 → Task 2/3/4/5。✅
- 无障碍(planet 可聚焦/Enter、Esc 关闭、god aria-label) → Task 1(aria) + Task 3(button) + Task 4(Esc)。✅

**Placeholder scan:** 无 TBD/TODO;每个改代码的步骤都给了完整代码。星座点集明确为"手撒示意"，属创作自由度而非占位，已说明每角意象。

**Type consistency:** `openWorld(world)` 在 Task 3 被 `renderField` 引用、Task 4 用 `function` 声明实现(hoisted，同一 IIFE 作用域);Task 3 的 `setOpenWorld` 钩子在 Task 4 Step 1 明确移除并直接用函数声明。`WORLDS` 字段 `{id,name,size,hue,depth,x,y}` 全程一致。stage 累积 class `gx-p1..gx-p4`/`gx-final`、god `gx-on`、`data-tint` 在 Task 4 定义、Task 5 复用，一致。

> 边界说明:本计划对纯样式部分给出的是具体可用的选择器+取值+行为(而非逐像素强约束)，结构性契约(数据形状、函数名、DOM id/class、相位时序)则完整锁定——这是创意前端原型的恰当颗粒度。
