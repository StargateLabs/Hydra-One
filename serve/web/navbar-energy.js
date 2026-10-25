/* Decorate labels without replacing buttons, icons or their event handlers. */
(() => {
  const selector = '.st-header .st-tab';
  function decorate(button) {
    for (const node of [...button.childNodes]) {
      if (node.nodeType === Node.TEXT_NODE && node.textContent.trim()) {
        const label = document.createElement('span');
        label.className = 'st-nav-energy-label';
        node.replaceWith(label);
        label.append(node);
      } else if (node.nodeType === Node.ELEMENT_NODE && node.tagName === 'SPAN' && !node.classList.contains('st-nav-liquid')) {
        node.classList.add('st-nav-energy-label');
      }
    }
    button.classList.add('st-nav-energy');

  }
  function start() {
    const buttons = [...document.querySelectorAll(selector)];
    buttons.forEach((button, index) => {
      button.style.setProperty('--nav-energy-delay', `${index * -0.62}s`);
      decorate(button);
      // Translation may replace a label. Rewrap only fresh direct text nodes.
      new MutationObserver(() => decorate(button)).observe(button, { childList: true });
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true });
  else start();
})();
