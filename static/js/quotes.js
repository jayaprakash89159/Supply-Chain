// Request-quotes page: live preview for each vendor, placeholder buttons, send count and confirmation.
(function () {
  'use strict';
  var form = document.querySelector('[data-quote-form]');
  if (!form) return;
  var subject = form.querySelector('[name="subject"]');
  var body = form.querySelector('[name="body"]');
  var requirement = form.querySelector('[name="requirement"]');
  var vendors = Array.prototype.slice.call(form.querySelectorAll('[data-vendor]'));
  var select = form.querySelector('[data-preview-select]');
  var yourName = JSON.parse(document.getElementById('quote-your-name').textContent);
  var lastFocused = body;
  var due = form.querySelector('[name="due_date"]');
  var itemBody = form.querySelector('[data-item-rows]');
  var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  function itemRows() { return Array.prototype.slice.call(itemBody.querySelectorAll('[data-item-row]')); }

  function requirementText() {
    var lines = [];
    itemRows().forEach(function (row) {
      var d = row.querySelector('[name="item_description"]').value.trim();
      var q = row.querySelector('[name="item_quantity"]').value.trim();
      var u = row.querySelector('[name="item_unit"]').value.trim();
      if (d || q) lines.push((lines.length + 1) + '. ' + d + ' – ' + (q + ' ' + u).trim());
    });
    var notes = requirement.value.trim();
    if (notes) { if (lines.length) lines.push(''); lines.push(notes); }
    return lines.join('\n');
  }

  function dueText() {
    if (!due || !due.value) return 'as early as possible';
    var parts = due.value.split('-');
    return parts[2] + ' ' + MONTHS[Number(parts[1]) - 1] + ' ' + parts[0];
  }

  function renumber() {
    itemRows().forEach(function (row, index) { row.querySelector('.item-no').textContent = index + 1; });
  }

  function addRow(values) {
    var template = itemRows()[0];
    var row = template.cloneNode(true);
    row.querySelectorAll('input').forEach(function (input, index) { input.value = (values && values[index]) || ''; });
    itemBody.appendChild(row);
    wireRow(row);
    renumber();
    return row;
  }

  function wireRow(row) {
    row.querySelectorAll('input').forEach(function (input) { input.addEventListener('input', preview); });
    row.querySelector('[data-remove-item]').addEventListener('click', function () {
      if (itemRows().length > 1) row.remove(); else row.querySelectorAll('input').forEach(function (input) { input.value = ''; });
      renumber();
      preview();
    });
    // Rows copied from Excel arrive as tab-separated lines: description, quantity, unit.
    row.querySelector('[name="item_description"]').addEventListener('paste', function (event) {
      var text = (event.clipboardData || window.clipboardData).getData('text');
      if (text.indexOf('\t') === -1 && text.indexOf('\n') === -1) return;
      event.preventDefault();
      var lines = text.replace(/\r/g, '').split('\n').filter(function (line) { return line.trim(); });
      var target = row;
      lines.forEach(function (line, index) {
        var cells = line.split('\t').map(function (cell) { return cell.trim(); });
        if (index > 0) target = addRow();
        target.querySelectorAll('input').forEach(function (input, i) { input.value = cells[i] || ''; });
      });
      preview();
    });
  }

  function fill(text, box) {
    var values = {
      '{vendor_name}': box.dataset.name,
      '{contact_person}': box.dataset.contact || 'Sir/Madam',
      '{vendor_code}': box.dataset.code,
      '{city}': box.dataset.city,
      '{requirement}': requirementText(),
      '{quote_link}': '[' + box.dataset.name + '’s personal quote link]',
      '{due_date}': dueText(),
      '{your_name}': yourName
    };
    Object.keys(values).forEach(function (token) { text = text.split(token).join(values[token]); });
    return text;
  }

  function preview() {
    var box = vendors[Number(select.value)] || vendors[0];
    if (!box) return;
    form.querySelector('[data-preview-subject]').textContent = 'Subject: ' + fill(subject.value, box);
    form.querySelector('[data-preview-body]').textContent = fill(body.value, box);
  }

  function counts() {
    var ticked = vendors.filter(function (box) { return box.checked; });
    var emailable = ticked.filter(function (box) { return box.dataset.hasEmail; }).length;
    form.querySelector('[data-vendor-count]').textContent = ticked.length;
    form.querySelector('[data-send-count]').textContent = emailable;
    var send = form.querySelector('[data-send-button]');
    if (!send.hasAttribute('data-off')) send.disabled = emailable === 0 || send.hasAttribute('data-unconfigured');
  }

  var sendButton = form.querySelector('[data-send-button]');
  if (sendButton.disabled) sendButton.setAttribute('data-unconfigured', '');

  [subject, body, requirement].forEach(function (field) {
    field.addEventListener('input', preview);
    field.addEventListener('focus', function () { if (field !== requirement) lastFocused = field; });
  });
  select.addEventListener('change', preview);
  if (due) due.addEventListener('input', preview);
  itemRows().forEach(wireRow);
  form.querySelector('[data-add-item]').addEventListener('click', function () { addRow().querySelector('input').focus(); });
  renumber();
  vendors.forEach(function (box) { box.addEventListener('change', counts); });

  form.querySelectorAll('[data-insert]').forEach(function (button) {
    button.addEventListener('click', function () {
      var field = lastFocused;
      var token = button.dataset.insert;
      var start = field.selectionStart, end = field.selectionEnd;
      field.value = field.value.slice(0, start) + token + field.value.slice(end);
      field.focus();
      field.selectionStart = field.selectionEnd = start + token.length;
      preview();
    });
  });

  form.addEventListener('submit', function (event) {
    if (!event.submitter || event.submitter.value !== 'send') return;
    var n = form.querySelector('[data-send-count]').textContent;
    if (!window.confirm('Send ' + n + ' separate email(s) now? Each vendor receives only their own email.')) {
      event.preventDefault();
    }
  });

  preview();
  counts();
})();
