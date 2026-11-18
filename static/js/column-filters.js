// Excel-style filter and sort menus on the directory list headings.
// Menu data comes from the #column-menus JSON written by the page; choices are applied by reloading the
// page with f_<column>=value parameters, so the server filters, pages and exports the same rows.
(function () {
  'use strict';
  var dataElement = document.getElementById('column-menus');
  if (!dataElement) return;
  var menus = JSON.parse(dataElement.textContent);
  var open = null;

  function el(tag, attrs, text) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (key) { node.setAttribute(key, attrs[key]); });
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function go(params) {
    params.delete('page');
    var query = params.toString();
    window.location.search = query ? '?' + query : '';
  }

  function close() {
    if (!open) return;
    open.button.setAttribute('aria-expanded', 'false');
    open.panel.remove();
    open = null;
  }

  function build(button, key) {
    var menu = menus[key];
    var params = new URLSearchParams(window.location.search);
    var panel = el('div', { 'class': 'col-menu', role: 'dialog', 'aria-label': 'Filter ' + button.textContent.trim() });

    if (menu.sortable) {
      [['', menu.number ? 'Sort smallest → largest' : 'Sort A → Z'], ['-', menu.number ? 'Sort largest → smallest' : 'Sort Z → A']].forEach(function (option) {
        var sort = el('button', { type: 'button', 'class': 'col-menu-action' }, option[1]);
        sort.addEventListener('click', function () { params.set('sort', option[0] + key); go(params); });
        panel.appendChild(sort);
      });
    }
    if (params.getAll(menu.param).length) {
      var clear = el('button', { type: 'button', 'class': 'col-menu-action' }, 'Clear filter from this column');
      clear.addEventListener('click', function () { params.delete(menu.param); go(params); });
      panel.appendChild(clear);
    }

    var search = el('input', { type: 'search', 'class': 'col-menu-search', placeholder: 'Search values…', 'aria-label': 'Search values' });
    panel.appendChild(search);

    var list = el('div', { 'class': 'col-menu-list' });
    var allLabel = el('label', { 'class': 'col-menu-all' });
    var all = el('input', { type: 'checkbox' });
    allLabel.appendChild(all);
    allLabel.appendChild(document.createTextNode(' (Select all)'));
    list.appendChild(allLabel);

    var items = menu.values.map(function (value) {
      var label = el('label', { title: value.l });
      var box = el('input', { type: 'checkbox', value: value.v });
      box.checked = value.on;
      label.appendChild(box);
      label.appendChild(el('span', {}, ' ' + value.l));
      label.appendChild(el('small', {}, String(value.n)));
      list.appendChild(label);
      return { value: value, label: label, box: box };
    });
    if (!items.length) list.appendChild(el('p', { 'class': 'col-menu-empty' }, 'No values in the current results.'));
    panel.appendChild(list);

    var shown = function () { return items.filter(function (item) { return !item.label.hidden; }); };
    var syncAll = function () {
      var visible = shown();
      var ticked = visible.filter(function (item) { return item.box.checked; }).length;
      all.checked = visible.length > 0 && ticked === visible.length;
      all.indeterminate = ticked > 0 && ticked < visible.length;
      ok.disabled = !items.some(function (item) { return item.box.checked && !item.label.hidden; });
    };
    all.addEventListener('change', function () {
      shown().forEach(function (item) { item.box.checked = all.checked; });
      syncAll();
    });
    items.forEach(function (item) { item.box.addEventListener('change', syncAll); });
    search.addEventListener('input', function () {
      var needle = search.value.trim().toLowerCase();
      items.forEach(function (item) {
        item.label.hidden = needle !== '' && item.value.l.toLowerCase().indexOf(needle) === -1;
        // As in Excel, searching selects just the matching values.
        if (needle !== '') item.box.checked = !item.label.hidden;
      });
      syncAll();
    });

    var actions = el('div', { 'class': 'col-menu-buttons' });
    var ok = el('button', { type: 'button', 'class': 'button primary small' }, 'OK');
    var cancel = el('button', { type: 'button', 'class': 'button small' }, 'Cancel');
    actions.appendChild(ok);
    actions.appendChild(cancel);
    panel.appendChild(actions);

    ok.addEventListener('click', function () {
      var chosen = items.filter(function (item) { return item.box.checked && !item.label.hidden; });
      params.delete(menu.param);
      if (chosen.length < items.length) {
        chosen.forEach(function (item) { params.append(menu.param, item.value.v); });
      }
      go(params);
    });
    cancel.addEventListener('click', close);
    panel.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') { close(); button.focus(); }
      if (event.key === 'Enter' && event.target === search && !ok.disabled) ok.click();
    });

    syncAll();
    return { panel: panel, search: search };
  }

  function place(panel, button) {
    var rect = button.getBoundingClientRect();
    var width = panel.offsetWidth;
    var left = Math.min(rect.left + window.scrollX, window.scrollX + document.documentElement.clientWidth - width - 8);
    panel.style.left = Math.max(8, left) + 'px';
    panel.style.top = (rect.bottom + window.scrollY + 4) + 'px';
  }

  document.querySelectorAll('.col-button').forEach(function (button) {
    button.addEventListener('click', function (event) {
      event.stopPropagation();
      var key = button.getAttribute('data-col');
      var same = open && open.button === button;
      close();
      if (same) return;
      var built;
      if (menus[key]) {
        built = build(button, key);
      } else {
        // Sort-only column.
        var params = new URLSearchParams(window.location.search);
        built = { panel: el('div', { 'class': 'col-menu', role: 'dialog' }), search: null };
        [['', 'Sort ascending'], ['-', 'Sort descending']].forEach(function (option) {
          var sort = el('button', { type: 'button', 'class': 'col-menu-action' }, option[1]);
          sort.addEventListener('click', function () { params.set('sort', option[0] + key); go(params); });
          built.panel.appendChild(sort);
        });
      }
      document.body.appendChild(built.panel);
      place(built.panel, button);
      button.setAttribute('aria-expanded', 'true');
      open = { button: button, panel: built.panel };
      (built.search || built.panel.querySelector('button')).focus();
    });
  });

  document.addEventListener('click', function (event) {
    if (open && !open.panel.contains(event.target)) close();
  });
  // Close when the window gets narrower or wider, but not when a phone keyboard opens (height-only change).
  var lastWidth = window.innerWidth;
  window.addEventListener('resize', function () {
    if (window.innerWidth !== lastWidth) close();
    lastWidth = window.innerWidth;
  });
})();
