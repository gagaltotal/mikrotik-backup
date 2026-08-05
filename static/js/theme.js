(function () {
  const stored = localStorage.getItem('theme');
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)');
  const theme = stored || (prefersDark.matches ? 'dark' : 'light');
  document.documentElement.classList.toggle('dark', theme === 'dark');

  function updateThemeClass(event) {
    document.documentElement.classList.toggle('dark', event.matches);
  }

  if (!stored) {
    prefersDark.addEventListener('change', updateThemeClass);
  }
})();
