(function () {
  var body = document.body;
  var btn = document.getElementById("menuBtn");
  if (btn) {
    btn.addEventListener("click", function () { body.classList.toggle("nav-open"); });
    document.addEventListener("click", function (e) {
      if (body.classList.contains("nav-open") && !e.target.closest("#sidebar") && !e.target.closest("#menuBtn")) {
        body.classList.remove("nav-open");
      }
    });
  }
  document.querySelectorAll(".toast-msg").forEach(function (t) {
    var close = t.querySelector("button");
    if (close) close.addEventListener("click", function () { t.remove(); });
    setTimeout(function () { t.remove(); }, 6000);
  });
  document.querySelectorAll("form[data-confirm]").forEach(function (f) {
    f.addEventListener("submit", function (e) { if (!confirm(f.dataset.confirm)) e.preventDefault(); });
  });
})();
