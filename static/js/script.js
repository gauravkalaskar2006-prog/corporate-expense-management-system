document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll("[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });

  document.querySelectorAll(".alert").forEach(function (alert) {
    window.setTimeout(function () {
      alert.classList.add("alert-dismissed");
      alert.style.transition = "opacity 180ms ease";
      alert.style.opacity = "0";
      window.setTimeout(function () { alert.remove(); }, 200);
    }, 6500);
  });
});
