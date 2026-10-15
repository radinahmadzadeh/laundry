// Staff panel, order page: fill the price of a picked item.

function fillPrice(select){
    var opt = select.options[select.selectedIndex];
    var price = opt.getAttribute('data-price');
    if (price){ document.getElementById('item_price_input').value = price; }
}
