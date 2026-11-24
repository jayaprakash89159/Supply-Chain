// Admin bulk actions on the supplier and subcontractor lists, and the delete button on profile pages.
// - [data-select-all] ticks every row checkbox on the page.
// - Bulk buttons stay disabled until a row is ticked; "Set status" also needs a status chosen.
// - Buttons with data-confirm, and forms with data-confirm-delete, ask before they are sent.
(function () {
  'use strict';
  var IRREVERSIBLE = '\n\nThey move to the Recycle bin, where an administrator can restore them.';
  var form = document.getElementById('bulk-actions');

  if (form) {
    var boxes = Array.prototype.slice.call(document.querySelectorAll('input[type="checkbox"][form="bulk-actions"]'));
    var selectAlls = Array.prototype.slice.call(document.querySelectorAll('[data-select-all]'));
    var buttons = Array.prototype.slice.call(form.querySelectorAll('[data-bulk-button]'));
    var count = form.querySelector('[data-selected-count]');
    var status = form.querySelector('select[name="status"]');

    var ticked = function () { return boxes.filter(function (box) { return box.checked; }).length; };
    // Each "select all" box controls the rows of its own table (the search page has two tables).
    var rowsOf = function (selectAll) {
      var table = selectAll.closest('table');
      return boxes.filter(function (box) { return box.closest('table') === table; });
    };

    var refresh = function () {
      var n = ticked();
      count.textContent = n;
      buttons.forEach(function (button) {
        button.disabled = n === 0 || (button.hasAttribute('data-needs-status') && !(status && status.value));
      });
      selectAlls.forEach(function (selectAll) {
        var rows = rowsOf(selectAll);
        var on = rows.filter(function (box) { return box.checked; }).length;
        selectAll.checked = on > 0 && on === rows.length;
        selectAll.indeterminate = on > 0 && on < rows.length;
      });
      boxes.forEach(function (box) { box.closest('tr').classList.toggle('row-selected', box.checked); });
    };

    boxes.forEach(function (box) { box.addEventListener('change', refresh); });
    if (status) status.addEventListener('change', refresh);
    selectAlls.forEach(function (selectAll) {
      selectAll.addEventListener('change', function () {
        rowsOf(selectAll).forEach(function (box) { box.checked = selectAll.checked; });
        refresh();
      });
    });
    form.addEventListener('submit', function (event) {
      var button = event.submitter;
      var question = button && button.getAttribute('data-confirm');
      var note = button.hasAttribute('data-confirm-final') ? '' : IRREVERSIBLE;
      if (question && !window.confirm(question.replace('{n}', ticked()) + note)) {
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
