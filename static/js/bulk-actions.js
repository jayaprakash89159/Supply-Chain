// Admin bulk actions on the supplier and subcontractor lists, and the delete button on profile pages.
// - [data-select-all] ticks every row checkbox on the page.
// - Bulk buttons stay disabled until a row is ticked; "Set status" also needs a status chosen.
// - Buttons with data-confirm, and forms with data-confirm-delete, ask before they are sent.
(function () {
  'use strict';
  var IRREVERSIBLE = '\n\nThis permanently deletes the data and cannot be undone.';
  var form = document.getElementById('bulk-actions');

  if (form) {
    var boxes = Array.prototype.slice.call(document.querySelectorAll('input[name="ids"][form="bulk-actions"]'));
    var selectAll = document.querySelector('[data-select-all]');
    var buttons = Array.prototype.slice.call(form.querySelectorAll('[data-bulk-button]'));
    var count = form.querySelector('[data-selected-count]');
    var status = form.querySelector('select[name="status"]');

    var ticked = function () { return boxes.filter(function (box) { return box.checked; }).length; };

    var refresh = function () {
      var n = ticked();
      count.textContent = n;
      buttons.forEach(function (button) {
        button.disabled = n === 0 || (button.hasAttribute('data-needs-status') && !status.value);
      });
      if (selectAll) {
        selectAll.checked = n > 0 && n === boxes.length;
        selectAll.indeterminate = n > 0 && n < boxes.length;
      }
      boxes.forEach(function (box) { box.closest('tr').classList.toggle('row-selected', box.checked); });
    };

    boxes.forEach(function (box) { box.addEventListener('change', refresh); });
    status.addEventListener('change', refresh);
    if (selectAll) {
      selectAll.addEventListener('change', function () {
        boxes.forEach(function (box) { box.checked = selectAll.checked; });
        refresh();
      });
    }
    form.addEventListener('submit', function (event) {
      var button = event.submitter;
      var question = button && button.getAttribute('data-confirm');
      if (question && !window.confirm(question.replace('{n}', ticked()) + IRREVERSIBLE)) {
        event.preventDefault();
      }
    });
    refresh();
  }

  document.querySelectorAll('form[data-confirm-delete]').forEach(function (deleteForm) {
    deleteForm.addEventListener('submit', function (event) {
      if (!window.confirm(deleteForm.getAttribute('data-confirm-delete') + IRREVERSIBLE)) {
        event.preventDefault();
      }
    });
  });
})();
