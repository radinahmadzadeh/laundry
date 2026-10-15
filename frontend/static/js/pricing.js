// Pricing page: scroll reveal and price search.

(function(){
  var targets = document.querySelectorAll('.motion-reveal, .motion-stagger');
  if (!('IntersectionObserver' in window)) {
    targets.forEach(function(el){ el.classList.add('is-visible'); });
    return;
  }
  document.body.classList.add('motion-ready');
  var observer = new IntersectionObserver(function(entries){
    entries.forEach(function(entry){
      if(entry.isIntersecting){
        entry.target.classList.add('is-visible');
        observer.unobserve(entry.target);
      }
    });
  }, {threshold:.14, rootMargin:'0px 0px -8% 0px'});
  targets.forEach(function(el){ observer.observe(el); });
})();
(function(){
  var input = document.getElementById('price-search');
  if (!input) return;
  input.addEventListener('input', function(){
    var q = input.value.trim().replace(/ي/g, 'ی').replace(/ك/g, 'ک');
    var any = false;
    document.querySelectorAll('.category-card').forEach(function(card){
      var visible = 0;
      card.querySelectorAll('.price-row').forEach(function(row){
        var match = !q || (row.dataset.name || '').indexOf(q) !== -1;
        row.classList.toggle('search-hidden', !match);
        if (match) visible++;
      });
      card.classList.toggle('search-hidden', visible === 0);
      if (visible) any = true;
    });
    document.getElementById('price-search-empty').classList.toggle('hidden', any);
  });
})();
