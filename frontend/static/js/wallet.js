// Wallet page: top-up amount checks and formatting.

var MIN_TOPUP = 10000, MAX_TOPUP = 50000000;
function toLatinDigits(value){
  return String(value||'').replace(/[۰-۹]/g,function(d){return '۰۱۲۳۴۵۶۷۸۹'.indexOf(d)}).replace(/[٠-٩]/g,function(d){return '٠١٢٣٤٥٦٧٨٩'.indexOf(d)});
}
function digitsOnly(value){ return toLatinDigits(value).replace(/[^0-9]/g,''); }
// A decimal point means the customer typed something like 10000.5 — never silently turn it into 100005.
function hasDecimal(value){ return /[.\/٫]/.test(toLatinDigits(value)); }
function formatMoney(value){ return Number(digitsOnly(value)||'0').toLocaleString('fa-IR'); }
function showAmountError(message){
  var el=document.getElementById('amount-error');
  el.textContent=message||''; el.hidden=!message;
}
function setWalletAmount(amount){ document.getElementById('wallet-amount').value=formatMoney(amount); showAmountError(''); }
function normalizeAmount(){
  var input=document.getElementById('wallet-amount');
  if(hasDecimal(input.value)){ showAmountError('مبلغ را بدون اعشار و به تومان وارد کنید.'); input.focus(); return false; }
  var digits=digitsOnly(input.value), amount=parseInt(digits||'0',10);
  if(amount<MIN_TOPUP){ showAmountError('حداقل مبلغ شارژ ۱۰٬۰۰۰ تومان است.'); input.focus(); return false; }
  if(amount>MAX_TOPUP){ showAmountError('حداکثر مبلغ شارژ در هر بار ۵۰٬۰۰۰٬۰۰۰ تومان است.'); input.focus(); return false; }
  input.value=digits;
  return true;
}
document.addEventListener('DOMContentLoaded',function(){
  var input=document.getElementById('wallet-amount');
  if(input){input.addEventListener('input',function(){
    if(hasDecimal(this.value)){ showAmountError('مبلغ را بدون اعشار و به تومان وارد کنید.'); return; }
    showAmountError('');
    var digits=digitsOnly(this.value); this.value=digits?formatMoney(digits):'';
  });}
});
