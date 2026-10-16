// GSTIN helper for supplier and subcontractor pages.
// - Form pages: validates the GSTIN while typing and fills GST State Code, PAN and State.
// - Any page: buttons with data-gst-check copy the GSTIN and open the official GST portal search,
//   where the user enters the captcha (the portal cannot be queried directly).
(function () {
  'use strict';
  var configElement = document.getElementById('gst-config');
  if (!configElement) return;
  var config = JSON.parse(configElement.textContent);
  var CHARS = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ';
  var PATTERN = /^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;

  function normalise(value) { return String(value || '').replace(/\s/g, '').toUpperCase(); }

  function checkCharacter(gstin) {
    var total = 0;
    for (var i = 0; i < 14; i++) {
      var product = CHARS.indexOf(gstin[i]) * (i % 2 === 0 ? 1 : 2);
      total += Math.floor(product / 36) + (product % 36);
    }
    return CHARS[(36 - (total % 36)) % 36];
  }

  function inspect(value) {
    var gstin = normalise(value);
    if (!gstin) return { status: 'empty' };
    if (gstin.length < 15) return { status: 'typing', message: gstin.length + ' of 15 characters' };
    if (!PATTERN.test(gstin)) return { status: 'invalid_format', message: 'Not a valid GSTIN format.' };
    var info = { gstin: gstin, stateCode: gstin.slice(0, 2), state: config.states[gstin.slice(0, 2)] || '', pan: gstin.slice(2, 12) };
    var expected = checkCharacter(gstin);
    if (expected !== gstin[14]) {
      info.status = 'check_mismatch';
      info.message = 'Check character should be "' + expected + '", not "' + gstin[14] + '" - possible typo. Verify on the GST portal.';
    } else if (!info.state) {
      info.status = 'invalid_format';
      info.message = 'Unknown GST state code ' + info.stateCode + '.';
    } else {
      info.status = 'ok';
      info.message = 'Valid format · ' + info.state + ' · PAN ' + info.pan;
    }
    return info;
  }

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text).then(function () { return true; }, function () { return legacyCopy(text); });
    }
    return Promise.resolve(legacyCopy(text));
  }

  function legacyCopy(text) {
    var area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    var copied = false;
    try { copied = document.execCommand('copy'); } catch (error) { copied = false; }
    document.body.removeChild(area);
    return copied;
  }

  function openPortal(gstin, statusElement) {
    // Copy before opening: the new tab takes focus, and browsers only copy from the focused page.
    var copied = gstin ? legacyCopy(gstin) : false;
    // ('noopener' would make window.open return null, hiding a real pop-up block, so detach manually.)
    var portal = window.open(config.portal, '_blank');
    if (portal) portal.opener = null;
    if (!portal) {
      setStatus(statusElement, 'warn', 'Your browser blocked the new tab. Allow pop-ups for this site, or open ' + config.portal);
    } else if (!gstin) {
      setStatus(statusElement, 'info', 'GST portal opened. Enter the GSTIN and captcha there.');
    } else if (copied) {
      setStatus(statusElement, 'info', 'GSTIN ' + gstin + ' copied. In the GST portal: paste it (Ctrl+V), type the captcha, press Search.');
    } else {
      setStatus(statusElement, 'info', 'GST portal opened. Type ' + gstin + ' there, then the captcha.');
      copyText(gstin).then(function (done) {
        if (done) setStatus(statusElement, 'info', 'GSTIN ' + gstin + ' copied. In the GST portal: paste it (Ctrl+V), type the captcha, press Search.');
      });
    }
  }

  function setStatus(element, kind, message) {
    if (!element) return;
    element.className = 'gstin-status ' + kind;
    element.textContent = message || '';
  }

  function cleanStateName(name) { return name.replace(/\s*\(.*\)$/, ''); }

  function attachToForm(input) {
    var form = input.form;
    var field = function (name) { return form.querySelector('[name="' + name + '"]'); };
    var stateCode = field('gst_state_code'), pan = field('pan'), state = field('state');

    var tools = document.createElement('div');
    tools.className = 'gstin-tools';
    tools.innerHTML = '<button type="button" class="button small">Check on GST portal <span aria-hidden="true">↗</span></button>'
      + '<button type="button" class="text-button gstin-fill" hidden>Fill state code, PAN &amp; state from GSTIN</button>'
      + '<span class="gstin-status" aria-live="polite"></span>';
    input.insertAdjacentElement('afterend', tools);
    var statusElement = tools.querySelector('.gstin-status');
    var fillButton = tools.querySelector('.gstin-fill');

    function differences(info) {
      var notes = [];
      if (stateCode && stateCode.value && stateCode.value !== info.stateCode) notes.push('GST State Code');
      if (pan && pan.value && normalise(pan.value) !== info.pan) notes.push('PAN');
      return notes;
    }

    function fill(info, overwrite) {
      if (stateCode && (overwrite || !stateCode.value)) stateCode.value = info.stateCode;
      if (pan && (overwrite || !pan.value)) pan.value = info.pan;
      if (state && (overwrite || !state.value)) state.value = cleanStateName(info.state);
    }

    function update(autoFill) {
      var info = inspect(input.value);
      fillButton.hidden = true;
      if (info.status === 'empty') return setStatus(statusElement, '', '');
      if (info.status === 'typing') return setStatus(statusElement, '', info.message);
      if (info.status === 'invalid_format') return setStatus(statusElement, 'error', info.message);
      if (autoFill) fill(info, false);
      var notes = differences(info);
      if (notes.length) {
        fillButton.hidden = false;
        return setStatus(statusElement, 'warn', info.message + ' · ' + notes.join(' and ') + ' differ from the GSTIN.');
      }
      setStatus(statusElement, info.status === 'ok' ? 'ok' : 'warn', info.message);
    }

    input.addEventListener('input', function () { update(true); });
    input.addEventListener('blur', function () {
      var cleaned = normalise(input.value);
      if (cleaned !== input.value) input.value = cleaned;
      update(true);
    });
    fillButton.addEventListener('click', function () { fill(inspect(input.value), true); update(false); });
    tools.querySelector('.button').addEventListener('click', function () {
      var info = inspect(input.value);
      openPortal(info.gstin || normalise(input.value), statusElement);
    });
    update(false);
  }

  document.querySelectorAll('form input[name="gstin"]').forEach(attachToForm);
  document.querySelectorAll('[data-gst-check]').forEach(function (button) {
    button.addEventListener('click', function () {
      var statusElement = button.parentElement.querySelector('.gstin-status');
      openPortal(normalise(button.getAttribute('data-gst-check')), statusElement);
    });
  });
})();
