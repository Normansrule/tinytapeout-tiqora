/* views.js — "Inside a gate": one design, five linked views.

   RTL source, the sky130 gates synthesis made from it, one gate as
   transistors, the same gate's layout, and the state machines. Everything
   drawn comes from docs/site/data/views.json (docs/tools/views_build.py);
   nothing here invents a number. Every clickable thing is a "viewing
   point": choosing one updates every view that can show it, and the
   address bar (#m=..&g=..&c=..) so a view can be linked.

   The transistor view's truth table is computed here, in the browser, by
   the same switch-level rules docs/tools/views_switch.py uses to check every
   cell against its liberty function; test/views/page_test.js checks the two
   agree on every cell and every input. */
(function () {
  "use strict";
  var el = document.getElementById("data-views");
  if (!el) return;
  var V = JSON.parse(el.textContent);
  var root = document.getElementById("views");
  if (!root) return;
  var SVGNS = "http://www.w3.org/2000/svg";
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ------------------------------------------------------------ helpers
  function $(sel, ctx) { return (ctx || document).querySelector(sel); }
  function h(tag, attrs, kids) {
    var e = document.createElement(tag);
    for (var k in attrs || {}) {
      if (k === "text") e.textContent = attrs[k];
      else if (k === "html") e.innerHTML = attrs[k];
      else if (k.slice(0, 2) === "on") e.addEventListener(k.slice(2), attrs[k]);
      else e.setAttribute(k, attrs[k]);
    }
    (kids || []).forEach(function (c) { if (c != null) e.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return e;
  }
  function s(tag, attrs, kids) {
    var e = document.createElementNS(SVGNS, tag);
    for (var k in attrs || {}) {
      if (k === "text") e.textContent = attrs[k];
      else if (k.slice(0, 2) === "on") e.addEventListener(k.slice(2), attrs[k]);
      else e.setAttribute(k, attrs[k]);
    }
    (kids || []).forEach(function (c) { if (c) e.appendChild(c); });
    return e;
  }
  function clickable(node, label, fn) {
    node.setAttribute("tabindex", "0");
    node.setAttribute("role", "button");
    node.setAttribute("aria-label", label);
    node.addEventListener("click", function (ev) { ev.stopPropagation(); fn(); });
    node.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); fn(); }
    });
    return node;
  }
  function fmt(n) { return Number(n).toLocaleString("en-US"); }
  function short(t) { return t.replace("sky130_fd_sc_hd__", ""); }

  // ------------------------------------------------------------ state
  var sel = { m: null, g: null, c: null, t: null, f: null, st: null, e: null, line: null };
  var simIn = {};           // input pin -> 0/1 for the transistor view
  var finfet = false;

  function go(next, fromHash) {
    for (var k in next) sel[k] = next[k];
    if (!fromHash) writeHash();
    render();
  }
  function writeHash() {
    var parts = [];
    ["m", "g", "c", "t", "f", "st"].forEach(function (k) { if (sel[k] != null) parts.push(k + "=" + encodeURIComponent(sel[k])); });
    var hsh = "#" + parts.join("&");
    if (location.hash !== hsh) history.replaceState(null, "", hsh);
  }
  function readHash() {
    var o = { m: null, g: null, c: null, t: null, f: null, st: null, e: null, line: null };
    location.hash.replace(/^#/, "").split("&").forEach(function (kv) {
      var p = kv.split("="); if (p.length === 2 && p[0] in o) o[p[0]] = decodeURIComponent(p[1]);
    });
    if (o.st != null) o.st = +o.st;
    if (o.m && !V.modules[o.m]) o.m = null;
    if (o.g && !V.groups[o.g]) o.g = null;
    return o;
  }

  // the cell a gate-schematic node stands for: "module/cellname"
  function cellType(m, cn) {
    var g = V.groups, mod = V.modules[m];
    for (var i = 0; i < mod.groups.length; i++) {
      var gr = g[mod.groups[i]];
      for (var j = 0; j < gr.nodes.length; j++) if (gr.nodes[j][1] === "c" && gr.nodes[j][0] === cn) return gr.ctypes[j];
    }
    return null;
  }

  // ------------------------------------------------------------ switch level (same rules as views_switch.py)
  // fets: [name, "p"|"n", gate, drain, source, ...]; fixed: rails and inputs;
  // prev (optional): node values before this step, so a latch keeps its charge
  function settle(fets, fixed, init, prev) {
    var nodes = {}, val = {};
    fets.forEach(function (f) { nodes[f[2]] = 1; nodes[f[3]] = 1; nodes[f[4]] = 1; });
    var names = Object.keys(nodes).sort();
    names.forEach(function (n) { val[n] = (prev && (prev[n] === 0 || prev[n] === 1)) ? prev[n] : init; });
    for (var k in fixed) val[k] = fixed[k];
    function on(f) { var g = val[f[2]]; return (f[1] === "n" && g === 1) || (f[1] === "p" && g === 0); }
    function drivers() {
      var parent = {}, src = {};
      names.forEach(function (n) { if (!(n in fixed)) parent[n] = n; });
      function find(a) { while (parent[a] !== a) { parent[a] = parent[parent[a]]; a = parent[a]; } return a; }
      var touch = [];
      fets.forEach(function (f) {
        if (!on(f)) return;
        var a = f[3], b = f[4];
        if (a in fixed && b in fixed) return;
        if (a in fixed) touch.push([b, val[a]]);
        else if (b in fixed) touch.push([a, val[b]]);
        else { var ra = find(a), rb = find(b); if (ra !== rb) parent[ra] = rb; }
      });
      touch.forEach(function (t) { var r = find(t[0]); (src[r] = src[r] || {})[t[1]] = 1; });
      var out = {};
      Object.keys(parent).forEach(function (n) { out[n] = src[find(n)] || {}; });
      return out;
    }
    for (var it = 0; it < 200; it++) {
      var d = drivers(), nv = {}, changed = false;
      for (k in val) nv[k] = val[k];
      Object.keys(d).forEach(function (n) {
        var v = Object.keys(d[n]);
        if (v.length === 1) { var x = +v[0]; if (nv[n] !== x) { nv[n] = x; changed = true; } }
      });
      val = nv;
      if (!changed) {
        Object.keys(d).forEach(function (n) { if (Object.keys(d[n]).length === 2) val[n] = "C"; });
        return val;
      }
    }
    // a loop that rings when every node moves at once: one node at a time, in name order
    for (it = 0; it < 200; it++) {
      var moved = false;
      names.forEach(function (n) {
        if (n in fixed) return;
        var v = Object.keys(drivers()[n]);
        if (v.length === 1 && val[n] !== +v[0]) { val[n] = +v[0]; moved = true; }
      });
      if (!moved) {
        var dd = drivers();
        Object.keys(dd).forEach(function (n) { if (Object.keys(dd[n]).length === 2) val[n] = "C"; });
        return val;
      }
    }
    names.forEach(function (n) { if (!(n in fixed)) val[n] = "X"; });
    return val;
  }
  // liberty Boolean function, evaluated
  function libEval(expr, env) {
    var e = expr.replace(/\*/g, "&").replace(/\+/g, "|")
      .replace(/([A-Za-z_][A-Za-z0-9_]*)'/g, "(!$1)")
      .replace(/([A-Za-z0-9_)])\s+(?=[A-Za-z_!(])/g, "$1&");
    var toks = e.match(/[A-Za-z_][A-Za-z0-9_]*|[!&|^()]/g) || [], p = 0;
    function prim() {
      var t = toks[p++];
      if (t === "!") return prim() ? 0 : 1;
      if (t === "(") { var v = or(); p++; return v; }
      if (!(t in env)) throw new Error("unknown " + t);
      return env[t];
    }
    function and() { var v = prim(); while (toks[p] === "&") { p++; v = prim() & v; } return v; }
    function xor() { var v = and(); while (toks[p] === "^") { p++; v = and() ^ v; } return v; }
    function or() { var v = xor(); while (toks[p] === "|") { p++; v = xor() | v; } return v; }
    return or();
  }
  window.TQViews = { settle: settle, libEval: libEval, data: V };   // for test/views/page_test.js

  // ------------------------------------------------------------ the frame
  var bar = h("div", { class: "vw-bar", role: "navigation", "aria-label": "Viewing point" });
  var side = h("div", { class: "vw-side" });
  var paneRtl = pane("rtl", "RTL source", "SystemVerilog, as written");
  var paneGate = pane("gate", "Logic gates", "sky130 standard cells, as synthesized");
  var paneCell = pane("cell", "Transistors", "one cell, from the SkyWater SPICE netlist");
  var paneLay = pane("lay", "Layout", "the same cell, from the SkyWater GDS");
  var paneFsm = pane("fsm", "State machines and connections", "the design as states and links");
  root.appendChild(bar);
  root.appendChild(h("div", { class: "vw-main" }, [side, h("div", { class: "vw-grid" }, [paneRtl.box, paneGate.box, paneCell.box, paneLay.box])]));
  root.appendChild(paneFsm.box);

  function pane(id, title, sub) {
    var body = h("div", { class: "vw-body", id: "vw-" + id + "-body" });
    var box = h("section", { class: "vw-pane", id: "vw-" + id, "aria-labelledby": "vw-" + id + "-h" }, [
      h("header", {}, [h("h3", { id: "vw-" + id + "-h", text: title }), h("span", { class: "vw-sub", text: sub })]),
      body]);
    return { box: box, body: body };
  }

  // ------------------------------------------------------------ side: hierarchy
  function renderSide() {
    side.innerHTML = "";
    side.appendChild(h("h3", { text: "Modules" }));
    var ul = h("ul", { class: "vw-tree" });
    V.hierarchy.forEach(function (n) {
      var mod = V.modules[n.module];
      var b = h("button", { type: "button", class: "vw-mod", "aria-pressed": String(sel.m === n.module),
        style: "padding-left:" + (0.5 + n.depth * 0.8) + "rem",
        onclick: function () { go({ m: n.module, g: null, c: null, t: null, line: null }); } },
        [h("span", { text: n.path.split(".").pop() }), h("span", { class: "vw-n", text: fmt(mod.cells) })]);
      b.title = n.module + " — " + fmt(mod.cells) + " cells, " + fmt(mod.area) + " µm²";
      ul.appendChild(h("li", {}, [b]));
    });
    side.appendChild(ul);
  }

  // ------------------------------------------------------------ breadcrumb
  function renderBar() {
    bar.innerHTML = "";
    var crumbs = [];
    if (sel.m) crumbs.push(["module", sel.m, function () { go({ g: null, c: null, t: null }); }]);
    if (sel.g) crumbs.push([V.groups[sel.g].kind === "register" ? "register" : "output", V.groups[sel.g].name, function () { go({ c: null, t: null }); }]);
    if (sel.c) crumbs.push(["gate", sel.c + " (" + (cellType(sel.m, sel.c) || "") + ")", function () { go({ t: null }); }]);
    if (sel.t) crumbs.push(["transistor", sel.t, function () {}]);
    if (sel.f != null && sel.st != null) {
      var F = V.fsms[sel.f], st = F.states.filter(function (x) { return x.index === sel.st; })[0];
      if (st) crumbs.push(["state", F.module + "." + st.name, function () {}]);
    }
    bar.appendChild(h("span", { class: "vw-lbl", text: "Viewing point:" }));
    if (!crumbs.length) bar.appendChild(h("span", { class: "vw-hint", text: "choose a module, a line, a gate or a state" }));
    crumbs.forEach(function (c, i) {
      if (i) bar.appendChild(h("span", { class: "vw-sep", "aria-hidden": "true", text: "›" }));
      bar.appendChild(h("button", { type: "button", class: "vw-crumb", onclick: c[2] }, [h("small", { text: c[0] }), " " + c[1]]));
    });
  }

  // ------------------------------------------------------------ RTL
  var KW = /\b(module|endmodule|input|output|inout|wire|logic|reg|assign|always_ff|always_comb|always|begin|end|if|else|case|unique|endcase|default|localparam|parameter|generate|endgenerate|for|genvar|posedge|negedge|int|signed|function|endfunction|return)\b/g;
  function hl(line) {
    var esc = line.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    var ci = esc.indexOf("//");
    var code = ci >= 0 ? esc.slice(0, ci) : esc, com = ci >= 0 ? esc.slice(ci) : "";
    code = code.replace(KW, "<b>$1</b>").replace(/(\d+'[bdh][0-9a-fA-F_]+)/g, "<i>$1</i>");
    return code + (com ? "<em>" + com + "</em>" : "");
  }
  function rtlMarks() {
    // line -> list of groups / FSM states / ISA rows that point here
    var marks = {};
    if (!sel.m) return marks;
    V.modules[sel.m].groups.forEach(function (gid) {
      V.groups[gid].rtl.forEach(function (ln) { (marks[ln] = marks[ln] || []).push({ kind: "g", id: gid }); });
    });
    V.fsms.forEach(function (F, fi) {
      if (F.module !== sel.m) return;
      F.states.forEach(function (st) {
        if (st.arm) (marks[st.arm[0]] = marks[st.arm[0]] || []).push({ kind: "s", f: fi, st: st.index });
      });
    });
    return marks;
  }
  function highlighted() {
    var lines = {};
    if (sel.g) V.groups[sel.g].rtl.forEach(function (l) { lines[l] = "g"; });
    if (sel.f != null) {
      var F = V.fsms[sel.f];
      if (F.module === sel.m) {
        if (sel.st != null) F.states.forEach(function (st) {
          if (st.index === sel.st && st.arm) for (var l = st.arm[0]; l <= st.arm[1]; l++) lines[l] = "s";
        });
        if (sel.e != null) F.edges[sel.e].rtl.forEach(function (l) { lines[l] = "e"; });
      }
    }
    if (sel.line && !lines[sel.line]) lines[sel.line] = "x";
    return lines;
  }
  function renderRtl() {
    var b = paneRtl.body;
    b.innerHTML = "";
    if (!sel.m) { b.appendChild(h("p", { class: "vw-empty", text: "Choose a module on the left to read its source." })); return; }
    var mod = V.modules[sel.m], lines = V.files[mod.file], marks = rtlMarks(), hi = highlighted();
    b.appendChild(h("p", { class: "vw-meta" }, [h("code", { text: mod.file }), " lines " + mod.lines[0] + "–" + mod.lines[1] +
      ". Marked lines (▸) assign a register or start a state; choose one to see its gates."]));
    var pre = h("div", { class: "vw-code", role: "list" });
    var first = null;
    for (var i = mod.lines[0]; i <= mod.lines[1]; i++) {
      (function (ln) {
        var mk = marks[ln];
        var row = h("div", { class: "vw-ln" + (hi[ln] ? " on-" + hi[ln] : "") + (mk ? " mk" : ""), role: "listitem", "data-line": ln }, [
          h("span", { class: "no", text: String(ln) }), h("span", { class: "tx", html: hl(lines[ln - 1] || "") || " " })]);
        if (mk) {
          var m0 = mk[0];
          var label = "line " + ln + ": " + (m0.kind === "g" ? "logic of " + V.groups[m0.id].name : "state " + V.fsms[m0.f].states.filter(function (x) { return x.index === m0.st; })[0].name);
          clickable(row, label, function () {
            if (m0.kind === "g") go({ g: m0.id, c: null, t: null, line: ln, f: null, st: null, e: null });
            else go({ f: m0.f, st: m0.st, e: null, line: ln, g: fsmGroup(m0.f), c: stateFlop(m0.f, m0.st), t: null });
          });
        }
        if (hi[ln] && !first) first = row;
        pre.appendChild(row);
      })(i);
    }
    b.appendChild(pre);
    if (first) requestAnimationFrame(function () { pre.scrollTop = Math.max(0, first.offsetTop - pre.offsetTop - 40); });
  }

  // ------------------------------------------------------------ gates
  function gateShape(t) {
    var n = t.replace(/_\d+$/, "");
    if (/^(clk)?inv$/.test(n)) return "inv";
    if (/^buf$/.test(n)) return "buf";
    if (/^nand\d/.test(n)) return "nand";
    if (/^and\d/.test(n)) return "and";
    if (/^nor\d/.test(n)) return "nor";
    if (/^or\d/.test(n)) return "or";
    if (/^xnor/.test(n)) return "xnor";
    if (/^xor/.test(n)) return "xor";
    if (/^mux/.test(n)) return "mux";
    if (/^df/.test(n)) return "ff";
    return "box";
  }
  var GW = 46, GH = 30, CX = 112, RY = 46;
  function drawGate(g, shape, label) {
    var p;
    var w = GW, hh = GH;
    switch (shape) {
      case "inv": case "buf":
        p = s("path", { d: "M0,0 L" + (w - 8) + "," + hh / 2 + " L0," + hh + " Z" }); g.appendChild(p);
        if (shape === "inv") g.appendChild(s("circle", { cx: w - 4, cy: hh / 2, r: 4, class: "bub" }));
        break;
      case "and": case "nand":
        p = s("path", { d: "M0,0 H" + (w - 8 - hh / 2) + " A" + hh / 2 + "," + hh / 2 + " 0 0 1 " + (w - 8 - hh / 2) + "," + hh + " H0 Z" }); g.appendChild(p);
        if (shape === "nand") g.appendChild(s("circle", { cx: w - 4, cy: hh / 2, r: 4, class: "bub" }));
        break;
      case "or": case "nor": case "xor": case "xnor":
        p = s("path", { d: "M0,0 Q" + (w * 0.45) + ",0 " + (w - 8) + "," + hh / 2 + " Q" + (w * 0.45) + "," + hh + " 0," + hh + " Q10," + hh / 2 + " 0,0 Z" }); g.appendChild(p);
        if (shape === "xor" || shape === "xnor") g.appendChild(s("path", { d: "M-5,0 Q5," + hh / 2 + " -5," + hh, class: "xl" }));
        if (shape === "nor" || shape === "xnor") g.appendChild(s("circle", { cx: w - 4, cy: hh / 2, r: 4, class: "bub" }));
        break;
      case "mux":
        p = s("path", { d: "M0,-4 L" + w + ",6 L" + w + "," + (hh - 6) + " L0," + (hh + 4) + " Z" }); g.appendChild(p);
        break;
      case "ff":
        p = s("rect", { x: 0, y: -4, width: w, height: hh + 8, rx: 2 }); g.appendChild(p);
        g.appendChild(s("path", { d: "M0," + (hh - 2) + " l7,-5 l-7,-5", class: "xl" }));
        break;
      default:
        p = s("rect", { x: 0, y: 0, width: w, height: hh, rx: 6 }); g.appendChild(p);
    }
    p.setAttribute("class", "body");
    g.appendChild(s("text", { x: w / 2 - (shape === "box" || shape === "ff" || shape === "mux" ? 0 : 6), y: hh + 13, class: "gl", "text-anchor": "middle", text: label }));
  }
  function renderGate() {
    var b = paneGate.body;
    b.innerHTML = "";
    if (!sel.m) { b.appendChild(h("p", { class: "vw-empty", text: "Choose a module first." })); return; }
    var mod = V.modules[sel.m];
    var chips = h("div", { class: "vw-chips", role: "group", "aria-label": "Registers and outputs of " + sel.m });
    mod.groups.forEach(function (gid) {
      var gr = V.groups[gid];
      chips.appendChild(h("button", { type: "button", "aria-pressed": String(sel.g === gid), class: "vw-chip " + gr.kind,
        title: gr.kind === "register" ? gr.flops + " flip-flops, " + gr.size + " cells in the cone" : "output port, " + gr.size + " cells",
        onclick: function () { go({ g: gid, c: null, t: null, line: null }); } }, [gr.name, h("small", { text: " " + gr.size })]));
    });
    b.appendChild(h("p", { class: "vw-meta", text: fmt(mod.cells) + " cells, " + fmt(mod.area) + " µm², " + mod.flops + " flip-flops. Each register below is drawn with the logic cone that computes its next value." }));
    b.appendChild(chips);
    if (!sel.g) { b.appendChild(h("p", { class: "vw-empty", text: "Choose a register or output." })); return; }
    var gr = V.groups[sel.g];
    var note = gr.kind === "register"
      ? gr.flops + " flip-flop" + (gr.flops === 1 ? "" : "s") + " (right) and the " + (gr.size - gr.flops) + " gates that compute what they load next. Inputs on the left come from other registers or ports."
      : "The " + gr.size + " gates that drive output port " + gr.name + ".";
    if (gr.dropped) note += " The cone has " + gr.dropped + " more gates further left than this view draws (it keeps the " + V.about.max_draw + " nearest the flip-flops).";
    b.appendChild(h("p", { class: "vw-meta", text: note }));
    var ncol = 0, nrow = {};
    gr.nodes.forEach(function (n) { ncol = Math.max(ncol, n[2]); nrow[n[2]] = Math.max(nrow[n[2]] || 0, n[3]); });
    var maxr = 0; for (var c in nrow) maxr = Math.max(maxr, nrow[c]);
    var W = (ncol + 1) * CX + 120, H = (maxr + 1) * RY + 40;
    var svg = s("svg", { viewBox: "-110 -20 " + W + " " + H, width: W * zoom, height: H * zoom, class: "vw-svg gates", role: "group", "aria-label": "Gate schematic of " + gr.name });
    function xy(n) { return [n[2] * CX, n[3] * RY]; }
    var edgeG = s("g", { class: "edges" });
    svg.appendChild(edgeG);
    gr.edges.forEach(function (e) {
      var a = gr.nodes[e[0]], bn = gr.nodes[e[1]];
      var p0 = xy(a), p1 = xy(bn);
      var x0 = p0[0] + (a[1] === "i" ? 0 : GW), y0 = p0[1] + GH / 2, x1 = p1[0], y1 = p1[1] + GH / 2;
      var on = sel.c && (a[0] === sel.c || bn[0] === sel.c);
      edgeG.appendChild(s("path", { d: "M" + x0 + "," + y0 + " C" + (x0 + 40) + "," + y0 + " " + (x1 - 40) + "," + y1 + " " + x1 + "," + y1, class: "wire" + (on ? " on" : "") }));
    });
    var focusNode = null;
    gr.nodes.forEach(function (n, i) {
      var p = xy(n);
      if (n[1] === "i") {
        var t = s("text", { x: p[0] - 4, y: p[1] + GH / 2 + 4, class: "inl", "text-anchor": "end", text: n[0].replace(/^in:/, "") });
        var gIn = s("g", {}, [t]);
        if (n[4]) clickable(gIn, "input from register bit " + n[0].replace(/^in:/, "") + ", show its gates", function () {
          var target = groupOfCell(sel.m, n[4]);
          if (target) go({ g: target, c: n[4], t: null, line: null });
        });
        svg.appendChild(gIn);
        return;
      }
      var ct = gr.ctypes[i];
      var gEl = s("g", { transform: "translate(" + p[0] + "," + p[1] + ")", class: "gate " + gateShape(ct) + (sel.c === n[0] ? " sel" : "") });
      drawGate(gEl, gateShape(ct), ct.replace(/_\d+$/, ""));
      gEl.appendChild(s("title", { text: n[0] + ": sky130_fd_sc_hd__" + ct + " — " + funcText(ct) }));
      clickable(gEl, "gate " + n[0] + ", a " + ct + ", show its transistors", function () { go({ c: n[0], t: null }); });
      if (sel.c === n[0]) focusNode = gEl;
      svg.appendChild(gEl);
    });
    var wrap = h("div", { class: "vw-scroll", tabindex: "-1" }, [svg]);
    b.appendChild(h("div", { class: "vw-zoom", role: "group", "aria-label": "Zoom" }, [
      h("button", { type: "button", "aria-label": "Zoom out", text: "−", onclick: function () { zoom = Math.max(0.3, zoom / 1.3); renderGate(); } }),
      h("button", { type: "button", "aria-label": "Zoom in", text: "+", onclick: function () { zoom = Math.min(2.5, zoom * 1.3); renderGate(); } })]));
    b.appendChild(wrap);
    requestAnimationFrame(function () {
      if (!focusNode) { wrap.scrollLeft = wrap.scrollWidth; return; }   // start at the flip-flops, where the cone ends
      var r = focusNode.getBoundingClientRect(), wr = wrap.getBoundingClientRect();
      wrap.scrollLeft += r.left - wr.left - wr.width / 2; wrap.scrollTop += r.top - wr.top - wr.height / 2;
    });
  }
  var zoom = 0.8;
  function funcText(ct) {
    var T = V.celltypes[ct];
    if (!T) return "";
    if (T.seq) return "D flip-flop: Q takes D at each rising CLK edge";
    return Object.keys(T.function).map(function (p) { return p + " = " + T.function[p]; }).join("; ");
  }
  function groupOfCell(m, cn) {
    var gs = V.modules[m].groups, best = null;
    for (var i = 0; i < gs.length; i++) {
      var gr = V.groups[gs[i]];
      for (var j = 0; j < gr.nodes.length; j++) {
        if (gr.nodes[j][0] === cn && gr.nodes[j][1] === "c") {
          // a flip-flop belongs to its own register; any gate to the smallest cone holding it
          if (gr.ctypes[j] === "dfxtp_1") return gs[i];
          if (!best || gr.size < V.groups[best].size) best = gs[i];
        }
      }
    }
    return best;
  }

  // ------------------------------------------------------------ transistors
  function currentType() {
    if (sel.c && sel.m) return cellType(sel.m, sel.c);
    return null;
  }
  function renderCell() {
    var b = paneCell.body;
    b.innerHTML = "";
    var ct = currentType();
    if (!ct) { b.appendChild(h("p", { class: "vw-empty", text: "Choose a gate in the schematic to see the transistors it is made of." })); return; }
    var T = V.celltypes[ct];
    var ins = Object.keys(T.pins).filter(function (p) { return T.pins[p] === "input"; });
    var outs = Object.keys(T.pins).filter(function (p) { return T.pins[p] === "output"; });
    ins.forEach(function (p) { if (!(p in simIn)) simIn[p] = 0; });
    var val = cellValues(ct);
    var fn = T.seq ? "Q takes D on each rising edge of CLK (flip CLK to 0 then 1 to load D)" : outs.map(function (o) { return o + " = " + T.function[o]; }).join(", ");
    b.appendChild(h("p", { class: "vw-meta" }, [h("b", { text: "sky130_fd_sc_hd__" + ct }), " — " + T.fets.length + " transistors, " + T.area + " µm². Liberty function: ", h("code", { text: fn })]));
    // input switches
    var sw = h("div", { class: "vw-chips", role: "group", "aria-label": "Inputs of " + ct });
    ins.forEach(function (p) {
      sw.appendChild(h("button", { type: "button", class: "vw-chip pin", "aria-pressed": String(simIn[p] === 1),
        onclick: function () { simIn[p] = simIn[p] ? 0 : 1; renderCell(); renderLayout(); } }, [p + " = " + simIn[p]]));
    });
    outs.forEach(function (o) {
      var sv = val[o], lv = T.seq ? null : libEval(T.function[o], simIn);
      sw.appendChild(h("span", { class: "vw-out" + (sv === 1 ? " hi" : ""), role: "status" },
        [o + " = " + sv + (lv == null ? "" : (sv === lv ? "  ✓ matches liberty" : "  ✗ liberty says " + lv))]));
    });
    b.appendChild(sw);
    // schematic: PMOS row above, NMOS row below, each at its x in the layout
    var bb = T.bbox, scale = Math.max(90, Math.min(220, 640 / (bb[2] - bb[0]))), wpx = (bb[2] - bb[0]) * scale + 80;
    var svg = s("svg", { viewBox: "-40 0 " + (wpx + 40) + " 250", width: Math.min(wpx + 40, 900), class: "vw-svg fets", role: "group", "aria-label": "Transistor schematic of " + ct });
    svg.appendChild(s("line", { x1: -30, x2: wpx - 50, y1: 18, y2: 18, class: "rail p" }));
    svg.appendChild(s("text", { x: -30, y: 12, class: "rl", text: "VPWR (1)" }));
    svg.appendChild(s("line", { x1: -30, x2: wpx - 50, y1: 232, y2: 232, class: "rail n" }));
    svg.appendChild(s("text", { x: -30, y: 248, class: "rl", text: "VGND (0)" }));
    T.fets.forEach(function (f) {
      var x = (f[7] - bb[0]) * scale, y = f[1] === "p" ? 80 : 170;
      var g = val[f[2]];
      var on = (f[1] === "n" && g === 1) || (f[1] === "p" && g === 0);
      var grp = s("g", { transform: "translate(" + x + "," + y + ")", class: "fet " + f[1] + (on ? " on" : " off") + (sel.t === f[0] ? " sel" : "") });
      // a transparent box under the symbol, so the whole transistor takes a click, not only its 2-pixel lines
      grp.appendChild(s("rect", { x: -20, y: -24, width: 26, height: 48, class: "hit" }));
      // drain on top, source below, gate from the left (a bubble on PMOS)
      grp.appendChild(s("line", { x1: 0, y1: -24, x2: 0, y2: -10, class: "term" }));
      grp.appendChild(s("line", { x1: 0, y1: 10, x2: 0, y2: 24, class: "term" }));
      grp.appendChild(s("line", { x1: 0, y1: -10, x2: 0, y2: 10, class: "chan" }));
      grp.appendChild(s("line", { x1: -7, y1: -9, x2: -7, y2: 9, class: "gate" }));
      grp.appendChild(s("line", { x1: -20, y1: 0, x2: f[1] === "p" ? -13 : -7, y2: 0, class: "gate" }));
      if (f[1] === "p") grp.appendChild(s("circle", { cx: -10, cy: 0, r: 3, class: "bub" }));
      grp.appendChild(s("text", { x: -22, y: 4, "text-anchor": "end", class: "net v" + g, text: netName(f[2]) }));
      grp.appendChild(s("text", { x: 4, y: -26, class: "net v" + val[f[3]], text: netName(f[3]) }));
      grp.appendChild(s("text", { x: 4, y: 34, class: "net v" + val[f[4]], text: netName(f[4]) }));
      grp.appendChild(s("title", { text: f[0] + ": " + (f[1] === "p" ? "PMOS" : "NMOS") + " " + f[9] + ", W " + f[5] + " µm, L " + f[6] + " µm; gate " + f[2] + ", drain " + f[3] + ", source " + f[4] + (on ? " — conducting" : " — off") }));
      clickable(grp, "transistor " + f[0] + ", " + (f[1] === "p" ? "PMOS" : "NMOS") + ", gate " + netName(f[2]) + ", " + (on ? "conducting" : "off") + "; show it in the layout", function () { go({ t: f[0] }); });
      svg.appendChild(grp);
    });
    b.appendChild(h("div", { class: "vw-scroll short" }, [svg]));
    b.appendChild(h("p", { class: "vw-meta", text: "A PMOS (top, with a bubble) conducts when its gate is 0, an NMOS when it is 1. Lit transistors conduct; net names are coloured by the value they settle to. Each transistor sits at the x position of its gate in the layout." }));
    // truth table
    if (!T.seq && ins.length <= 5) {
      var tb = h("table", { class: "vw-tt" });
      tb.appendChild(h("tr", {}, ins.concat(outs).map(function (p) { return h("th", { text: p }); }).concat([h("th", { text: "liberty" })])));
      for (var k = 0; k < (1 << ins.length); k++) {
        var env = {}, fx = { VPWR: 1, VGND: 0 };
        ins.forEach(function (p, i) { env[p] = (k >> (ins.length - 1 - i)) & 1; fx[p] = env[p]; });
        var r = settle(T.fets, fx, 0);
        var agree = outs.every(function (o) { return r[o] === libEval(T.function[o], env); });
        var cur = ins.every(function (p) { return env[p] === simIn[p]; });
        tb.appendChild(h("tr", { class: cur ? "cur" : "" }, ins.map(function (p) { return h("td", { text: String(env[p]) }); })
          .concat(outs.map(function (o) { return h("td", { class: "o", text: String(r[o]) }); }))
          .concat([h("td", { text: agree ? "✓" : "✗" })])));
      }
      b.appendChild(h("details", {}, [h("summary", { text: "Truth table, computed from the transistors (" + (1 << ins.length) + " rows)" }), tb]));
    }
  }
  // node values of the chosen cell under the input switches. A flip-flop
  // remembers: each step settles from the last one, so flipping CLK from 0
  // to 1 loads D, and flipping D while CLK stays put changes nothing at Q.
  var ffMem = { type: null, val: null, key: null };
  function cellValues(ct) {
    var T = V.celltypes[ct], fixed = { VPWR: 1, VGND: 0 };
    Object.keys(T.pins).forEach(function (p) { if (T.pins[p] === "input") fixed[p] = simIn[p] || 0; });
    if (!T.seq) return settle(T.fets, fixed, 0);
    var key = JSON.stringify(fixed);
    if (ffMem.type === ct && ffMem.key === key) return ffMem.val;
    var prev = ffMem.type === ct ? ffMem.val : null;
    if (!prev) {
      // power-up: clock low, then a first settle; the stored bit starts as whatever the loop falls into
      prev = settle(T.fets, Object.assign({}, fixed, { CLK: 0 }), 0);
    }
    var v = settle(T.fets, fixed, 0, prev);
    ffMem = { type: ct, val: v, key: key };
    return v;
  }
  function netName(n) { return n.replace(/^a_(\d+)_(\d+)#$/, "n$1_$2"); }

  // ------------------------------------------------------------ layout
  var LAYERS = [["nwell", "n-well", "where the PMOS transistors sit"], ["diff", "diffusion", "doped silicon: sources, drains, channels"],
    ["poly", "polysilicon", "transistor gates"], ["licon", "contacts", "silicon up to local interconnect"],
    ["li1", "local interconnect", "the first wiring layer"], ["mcon", "vias", "local interconnect up to metal 1"], ["met1", "metal 1", "power rails and wiring"]];
  var hidden = {};
  function renderLayout() {
    var b = paneLay.body;
    b.innerHTML = "";
    var ct = currentType();
    if (!ct) { b.appendChild(h("p", { class: "vw-empty", text: "Choose a gate to see how it is drawn in silicon." })); return; }
    var T = V.celltypes[ct], bb = T.bbox, sc = 70;
    var tog = h("div", { class: "vw-chips", role: "group", "aria-label": "Layers" });
    LAYERS.forEach(function (L) {
      if (!T.layers[L[0]]) return;
      tog.appendChild(h("button", { type: "button", class: "vw-chip lay", "aria-pressed": String(!hidden[L[0]]), title: L[2],
        onclick: function () { hidden[L[0]] = !hidden[L[0]]; renderLayout(); } }, [h("i", { class: "sw sw-" + L[0], "aria-hidden": "true" }), L[1]]));
    });
    tog.appendChild(h("button", { type: "button", class: "vw-chip", "aria-pressed": String(finfet),
      onclick: function () { finfet = !finfet; renderLayout(); } }, ["Compare with FinFET"]));
    b.appendChild(tog);
    var w = (bb[2] - bb[0]) * sc, hh = (bb[3] - bb[1]) * sc;
    var svg = s("svg", { viewBox: "0 0 " + w + " " + hh, width: Math.min(w, 900), class: "vw-svg lay", role: "img",
      "aria-label": "Layout of sky130_fd_sc_hd__" + ct + ", " + (bb[2] - bb[0]).toFixed(2) + " by " + (bb[3] - bb[1]).toFixed(2) + " µm" });
    function pt(x, y) { return ((x - bb[0]) * sc).toFixed(1) + "," + ((bb[3] - y) * sc).toFixed(1); }
    LAYERS.forEach(function (L) {
      if (hidden[L[0]] || !T.layers[L[0]]) return;
      var g = s("g", { class: "ly ly-" + L[0] });
      T.layers[L[0]].forEach(function (poly) {
        g.appendChild(s("polygon", { points: poly.map(function (p) { return pt(p[0], p[1]); }).join(" ") }));
      });
      svg.appendChild(g);
    });
    // transistor gates, where layout-versus-schematic found them, lit if conducting
    var val = cellValues(ct);
    T.fets.forEach(function (f) {
      var c = pt(f[7], f[8]).split(",");
      var g = val[f[2]], on = (f[1] === "n" && g === 1) || (f[1] === "p" && g === 0);
      var m = s("g", { class: "gm" + (sel.t === f[0] ? " sel" : "") + (on ? " on" : "") }, [
        s("rect", { x: +c[0] - 0.075 * sc - 3, y: +c[1] - f[5] * sc / 2 - 3, width: 0.15 * sc + 6, height: f[5] * sc + 6, rx: 3 }),
        s("title", { text: f[0] + " " + (f[1] === "p" ? "PMOS" : "NMOS") + ", W " + f[5] + " µm × L " + f[6] + " µm" })]);
      clickable(m, "transistor " + f[0] + " in the layout, W " + f[5] + " micrometres", function () { go({ t: f[0] }); });
      svg.appendChild(m);
    });
    T.labels.forEach(function (l) {
      var c = pt(l[2], l[3]).split(",");
      svg.appendChild(s("text", { x: c[0], y: c[1], class: "pl", "text-anchor": "middle", text: l[0] }));
    });
    b.appendChild(h("div", { class: "vw-scroll short" }, [svg]));
    var tsel = sel.t ? T.fets.filter(function (f) { return f[0] === sel.t; })[0] : null;
    b.appendChild(h("p", { class: "vw-meta", text: (bb[2] - bb[0]).toFixed(2) + " × " + (bb[3] - bb[1]).toFixed(2) + " µm. A transistor is where polysilicon (gate) crosses diffusion; outlined boxes mark every one, found by layout-versus-schematic and paired with the netlist." +
      (tsel ? " Selected: " + tsel[0] + ", " + (tsel[1] === "p" ? "PMOS" : "NMOS") + ", W " + tsel[5] + " µm, L " + tsel[6] + " µm (" + tsel[9] + ")." : "") }));
    if (finfet) b.appendChild(finfetFigure());
  }
  function finfetFigure() {
    // a drawing for comparison only: sky130 has no FinFETs
    var svg = s("svg", { viewBox: "0 0 560 210", class: "vw-svg ff", role: "img",
      "aria-label": "Illustration: a planar MOSFET like sky130's beside a FinFET, in cross-section. Not to scale." });
    function t(x, y, txt, cls) { svg.appendChild(s("text", { x: x, y: y, class: cls || "fl", text: txt })); }
    // planar
    svg.appendChild(s("rect", { x: 20, y: 120, width: 220, height: 60, class: "si" }));
    svg.appendChild(s("rect", { x: 90, y: 112, width: 80, height: 8, class: "ox" }));
    svg.appendChild(s("rect", { x: 90, y: 72, width: 80, height: 40, class: "pg" }));
    svg.appendChild(s("rect", { x: 30, y: 120, width: 60, height: 16, class: "sd" }));
    svg.appendChild(s("rect", { x: 170, y: 120, width: 60, height: 16, class: "sd" }));
    svg.appendChild(s("path", { d: "M90,128 H170", class: "ch" }));
    t(20, 30, "Planar MOSFET (sky130, 130 nm)", "fh");
    t(20, 50, "the gate sits on top of a flat channel");
    t(96, 96, "gate"); t(34, 156, "source"); t(178, 156, "drain"); t(96, 150, "channel");
    // finfet
    svg.appendChild(s("rect", { x: 320, y: 160, width: 220, height: 20, class: "si" }));
    svg.appendChild(s("rect", { x: 410, y: 90, width: 30, height: 70, class: "fin" }));
    svg.appendChild(s("path", { d: "M396,160 V80 H454 V160 H446 V86 H404 V160 Z", class: "pg" }));
    t(320, 30, "FinFET (illustrative only)", "fh");
    t(320, 50, "the gate wraps three sides of a fin");
    t(456, 110, "gate"); t(412, 176, "fin");
    t(20, 204, "A drawing for comparison, not to scale. Every transistor in this chip is planar; sky130 has no FinFETs.", "fn");
    return h("figure", { class: "vw-ff" }, [svg, h("figcaption", {}, [h("span", { class: "ev illustrative", text: "illustrative" }),
      " A FinFET raises the channel into a fin so the gate controls it from three sides, which leaks less at small sizes. Processes at 22 nm and below use them; SkyWater 130 nm does not."])]);
  }

  // ------------------------------------------------------------ FSM, connections, ISA lens
  var fsmTab = "fsm";
  function fsmGroup(fi) { var F = V.fsms[fi]; return F.module + "/" + F.wire; }
  function stateFlop(fi, idx) { var st = V.fsms[fi].states.filter(function (x) { return x.index === idx; })[0]; return st ? st.flop : null; }
  function renderFsm() {
    var b = paneFsm.body;
    b.innerHTML = "";
    var tabs = h("div", { class: "vw-tabs", role: "tablist", "aria-label": "Lingua franca views" });
    [["fsm", "State machines"], ["links", "Connections"]].concat(V.isa ? [["isa", "RISC-V instructions"]] : []).forEach(function (t) {
      tabs.appendChild(h("button", { type: "button", role: "tab", "aria-selected": String(fsmTab === t[0]), id: "vw-tab-" + t[0],
        onclick: function () { fsmTab = t[0]; renderFsm(); } }, [t[1]]));
    });
    b.appendChild(tabs);
    var panel = h("div", { role: "tabpanel", "aria-labelledby": "vw-tab-" + fsmTab });
    b.appendChild(panel);
    if (fsmTab === "fsm") renderMachines(panel);
    else if (fsmTab === "links") renderLinks(panel);
    else renderIsa(panel);
  }
  function renderMachines(panel) {
    var pick = h("div", { class: "vw-chips", role: "group", "aria-label": "State machine" });
    V.fsms.forEach(function (F, fi) {
      pick.appendChild(h("button", { type: "button", class: "vw-chip", "aria-pressed": String(sel.f === fi),
        onclick: function () { go({ f: fi, st: null, e: null, m: F.module, g: fsmGroup(fi), c: null, t: null, line: null }); } },
        [F.module + "." + F.wire, h("small", { text: " " + F.states.length + " states" })]));
    });
    panel.appendChild(pick);
    if (sel.f == null) {
      panel.appendChild(h("p", { class: "vw-empty", text: "Yosys found " + V.fsms.length + " state machine" + (V.fsms.length === 1 ? "" : "s") + " in the RTL. Choose one: its states are viewing points into the source, the gates and the transistors." }));
      return;
    }
    var F = V.fsms[sel.f], n = F.states.length, R = 165, cx = 300, cy = 225;
    panel.appendChild(h("p", { class: "vw-meta", text: "As Yosys extracted it from " + F.module + ": " + n + " states, " + F.edges.length + " transitions. In the RTL the state is " + F.states[0].bits + " bits; synthesis re-encoded it " + F.encoding + ", so the gates hold it in " + n + " flip-flops, exactly one of them 1. Choose a state or an arrow." }));
    var svg = s("svg", { viewBox: "0 -10 600 460", width: 600, height: 460, class: "vw-svg fsm", role: "group", "aria-label": "State diagram of " + F.module });
    svg.appendChild(s("defs", {}, [s("marker", { id: "vw-arr", viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" }, [s("path", { d: "M0,0 L10,5 L0,10 z", class: "ah" })])]));
    var pos = {};
    F.states.forEach(function (st, i) {
      var a = -Math.PI / 2 + i * 2 * Math.PI / n;
      pos[st.index] = [cx + R * Math.cos(a), cy + R * Math.sin(a)];
    });
    F.edges.forEach(function (e, ei) {
      var p0 = pos[e.from], p1 = pos[e.to], d;
      if (e.from === e.to) {
        var ang = Math.atan2(p0[1] - cy, p0[0] - cx), ox = Math.cos(ang) * 40, oy = Math.sin(ang) * 40;
        d = "M" + (p0[0] + ox * 0.75 - oy * 0.35) + "," + (p0[1] + oy * 0.75 + ox * 0.35) + " C" + (p0[0] + ox * 2 - oy) + "," + (p0[1] + oy * 2 + ox) + " " + (p0[0] + ox * 2 + oy) + "," + (p0[1] + oy * 2 - ox) + " " + (p0[0] + ox * 0.75 + oy * 0.35) + "," + (p0[1] + oy * 0.75 - ox * 0.35);
      } else {
        var dx = p1[0] - p0[0], dy = p1[1] - p0[1], L = Math.sqrt(dx * dx + dy * dy), ux = dx / L, uy = dy / L;
        var sx = p0[0] + ux * 31, sy = p0[1] + uy * 31, ex = p1[0] - ux * 34, ey = p1[1] - uy * 34;
        var mx = (sx + ex) / 2 - uy * 22, my = (sy + ey) / 2 + ux * 22;
        d = "M" + sx + "," + sy + " Q" + mx + "," + my + " " + ex + "," + ey;
      }
      var on = sel.e === ei || (sel.st != null && (e.from === sel.st || e.to === sel.st));
      var path = s("path", { d: d, class: "tr" + (on ? " on" : "") + (sel.e === ei ? " sel" : ""), "marker-end": "url(#vw-arr)" });
      var hit = s("path", { d: d, class: "hit" });
      var g = s("g", {}, [path, hit, s("title", { text: nameOf(F, e.from) + " → " + nameOf(F, e.to) + ": " + e.when.join("  OR  ") })]);
      clickable(g, "transition " + nameOf(F, e.from) + " to " + nameOf(F, e.to), function () { go({ e: ei, st: null, line: null, c: null, t: null }); });
      svg.appendChild(g);
    });
    F.states.forEach(function (st) {
      var p = pos[st.index];
      var g = s("g", { class: "st" + (sel.st === st.index ? " sel" : "") + (st.reset ? " reset" : ""), transform: "translate(" + p[0] + "," + p[1] + ")" }, [
        s("circle", { r: 29 }), st.reset ? s("circle", { r: 33, class: "ring" }) : null,
        s("text", { y: -2, "text-anchor": "middle", class: "sn", text: st.name.replace(/^[SQ]_/, "") }),
        s("text", { y: 12, "text-anchor": "middle", class: "sc", text: binary(st.code, st.bits) })]);
      clickable(g, "state " + st.name + ", code " + st.code + ", one-hot flip-flop " + st.onehot + (st.reset ? ", the reset state" : ""), function () {
        go({ st: st.index, e: null, m: F.module, g: fsmGroup(sel.f), c: st.flop, t: null, line: st.arm ? st.arm[0] : null });
      });
      svg.appendChild(g);
    });
    // side legend: the selection's details
    var info = h("div", { class: "vw-fsminfo" });
    if (sel.st != null) {
      var st = F.states.filter(function (x) { return x.index === sel.st; })[0];
      info.appendChild(h("h4", { text: st.name + (st.reset ? " (reset state)" : "") }));
      info.appendChild(h("p", { text: "RTL code " + binary(st.code, st.bits) + " (" + st.code + "), declared on line " + st.decl + "; its case arm is lines " + (st.arm ? st.arm[0] + "–" + st.arm[1] : "(none)") + ". In the gates it is flip-flop " + st.flop + " (one-hot bit " + st.onehot + "), shown in the schematic above." }));
      var outE = F.edges.filter(function (e) { return e.from === st.index; });
      info.appendChild(h("p", { text: "Leaves to: " + outE.map(function (e) { return nameOf(F, e.to); }).join(", ") }));
    } else if (sel.e != null) {
      var e = F.edges[sel.e];
      info.appendChild(h("h4", { text: nameOf(F, e.from) + " → " + nameOf(F, e.to) }));
      info.appendChild(h("p", { text: "Taken when any of these hold (Yosys's own transition table):" }));
      var ul = h("ul", {});
      e.when.forEach(function (w) { ul.appendChild(h("li", {}, [h("code", { text: w })])); });
      info.appendChild(ul);
      info.appendChild(h("p", { text: e.rtl.length ? "Written in the RTL on line" + (e.rtl.length > 1 ? "s " : " ") + e.rtl.join(", ") + "." : (e.from === e.to ? "Staying put needs no line: no assignment fires." : "No single line names this target (it goes through a variable).") }));
    } else info.appendChild(h("p", { class: "vw-empty", text: "Choose a state or an arrow." }));
    panel.appendChild(h("div", { class: "vw-fsmwrap" }, [h("div", { class: "vw-scroll" }, [svg]), info]));
  }
  function nameOf(F, idx) { var st = F.states.filter(function (x) { return x.index === idx; })[0]; return st ? st.name : String(idx); }
  function binary(v, n) { var t = v.toString(2); while (t.length < n) t = "0" + t; return t; }
  function renderLinks(panel) {
    var parent = sel.m && V.modules[sel.m].links.length ? sel.m : V.chip.links_root;
    var mod = V.modules[parent];
    panel.appendChild(h("p", { class: "vw-meta", text: "Inside " + parent + ": each box is a submodule and each line the number of wires two of them share, counted in the gate netlist. Choose a box to open that module." }));
    var subs = {};
    var cellsOf = {};
    V.hierarchy.forEach(function (n) { cellsOf[n.path] = n; });
    mod.links.forEach(function (l) { subs[l[0]] = 1; subs[l[1]] = 1; });
    var names = Object.keys(subs).sort(), N = names.length, cx = 360, cy = 190, R = 140, pos = {};
    var svg = s("svg", { viewBox: "0 0 720 390", class: "vw-svg links", role: "group", "aria-label": "Connections inside " + parent });
    names.forEach(function (nm, i) { var a = -Math.PI / 2 + i * 2 * Math.PI / N; pos[nm] = [cx + R * 1.5 * Math.cos(a), cy + R * Math.sin(a)]; });
    var maxw = 1; mod.links.forEach(function (l) { maxw = Math.max(maxw, l[2]); });
    mod.links.forEach(function (l) {
      var a = pos[l[0]], c = pos[l[1]];
      svg.appendChild(s("g", {}, [s("line", { x1: a[0], y1: a[1], x2: c[0], y2: c[1], class: "ln", "stroke-width": 1 + 5 * l[2] / maxw }),
        s("text", { x: (a[0] + c[0]) / 2, y: (a[1] + c[1]) / 2 - 4, class: "lw", "text-anchor": "middle", text: String(l[2]) })]));
    });
    names.forEach(function (nm) {
      var typ = null;
      V.hierarchy.forEach(function (hn) { if (hn.path.slice(-nm.length - 1) === "." + nm) typ = hn.module; });   // nm may cross a generate block (g_cpu.u_core)
      var p = pos[nm];
      var g = s("g", { class: "mb", transform: "translate(" + p[0] + "," + p[1] + ")" }, [
        s("rect", { x: -62, y: -20, width: 124, height: 40, rx: 4 }),
        s("text", { y: -3, "text-anchor": "middle", class: "mn", text: nm.split(".").pop() }),
        s("text", { y: 12, "text-anchor": "middle", class: "mt", text: (typ || "") + (typ ? " · " + fmt(V.modules[typ].cells) : "") })]);
      if (typ) clickable(g, "module " + nm + " (" + typ + "), open it", function () { go({ m: typ, g: null, c: null, t: null, line: null }); });
      svg.appendChild(g);
    });
    panel.appendChild(h("div", { class: "vw-scroll" }, [svg]));
  }
  function renderIsa(panel) {
    if (!V.isa) { panel.appendChild(h("p", { text: "No ISA data." })); return; }
    panel.appendChild(h("p", { class: "vw-meta", text: V.isa.about }));
    var tb = h("table", { class: "vw-isa" });
    tb.appendChild(h("tr", {}, ["instruction", "encoding", "format and fields", "what it does"].map(function (t) { return h("th", { text: t }); })));
    V.isa.rows.forEach(function (r) {
      var td0 = h("td", {}, [h("code", { text: r.rv })]);
      if (r.rtl) {
        var a = h("button", { type: "button", class: "vw-link", text: "decoded on line " + r.rtl[1].join(", "),
          onclick: function () { go({ m: V.chip.isa_module, g: null, c: null, t: null, line: r.rtl[1][0], f: null, st: null, e: null }); } });
        td0.appendChild(h("br")); td0.appendChild(a);
      }
      tb.appendChild(h("tr", {}, [td0, h("td", {}, [h("code", { text: r.rv_hex })]),
        h("td", {}, [h("code", { text: fieldText(r.rv_fields) })]), h("td", { text: r.note })]));
    });
    panel.appendChild(h("div", { class: "vw-tablewrap" }, [tb]));
    panel.appendChild(h("p", { class: "vw-meta", text: "Assembled with " + V.isa.assemblers.riscv + ". Every instruction is one 32-bit word; its opcode (bits 6:0) picks the format, and the core decodes it on the linked line." }));
  }
  // the RISC-V base formats by opcode; only R-type has every field, so the others show their format
  var FORMAT = { 0x37: "U", 0x17: "U", 0x6f: "J", 0x67: "I", 0x63: "B", 0x03: "I", 0x23: "S", 0x13: "I", 0x33: "R", 0x0f: "I", 0x73: "I", 0x0b: "R" };
  function fieldText(f) {
    var t = FORMAT[f.opcode] || "?";
    var out = "opcode " + binary(f.opcode, 7) + ", " + t + "-type";
    if (t === "R") out += ": rd " + f.rd + " rs1 " + f.rs1 + " rs2 " + f.rs2 + " funct3 " + f.funct3 + " funct7 " + binary(f.funct7, 7);
    else if (t === "I") out += ": rd " + f.rd + " rs1 " + f.rs1 + " funct3 " + f.funct3;
    else if (t === "S" || t === "B") out += ": rs1 " + f.rs1 + " rs2 " + f.rs2 + " funct3 " + f.funct3;
    else out += ": rd " + f.rd;
    return out;
  }

  // ------------------------------------------------------------ render all
  function render() {
    renderSide(); renderBar(); renderRtl(); renderGate(); renderCell(); renderLayout(); renderFsm();
  }
  window.addEventListener("hashchange", function () { var o = readHash(); go(o, true); });
  var start = readHash();
  if (!start.m) { start.m = V.chip.start.m; start.g = V.chip.start.g; }
  go(start, true);
  root.classList.add("ready");
})();
