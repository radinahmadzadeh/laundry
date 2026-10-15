// Dashboard motion and counters (account page).

// Account dashboard motion: blocks rise in as they come into view and their numbers count up.
(function(){
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var blocks = document.querySelectorAll('.rv-a');
  function fa(n, money){
    var s = money ? Math.round(n).toLocaleString('en-US').replace(/,/g, '٬') : String(Math.round(n));
    return s.replace(/\d/g, function(d){ return '۰۱۲۳۴۵۶۷۸۹'[d]; });
  }
  function countUp(el){
    var target = parseFloat(el.getAttribute('data-count')) || 0, money = el.hasAttribute('data-money');
    if (reduce || !target) return;
    var start = performance.now(), dur = 1100;
    (function tick(now){
      var t = Math.min(1, (now - start) / dur), eased = 1 - Math.pow(1 - t, 3);
      el.textContent = fa(target * eased, money);
      if (t < 1) requestAnimationFrame(tick);
    })(start);
  }
  // The hero is on screen from the start: its wallet balance counts up as it lands.
  setTimeout(function(){ document.querySelectorAll('.ac-hero [data-count]').forEach(countUp); }, 550);
  if (reduce || !('IntersectionObserver' in window)){ blocks.forEach(function(b){ b.classList.add('in'); }); return; }
  var io = new IntersectionObserver(function(entries){
    entries.forEach(function(e){
      if (!e.isIntersecting) return;
      io.unobserve(e.target);
      e.target.classList.add('in');
      var target = e.target, d = parseFloat(getComputedStyle(target).getPropertyValue('--d')) || 0;
      setTimeout(function(){ target.classList.add('settled'); }, 1300 + d * 90);
      e.target.querySelectorAll('[data-count]').forEach(countUp);
    });
  }, { threshold:0, rootMargin:'0px 0px -6% 0px' });
  blocks.forEach(function(b){ io.observe(b); });
})();
