document.addEventListener("DOMContentLoaded", function () {
  var data = window.expenseAnalytics;
  if (!data || typeof Chart === "undefined") return;

  var colors = ["#2d6cdf", "#48a27a", "#e3a73d", "#9b75ca", "#db6c76", "#4d9eaa"];
  function draw(id, type, labels, values, options) {
    var canvas = document.getElementById(id);
    if (!canvas) return;
    new Chart(canvas, {
      type: type,
      data: {
        labels: labels,
        datasets: [{
          data: values,
          backgroundColor: type === "line" ? "rgba(45,108,223,.12)" : colors,
          borderColor: type === "line" ? "#2d6cdf" : "#ffffff",
          borderWidth: type === "line" ? 2 : 1,
          fill: type === "line",
          tension: 0.28
        }]
      },
      options: Object.assign({
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: type === "doughnut", position: "bottom" } },
        scales: type === "doughnut" ? {} : {
          y: { beginAtZero: true, ticks: { callback: function (value) { return "₹" + value; } } }
        }
      }, options || {})
    });
  }

  if (data.monthly) {
    draw("monthlyChart", "line", data.monthly.labels, data.monthly.values);
    draw("dashboardMonthlyChart", "line", data.monthly.labels, data.monthly.values);
  }
  if (data.category) {
    draw("categoryChart", "bar", data.category.labels, data.category.values);
    draw("dashboardCategoryChart", "bar", data.category.labels, data.category.values);
  }
  if (data.status) draw("statusChart", "doughnut", data.status.labels, data.status.values);
  if (data.department) {
    draw("departmentChart", "bar", data.department.labels, data.department.values, {
      indexAxis: "y",
      scales: { x: { beginAtZero: true, ticks: { callback: function (value) { return "₹" + value; } } } }
    });
  }
});
