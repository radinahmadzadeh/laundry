// Staff panel: find a customer by name or phone instead of scrolling a dropdown of every customer.

document.querySelectorAll('.customer-picker').forEach(function(picker){
    var hidden = picker.querySelector('input[type="hidden"]');
    var chosen = picker.querySelector('.picker-chosen');
    var label = picker.querySelector('.picker-label');
    var search = picker.querySelector('.picker-search');
    var input = picker.querySelector('.picker-input');
    var list = picker.querySelector('.picker-results');
    var timer = null, lastQuery = '';

    function setCustomer(id, text){
        hidden.value = id;
        label.textContent = text;
        chosen.classList.toggle('hidden', !id);
        search.classList.toggle('hidden', !!id);
        list.classList.add('hidden');
        hidden.dispatchEvent(new Event('change'));
    }

    function show(results){
        list.innerHTML = '';
        if (!results.length){
            var empty = document.createElement('li');
            empty.className = 'picker-empty';
            empty.textContent = 'مشتری‌ای پیدا نشد.';
            list.appendChild(empty);
        }
        results.forEach(function(c){
            var item = document.createElement('li');
            var button = document.createElement('button');
            button.type = 'button';
            button.setAttribute('role', 'option');
            var name = document.createElement('span');
            name.textContent = c.name;
            var phone = document.createElement('span');
            phone.className = 'picker-phone';
            phone.textContent = c.phone;
            button.append(name, phone);
            button.addEventListener('click', function(){ setCustomer(c.id, c.name + ' — ' + c.phone); });
            item.appendChild(button);
            list.appendChild(item);
        });
        list.classList.remove('hidden');
    }

    input.addEventListener('input', function(){
        clearTimeout(timer);
        var q = input.value.trim();
        if (!q){ list.classList.add('hidden'); lastQuery = ''; return; }
        timer = setTimeout(function(){
            lastQuery = q;
            fetch(picker.dataset.url + '?q=' + encodeURIComponent(q), {headers: {'Accept': 'application/json'}})
                .then(function(r){ return r.ok ? r.json() : {results: []}; })
                .then(function(data){ if (q === lastQuery) show(data.results); })
                .catch(function(){});
        }, 250);
    });

    // Enter in the search box must not submit the whole form.
    input.addEventListener('keydown', function(e){
        if (e.key === 'Enter'){
            e.preventDefault();
            var first = list.querySelector('button');
            if (first) first.click();
        }
    });

    picker.querySelector('.picker-clear').addEventListener('click', function(){
        setCustomer('', '');
        input.value = '';
        input.focus();
    });

    document.addEventListener('click', function(e){
        if (!picker.contains(e.target)) list.classList.add('hidden');
    });
});
