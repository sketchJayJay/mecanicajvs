(function () {
  function normalize(value) {
    return (value || '')
      .toString()
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .toLowerCase()
      .trim();
  }

  function initClientSearch(root) {
    const input = root.querySelector('[data-client-input]');
    const hidden = root.querySelector('[data-client-id]');
    const results = root.querySelector('[data-client-results]');
    const empty = root.querySelector('[data-client-empty]');
    const vehicle = document.getElementById(root.dataset.vehicleTarget || '');
    const form = root.closest('form');
    const items = [...root.querySelectorAll('[data-client-option]')];

    if (!input || !hidden || !results) return;

    function filterVehicles() {
      if (!vehicle) return;
      const clientId = hidden.value;
      [...vehicle.options].forEach((option, index) => {
        if (index === 0) return;
        option.hidden = !!clientId && option.dataset.client !== clientId;
      });
      if (vehicle.selectedOptions[0]?.hidden) vehicle.value = '';
    }

    function closeResults() {
      results.classList.remove('open');
    }

    function showResults() {
      const query = normalize(input.value);
      let visible = 0;

      items.forEach(item => {
        const match = query && normalize(item.dataset.search).includes(query);
        const show = match && visible < 10;
        item.hidden = !show;
        if (show) visible += 1;
      });

      if (empty) empty.hidden = !(query && visible === 0);
      if (query) results.classList.add('open');
      else closeResults();
    }

    function clearSelectionIfTyping() {
      if (hidden.value) {
        hidden.value = '';
        filterVehicles();
      }
    }

    input.addEventListener('input', () => {
      clearSelectionIfTyping();
      showResults();
    });

    input.addEventListener('focus', showResults);

    items.forEach(item => {
      item.addEventListener('click', () => {
        hidden.value = item.dataset.id;
        input.value = item.dataset.label;
        closeResults();
        filterVehicles();
        input.classList.remove('field-error');
      });
    });

    document.addEventListener('click', event => {
      if (!root.contains(event.target)) closeResults();
    });

    if (form) {
      form.addEventListener('submit', event => {
        if (!hidden.value) {
          event.preventDefault();
          input.classList.add('field-error');
          input.focus();
          input.setCustomValidity('Busque e selecione um cliente da lista.');
          input.reportValidity();
          input.setCustomValidity('');
          showResults();
        }
      });
    }

    filterVehicles();
  }

  document.querySelectorAll('[data-client-search]').forEach(initClientSearch);
})();
