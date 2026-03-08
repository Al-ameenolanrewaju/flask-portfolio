$(document).ready(function(){

    $('a[href^="#"]').on('click', function(e) {
        e.preventDefault();

        var target = this.hash;
        var $target = $(target);

        $('html, body').animate({
            scrollTop: $target.offset().top - 60
        }, 800);
    });

});
$(window).on('scroll', function() {

    var scrollPos = $(document).scrollTop();

    $('.nav-item a').each(function () {
        var currLink = $(this);
        var refElement = $(currLink.attr("href"));

        if (refElement.position().top - 80 <= scrollPos &&
            refElement.position().top + refElement.height() > scrollPos) {

            $('.nav-item').removeClass("active");
            currLink.parent().addClass("active");

        }
    });

});