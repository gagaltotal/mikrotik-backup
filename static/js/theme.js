(function () {
  const root = document.documentElement;
  const media = window.matchMedia('(prefers-color-scheme: dark)');

  function applyTheme(theme) {
    const isDark = theme === 'dark';
    root.classList.toggle('dark', isDark);
    root.style.colorScheme = isDark ? 'dark' : 'light';
  }

  // Initial theme: saved preference, otherwise follow the OS setting.
  const stored = localStorage.getItem('theme');
  applyTheme(stored || (media.matches ? 'dark' : 'light'));

  // Shared helpers so the toggle button (app.js) always persists the choice.
  window.getTheme = function () {
    return root.classList.contains('dark') ? 'dark' : 'light';
  };
  window.setTheme = function (theme) {
    applyTheme(theme);
    localStorage.setItem('theme', theme);
  };

  // Follow OS changes only while the user has not picked a theme manually.
  media.addEventListener('change', function (event) {
    if (!stored) {
      applyTheme(event.matches ? 'dark' : 'light');
    }
  });

  // Make Tailwind's dark: variants react to the `.dark` class instead of the
  // OS preference (the Play CDN defaults to `media`). This runs after the CDN
  // script has been parsed so `window.tailwind` exists and re-builds the CSS.
  function configureTailwind() {
    if (window.tailwind) {
      window.tailwind.config = { darkMode: 'class' };
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', configureTailwind);
  } else {
    configureTailwind();
  }
})();
