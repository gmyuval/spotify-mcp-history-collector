/**
 * Theme toggle + ECharts theme sync.
 *
 * Usage:
 *   SpotifyMCP.getEchartsTheme()    — returns 'dark' or null (ECharts default light)
 *   SpotifyMCP.onThemeChange(fn)    — register callback(theme) for live toggles
 */
(function () {
  'use strict';

  var listeners = [];

  function currentTheme() {
    return document.documentElement.getAttribute('data-bs-theme') || 'dark';
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute('data-bs-theme', theme);
    localStorage.setItem('theme', theme);
    syncIcons(theme);
    for (var i = 0; i < listeners.length; i++) {
      listeners[i](theme);
    }
  }

  function syncIcons(theme) {
    var sun = document.getElementById('themeIconSun');
    var moon = document.getElementById('themeIconMoon');
    if (!sun || !moon) return;
    // Show sun icon in dark mode (click to switch to light), moon in light mode
    sun.style.display = theme === 'dark' ? 'block' : 'none';
    moon.style.display = theme === 'light' ? 'block' : 'none';
  }

  function toggle() {
    applyTheme(currentTheme() === 'dark' ? 'light' : 'dark');
  }

  // Initialize icons on load
  function init() {
    syncIcons(currentTheme());
    var btn = document.getElementById('themeToggle');
    if (btn) btn.addEventListener('click', toggle);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // Public API
  window.SpotifyMCP = window.SpotifyMCP || {};
  window.SpotifyMCP.getEchartsTheme = function () {
    return currentTheme() === 'dark' ? 'dark' : null;
  };
  window.SpotifyMCP.onThemeChange = function (fn) {
    listeners.push(fn);
  };
})();
