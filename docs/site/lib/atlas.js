/* atlas.js — the chip atlas: every real block, what it does, how it connects.
   Shared unchanged by tiqora-skywater130 and tinytapeout-tiqora.

   The data is docs/site/data/atlas.json, written by docs/tools/atlas.py from
   the RTL (Yosys elaboration) and docs/atlas/notes.json. Signals are
   followed as text: a net lists who drives it and who reads it, each a
   button, so nothing depends on colour or hover. */
(function (root) {
  "use strict";

  function h(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    for (const k in attrs || {}) {
      if (k === "on") for (const ev in attrs.on) e.addEventListener(ev, attrs.on[ev]);
      else if (k === "text") e.textContent = attrs[k];
      else if (attrs[k] !== undefined && attrs[k] !== null) e.setAttribute(k, attrs[k]);
    }
    kids.flat().forEach(k => k != null && e.append(k));
    return e;
  }
  const short = p => p.split("/").pop();

  function mount(host, A, cfg) {
    cfg = cfg || {};
    const byPath = {};
    A.blocks.forEach(b => byPath[b.path] = b);
    const area = (A.area && A.area.modules_um2) || {};
    const modesArea = (A.area && A.area.modes && A.area.modes.modules_um2) || {};
    const netsOf = path => A.nets.filter(n => n.drivers.some(d => d.block === path) || n.loads.some(l => l.block === path));
    let sel = null, filter = "", build = "all", view = "explore", net = null;

    const search = h("input", { type: "search", placeholder: "Find a block", "aria-label": "Find a block by name", on: { input: e => { filter = e.target.value.toLowerCase(); renderTree(); } } });
    const buildSel = h("select", { "aria-label": "Which build", on: { change: e => { build = e.target.value; renderTree(); renderTable(); } } },
      h("option", { value: "all", text: "Every build" }),
      ...Object.keys(A.builds).map(k => h("option", { value: k, text: k === "tile" ? "Tiny Tapeout tile only" : "FPGA / full-chip build (" + k + ")" })));
    const viewBtn = h("button", { type: "button", class: "btn ghost", "aria-pressed": "false", on: { click: () => { view = view === "explore" ? "table" : "explore"; viewBtn.setAttribute("aria-pressed", String(view === "table")); viewBtn.textContent = view === "table" ? "Explorer view" : "Table view"; show(); } } }, "Table view");
    const bar = h("div", { class: "row toolbar" }, search, buildSel, viewBtn,
      h("span", { class: "small", text: A.blocks.length + " blocks, " + A.nets.length + " connections, from " + A.generated_by.split(" from ")[0] }));
    const tree = h("nav", { class: "tree", "aria-label": "Blocks by category" });
    const detail = h("article", { class: "detail", tabindex: "-1", "aria-live": "polite" });
    const explore = h("div", { class: "atlas" }, tree, detail);
    const table = h("div", { class: "tablewrap", hidden: "" });
    host.append(bar, explore, table);

    function inBuild(b) { return build === "all" || b.builds.includes(build); }
    function matches(b) { return !filter || (b.title + " " + b.module + " " + b.path + " " + b.summary).toLowerCase().includes(filter); }

    function renderTree() {
      const kids = [];
      Object.keys(A.categories).forEach(cat => {
        const bs = A.blocks.filter(b => b.category === cat && matches(b));
        if (!bs.length) return;
        kids.push(h("h2", { text: cat }));
        bs.forEach(b => {
          const onNet = net && (net.drivers.concat(net.loads)).some(e => e.block === b.path);
          kids.push(h("button", { type: "button", class: inBuild(b) ? "" : "dim", "aria-current": sel && sel.path === b.path ? "true" : "false",
            title: inBuild(b) ? "" : "Not in this build", on: { click: () => choose(b.path, true) } },
            onNet ? h("span", { class: "onnet", "aria-label": "on the followed net", role: "img" }) : null, b.title, h("small", { text: b.module + (b.builds.length === 1 ? "  · " + b.builds[0] + " only" : "") })));
        });
      });
      if (!kids.length) kids.push(h("p", { class: "small", text: "No block matches." }));
      tree.replaceChildren(...kids);
    }

    function src(b) {
      const url = cfg.repo ? cfg.repo + "/blob/" + (cfg.ref || "main") + "/" + b.file + "#L" + b.line : null;
      return url ? h("a", { href: url, text: b.file + ":" + b.line }) : h("code", { text: b.file + ":" + b.line });
    }

    function areaText(b) {
      const v = area[b.module], m = modesArea[b.module];
      if (v === undefined && m === undefined) return null;
      const parts = [];
      if (v !== undefined) parts.push(v.toLocaleString("en-US", { maximumFractionDigits: 1 }) + " µm² in the tile build");
      if (m !== undefined && m !== v) parts.push(m.toLocaleString("en-US", { maximumFractionDigits: 1 }) + " µm² with " + A.area.modes.define);
      return h("span", {}, parts.join("; ") + " ", h("span", { class: "ev measured", text: "measured" }),
        h("span", { class: "small", text: " summed standard-cell area of this module alone, Yosys synthesis with " + A.area.library + ": not a layout" }));
    }

    function followNet(n, focus) {
      net = n;
      renderTree();
      const end = (e, role) => h("li", {}, role + " ", h("button", { type: "button", class: "follow", on: { click: () => choose(e.block, true) } }, byPath[e.block] ? byPath[e.block].title : short(e.block)),
        " port ", h("code", { text: e.port }), e.bits !== n.width ? " (" + e.bits + " of " + n.width + " bits)" : "");
      const panel = detail.querySelector(".netpanel");
      if (!panel) return;
      panel.replaceChildren(h("h3", { text: "Following " + n.net + " [" + n.width + "]" }),
        h("p", { class: "small", text: "Inside " + (byPath[n.in] ? byPath[n.in].title : n.in) + (n.const_bits ? "; " + n.const_bits + " bits tied to constants" : "") + ". Blocks on this net are marked ◆ in the list." }),
        h("ul", {}, ...n.drivers.map(e => end(e, "driven by")), ...n.loads.map(e => end(e, "read by"))),
        h("button", { type: "button", class: "follow", on: { click: () => { net = null; panel.replaceChildren(); renderTree(); } } }, "Stop following"));
      if (focus) panel.querySelector("h3").scrollIntoView({ block: "nearest" });
    }

    function choose(path, focus) {
      sel = byPath[path] || A.blocks[0];
      const b = sel;
      renderTree();
      const nets = netsOf(b.path);
      const portNets = {};
      nets.forEach(n => [...n.drivers, ...n.loads].filter(e => e.block === b.path).forEach(e => (portNets[e.port] = portNets[e.port] || []).push(n)));
      const parent = A.blocks.find(x => (x.children || []).includes(b.path));
      const kv = (k, v) => v ? [h("dt", { text: k }), h("dd", {}, v)] : [];
      // replaceChildren() neither flattens arrays nor skips null, so the
      // optional parts are flattened and filtered here
      detail.replaceChildren(...[
        h("h2", { text: b.title }),
        h("p", { class: "meta" }, h("span", { class: "tag cat cat-" + b.category, text: b.category }), " ",
          b.builds.length === Object.keys(A.builds).length ? "in every build" : b.builds.map(x => x === "tile" ? "Tiny Tapeout tile" : "FPGA / full chip (" + x + ")").join(", ") + " only",
          " · ", h("code", { text: b.module }), " instance ", h("code", { text: b.path })),
        h("p", { class: "lede", text: b.summary }),
        b.example ? h("div", { class: "note good" }, h("b", { text: "Example. " }), b.example) : null,
        h("dl", { class: "kv" },
          ...kv("Source", src(b)),
          ...kv("Flip-flops", b.ff_bits ? b.ff_bits + " bits (from the elaborated RTL)" : "none of its own"),
          ...kv("Area", areaText(b)),
          ...kv("Inside", parent ? h("button", { type: "button", class: "follow", on: { click: () => choose(parent.path, true) } }, parent.title) : "the top: this is the module the shuttle sees"),
          ...kv("Contains", (b.children || []).length ? h("span", {}, ...b.children.map(c => h("button", { type: "button", class: "follow", style: "margin: 0 .3rem .3rem 0", on: { click: () => choose(c, true) } }, byPath[c] ? byPath[c].title : short(c)))) : null),
          ...kv("Tests", (b.tests || []).length ? h("span", {}, ...b.tests.map(t => h("code", { class: "tag", text: "make -C test " + t }))) : "none"),
          ...kv("Parameters", Object.keys(b.params || {}).length ? h("span", {}, ...Object.entries(b.params).map(([k, v]) => h("code", { class: "tag", text: k + " = " + v }))) : null)),
        b.stages && b.stages.length ? [h("h3", { text: "What happens inside" }), h("ol", { class: "stages" }, ...b.stages.map(s => h("li", { text: s })))] : null,
        h("h3", { text: "Behaviour" }),
        h("dl", { class: "kv" }, ...kv("Handshake", b.handshake), ...kv("Latency", b.latency), ...kv("Reset", b.reset), ...kv("Stalls", b.stall), ...kv("Errors", b.errors)),
        h("h3", { text: "Ports" }),
        h("div", { class: "tablewrap" }, h("table", {},
          h("thead", {}, h("tr", {}, h("th", { class: "nw", text: "Port" }), h("th", { class: "nw", text: "Dir" }), h("th", { class: "num", text: "Bits" }), h("th", { text: "Meaning and legal values" }), h("th", { text: "Connects to" }))),
          h("tbody", {}, ...b.ports.map(p => h("tr", {},
            h("td", { class: "nw" }, h("code", { text: p.name })), h("td", { class: "nw", text: p.dir === "input" ? "in" : p.dir === "output" ? "out" : p.dir }), h("td", { class: "num", text: p.width }),
            h("td", { text: ((b.port_notes || {})[p.name] || "").replace(/^\[\d+\]\s*/, "") }),
            h("td", {}, ...(portNets[p.name] || []).map(n => h("button", { type: "button", class: "follow", style: "margin: 0 .3rem .3rem 0", on: { click: () => followNet(n, true) } }, "follow " + n.net)))))))),
        h("div", { class: "netpanel" })].flat().filter(x => x != null));
      if (net && nets.includes(net)) followNet(net); else net = null;
      if (focus) { detail.focus(); try { history.replaceState(null, "", "#block=" + encodeURIComponent(b.path)); } catch (e) {} }
      if (cfg.onSelect) cfg.onSelect(b);
    }

    function renderTable() {
      table.replaceChildren(h("table", {},
        h("caption", { class: "sr", text: "Every block in the chip" }),
        h("thead", {}, h("tr", {}, ...["Block", "Module", "Category", "Builds", "Flip-flop bits", "Area µm² (measured)", "Tests", "What it does"].map((t, i) => h("th", { class: i === 4 || i === 5 ? "num" : "", text: t })))),
        h("tbody", {}, ...A.blocks.filter(inBuild).map(b => h("tr", {},
          h("td", {}, h("a", { href: "#block=" + encodeURIComponent(b.path), on: { click: e => { e.preventDefault(); viewBtn.click(); choose(b.path, true); } } }, b.title)),
          h("td", {}, h("code", { text: b.module })), h("td", { text: b.category }), h("td", { text: b.builds.join(", ") }),
          h("td", { class: "num", text: b.ff_bits }), h("td", { class: "num", text: area[b.module] !== undefined ? area[b.module].toLocaleString("en-US") : (modesArea[b.module] !== undefined ? modesArea[b.module].toLocaleString("en-US") + " (modes)" : "–") }),
          h("td", { text: (b.tests || []).join(", ") }), h("td", { text: b.summary }))))));
    }

    function show() {
      explore.hidden = view !== "explore";
      table.hidden = view !== "table";
      if (view === "table") renderTable();
    }

    renderTable();
    const m = /block=([^&]+)/.exec(location.hash);
    choose(m ? decodeURIComponent(m[1]) : A.blocks[0].path);
    return { choose };
  }

  root.TQAtlas = { mount };
})(window);
