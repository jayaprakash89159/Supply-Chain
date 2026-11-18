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

  function fill(text, box) {
    var values = {
      '{vendor_name}': box.dataset.name,
      '{contact_person}': box.dataset.contact || 'Sir/Madam',
      '{vendor_code}': box.dataset.code,
      '{city}': box.dataset.city,
      '{requirement}': requirement.value.trim(),
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
