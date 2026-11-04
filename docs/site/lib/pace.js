/* pace.js — keeps the page light while it scrolls.
   Shared unchanged by tiqora-skywater130 and tinytapeout-tiqora.

   The recorded reels and the logic drawings animate with CSS. A browser keeps running those
   animations, restyling every frame, even when the drawing is far off screen. Here every
   drawing in the page is watched, and one more than a screen away is marked data-idle, which
   exhibit.css turns into animation-play-state: paused for it and everything inside it. It
   resumes where it stopped when it comes back. Nothing else changes: no drawing is hidden,
   moved or redrawn, and with reduced motion (when the drawings do not animate) this does
   nothing visible. */
(function (root) {
  "use strict";
  if (!("IntersectionObserver" in root)) return;
  const io = new IntersectionObserver(es => {
    for (const e of es) e.target.toggleAttribute("data-idle", !e.isIntersecting);
  }, { rootMargin: "100% 0px" });
  document.querySelectorAll("main svg, main .reel").forEach(el => io.observe(el));
})(window);
