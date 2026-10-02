document.addEventListener("DOMContentLoaded", function () {
  var table = document.querySelector(".sortable-table");
  if (!table) return;

  table.querySelectorAll(".sort-button").forEach(function (button) {
    button.addEventListener("click", function () {
      var heading = button.closest("th");
      var column = Array.prototype.indexOf.call(heading.parentElement.children, heading);
      var body = table.tBodies[0];
      var rows = Array.prototype.slice.call(body.rows);
      var ascending = button.dataset.direction !== "asc";
      button.dataset.direction = ascending ? "asc" : "desc";
      rows.sort(function (left, right) {
        var a = left.cells[column].dataset.value || left.cells[column].textContent.trim();
        var b = right.cells[column].dataset.value || right.cells[column].textContent.trim();
        if (button.dataset.sort === "number") {
          a = parseFloat(a.replace(/[^\d.-]/g, "")) || 0;
          b = parseFloat(b.replace(/[^\d.-]/g, "")) || 0;
          return ascending ? a - b : b - a;
        }
        if (button.dataset.sort === "date") {
          a = Date.parse(a) || 0;
          b = Date.parse(b) || 0;
          return ascending ? a - b : b - a;
        }
        return ascending ? a.localeCompare(b) : b.localeCompare(a);
      });
      rows.forEach(function (row) { body.appendChild(row); });
    });
  });
});
