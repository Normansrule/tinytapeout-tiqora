/* floorplan.js: the Tiny Tapeout floorplan (docs/tools/tt_floorplan.py) as four steps,
   package, die, tile grid, this design. Shared unchanged by both Tiqora repositories.
   Without JavaScript the four panels stay visible one after another; with it they become
   tabs: click, or arrow keys, Home and End on the focused tab. Reduced motion: no fade. */
const TQFloorplan = (function () {
  function init(root) {
    if (!root) return;
    const list = root.querySelector("[role=tablist]");
    const tabs = Array.from(root.querySelectorAll("[role=tab]"));
    const panels = Array.from(root.querySelectorAll("[role=tabpanel]"));
    list.hidden = false;
    root.classList.add("fp-on");
    function show(i, focus) {
      tabs.forEach((t, k) => { t.setAttribute("aria-selected", String(k === i)); t.tabIndex = k === i ? 0 : -1; });
      panels.forEach((p, k) => { p.hidden = k !== i; });
      if (focus) tabs[i].focus();
    }
    tabs.forEach((t, i) => {
      t.addEventListener("click", () => show(i, false));
      t.addEventListener("keydown", e => {
        const n = tabs.length;
        const j = { ArrowRight: (i + 1) % n, ArrowDown: (i + 1) % n, ArrowLeft: (i + n - 1) % n, ArrowUp: (i + n - 1) % n, Home: 0, End: n - 1 }[e.key];
        if (j === undefined) return;
        e.preventDefault();
        show(j, true);
      });
    });
    show(0, false);
  }
  return { init };
})();
