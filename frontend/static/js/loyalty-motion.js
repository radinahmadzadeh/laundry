// Loyalty club card motion (home order form and account dashboard): once the card is in view its
// progress bar fills, the amount bought this period counts up and the gift pops.
(function(){
    var cards = document.querySelectorAll('.loyalty-card');
    if (!cards.length || window.matchMedia('(prefers-reduced-motion: reduce)').matches || !('IntersectionObserver' in window)) return;

    function fa(n){
        return Math.round(n).toLocaleString('en-US').replace(/,/g, '٬').replace(/\d/g, function(d){ return '۰۱۲۳۴۵۶۷۸۹'[d]; });
    }
    function countUp(el){
        var target = parseFloat(el.getAttribute('data-loyalty-count')) || 0;
        if (!target) return;
        var start = null, dur = 1200;
        el.textContent = fa(0);
        function tick(now){
            if (start === null) start = now;
            var t = Math.min(1, (now - start) / dur), eased = 1 - Math.pow(1 - t, 3);
            el.textContent = fa(target * eased);
            if (t < 1) requestAnimationFrame(tick);
        }
        setTimeout(function(){ requestAnimationFrame(tick); }, 250);
    }

    var io = new IntersectionObserver(function(entries){
        entries.forEach(function(e){
            if (!e.isIntersecting) return;
            io.unobserve(e.target);
            e.target.classList.add('is-live');
            e.target.querySelectorAll('[data-loyalty-count]').forEach(countUp);
        });
    }, { threshold:0.35 });
    cards.forEach(function(card){
        card.classList.add('loyalty-anim');
        io.observe(card);
    });
})();
