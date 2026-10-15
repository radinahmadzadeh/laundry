// Staff panel, new order: item rows, prices and the new-customer fields.

function addItemRow(){
    var container = document.getElementById('items_container');
    var row = container.children[0].cloneNode(true);
    row.querySelectorAll('input, textarea').forEach(function(input){
        if (input.name === 'item_qty[]') input.value = '1';
        else input.value = '';
    });
    row.querySelector('select').selectedIndex = 0;
    container.appendChild(row);
}
function fillRowPrice(select){
    var opt = select.options[select.selectedIndex];
    var row = select.closest('.item-row');
    var manualInput = row.querySelector('.item-name-manual');
    var priceInput = row.querySelector('input[name="item_price[]"]');
    if (opt.value){
        manualInput.value = opt.value;
        priceInput.value = opt.getAttribute('data-price');
    }
}
document.getElementById('customer_select').addEventListener('change', function(){
    document.getElementById('new_customer_fields').style.display = this.value ? 'none' : 'block';
});
