/* Cognitive Assist dashboard - minimal, offline, zero network calls.
 *
 * Two small progressive enhancements, both optional:
 *   1. A page-age indicator that shows how stale the displayed data is.
 *   2. A subtle pointer-driven 3D tilt on elements marked with data-tilt.
 *
 * No polling, no fetches, no timers that contact the server. Everything
 * degrades gracefully: with JavaScript disabled, or for users who prefer
 * reduced motion, the pages are fully usable. */

(function () {
  'use strict';

  /* ---------- page age (only on pages that contain #page-age) ---------- */

  function initPageAge() {
    var el = document.getElementById('page-age');
    if (!el) { return; }

    var startedAt = Date.now();
    var timer = null;
    var shown = '';

    function format(secs) {
      if (secs < 5) { return 'just now'; }
      if (secs < 60) { return secs + 's ago'; }
      var m = Math.floor(secs / 60);
      var s = secs % 60;
      if (m < 60) { return m + 'm ' + s + 's ago'; }
      var h = Math.floor(m / 60);
      return h + 'h ' + (m % 60) + 'm ago';
    }

    function update() {
      var text = format(Math.floor((Date.now() - startedAt) / 1000));
      if (text !== shown) {
        shown = text;
        el.textContent = text;
      }
    }

    function start() {
      if (timer === null) {
        update();
        timer = setInterval(update, 1000);
      }
    }

    function stop() {
      if (timer !== null) {
        clearInterval(timer);
        timer = null;
      }
    }

    // Do not tick while the tab is hidden; catch up when it is shown again.
    document.addEventListener('visibilitychange', function () {
      if (document.hidden) { stop(); } else { start(); }
    });

    start();
  }

  /* ---------- 3D tilt (mouse / pen only, never touch) ---------- */

  function initTilt() {
    if (!window.matchMedia) { return; }
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) { return; }
    if (!window.matchMedia('(hover: hover) and (pointer: fine)').matches) { return; }

    var MAX_DEG = 5;
    var items = document.querySelectorAll('[data-tilt]');

    Array.prototype.forEach.call(items, function (el) {
      var frame = 0;
      var px = 0;
      var py = 0;

      function apply() {
        frame = 0;
        var r = el.getBoundingClientRect();
        if (!r.width || !r.height) { return; }
        var x = (px - r.left) / r.width;
        var y = (py - r.top) / r.height;
        el.style.setProperty('--ry', ((x - 0.5) * 2 * MAX_DEG).toFixed(2) + 'deg');
        el.style.setProperty('--rx', ((0.5 - y) * 2 * MAX_DEG).toFixed(2) + 'deg');
        el.style.setProperty('--mx', (x * 100).toFixed(1) + '%');
        el.style.setProperty('--my', (y * 100).toFixed(1) + '%');
      }

      function reset() {
        if (frame) {
          cancelAnimationFrame(frame);
          frame = 0;
        }
        el.classList.remove('is-tilting');
        el.style.removeProperty('--rx');
        el.style.removeProperty('--ry');
        el.style.removeProperty('--mx');
        el.style.removeProperty('--my');
      }

      el.addEventListener('pointermove', function (e) {
        if (e.pointerType === 'touch') { return; }
        px = e.clientX;
        py = e.clientY;
        el.classList.add('is-tilting');
        if (!frame) { frame = requestAnimationFrame(apply); }
      });

      el.addEventListener('pointerleave', reset);
      el.addEventListener('pointercancel', reset);
    });
  }

  /* ---------- known/unknown chart widths ---------- */

  function initChartWidths() {
    var bars = document.querySelectorAll('[data-bar-width]');

    Array.prototype.forEach.call(bars, function (el) {
      var width = Number(el.getAttribute('data-bar-width'));
      if (!Number.isFinite(width)) { return; }
      width = Math.max(0, Math.min(100, width));
      el.style.width = width + '%';
    });
  }

  initPageAge();
  initTilt();
  initChartWidths();
})();
