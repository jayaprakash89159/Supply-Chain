// Admin bulk delete on the supplier and subcontractor lists, and the delete button on profile pages.
// - [data-select-all] ticks every row checkbox on the page.
// - The "Delete selected" button shows how many rows are ticked and stays disabled until one is.
// - Every form with data-confirm-delete asks for confirmation before it is sent.
(function () {
  'use strict';
  var form = document.getElementById('bulk-delete');
  if (form) {
    var boxes = Array.prototype.slice.call(document.querySelectorAll('input[name="ids"][form="bulk-delete"]'));
    var selectAll = document.querySelector('[data-select-all]');
    var button = form.querySelector('[data-delete-button]');
    var count = form.querySelector('[data-selected-count]');

    var refresh = function () {
      var ticked = boxes.filter(function (box) { return box.checked; }).length;
      count.textContent = ticked;
      button.disabled = ticked === 0;
      if (selectAll) {
        selectAll.checked = ticked > 0 && ticked === boxes.length;
        selectAll.indeterminate = ticked > 0 && ticked < boxes.length;
      }
      boxes.forEach(function (box) { box.closest('tr').classList.toggle('row-selected', box.checked); });
    };

    boxes.forEach(function (box) { box.addEventListener('change', refresh); });
    if (selectAll) {
      selectAll.addEventListener('change', function () {
        boxes.forEach(function (box) { box.checked = selectAll.checked; });
        refresh();
      });
    }
    refresh();
  }

  document.querySelectorAll('form[data-confirm-delete]').forEach(function (deleteForm) {
    deleteForm.addEventListener('submit', function (event) {
      var ticked = deleteForm.id === 'bulk-delete'
        ? document.querySelectorAll('input[name="ids"][form="bulk-delete"]:checked').length
        : 1;
      var message = deleteForm.getAttribute('data-confirm-delete').replace('{n}', ticked);
      if (!window.confirm(message + '\n\nThis permanently deletes the data and cannot be undone.')) {
        event.preventDefault();
      }
    });
  });
})();
