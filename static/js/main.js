document.addEventListener('DOMContentLoaded', function () {
    var links = Array.prototype.slice.call(document.querySelectorAll('.nav-item a[href^="#"]'));
    var sections = Array.prototype.slice.call(document.querySelectorAll('main section[id], body > section[id]'));

    links.forEach(function (link) {
        link.addEventListener('click', function (event) {
            var target = document.querySelector(link.getAttribute('href'));
            if (!target) return;
            event.preventDefault();
            target.scrollIntoView({ behavior: 'smooth', block: 'start' });

            var collapse = document.querySelector('#mainNavbar');
            if (collapse && collapse.classList.contains('in') && window.jQuery) {
                window.jQuery(collapse).collapse('hide');
            }
        });
    });

    if (!sections.length || !('IntersectionObserver' in window)) return;

    var observer = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
            if (!entry.isIntersecting) return;
            links.forEach(function (link) {
                var active = link.getAttribute('href') === '#' + entry.target.id;
                link.parentElement.classList.toggle('active', active);
            });
        });
    }, { rootMargin: '-35% 0px -55% 0px' });

    sections.forEach(function (section) { observer.observe(section); });
});