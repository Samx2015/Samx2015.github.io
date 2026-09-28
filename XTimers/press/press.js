(() => {
  let feedbackTimer;
  const status = document.getElementById('copy-status');
  document.querySelectorAll('[data-copy-target]').forEach(button => {
    button.addEventListener('click', async () => {
      const target = document.getElementById(button.dataset.copyTarget);
      if (!target) return;
      const text = target.innerText.trim();
      try {
        if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
        await navigator.clipboard.writeText(text);
        status.textContent = 'Description copied.';
      } catch {
        const selection = window.getSelection();
        const range = document.createRange();
        range.selectNodeContents(target);
        selection.removeAllRanges();
        selection.addRange(range);
        status.textContent = 'Text selected. Use Copy to copy the description.';
      }
      window.clearTimeout(feedbackTimer);
      feedbackTimer = window.setTimeout(() => { status.textContent = ''; }, 5000);
    });
  });
})();
