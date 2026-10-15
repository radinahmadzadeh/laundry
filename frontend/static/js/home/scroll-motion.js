// Scroll reveal and pausing of off-screen animations (home page).

// Scroll motion: every block rises softly into view the first time it is scrolled to (grids in a
// stagger), and looping animations pause while their section is off screen so scrolling stays smooth.
(function(){
    var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    document.querySelectorAll('#services .panel, #pricing .panel').forEach(function(el){ el.classList.add('motion-card'); });
    if (!('IntersectionObserver' in window)) return;

    var pause = new IntersectionObserver(function(entries){
        entries.forEach(function(e){ e.target.classList.toggle('is-offscreen', !e.isIntersecting); });
    }, { rootMargin:'200px 0px' });
    document.querySelectorAll('body > section, body > footer').forEach(function(el){ pause.observe(el); });
    if (reduce) return;

    // Blocks that already have their own entrance stay as they are.
    var OWN = '.hero-section, .svc-board, .svc-dots, script, style, [hidden]';
    var targets = [];
    function mark(el, delay){
        el.classList.remove('enter');
        el.classList.add('rv');
        el.style.setProperty('--rv-d', delay + 'ms');
        targets.push(el);
    }
    document.querySelectorAll('body > section:not(.hero-section), body > footer > *').forEach(function(section){
        Array.prototype.forEach.call(section.children, function(child){
            if (child.matches(OWN)) return;
            var items = child.children;
            if (child.classList.contains('grid') && items.length > 1){
                Array.prototype.forEach.call(items, function(item, i){ mark(item, Math.min(i, 6) * 80); });
            } else {
                mark(child, 0);
            }
        });
    });
    var show = new IntersectionObserver(function(entries){
        entries.forEach(function(e){
            if (!e.isIntersecting) return;
            var el = e.target;
            show.unobserve(el);
            el.classList.add('rv-in');
            // Hand the element back to its own hover/transition styles once it has arrived.
            var done = parseFloat(el.style.getPropertyValue('--rv-d')) + 1000;
            setTimeout(function(){ el.classList.remove('rv', 'rv-in'); el.style.removeProperty('--rv-d'); }, done);
        });
    }, { threshold:0, rootMargin:'0px 0px -8% 0px' });  // any part in view: very tall blocks must reveal too
    targets.forEach(function(el){ show.observe(el); });
})();
