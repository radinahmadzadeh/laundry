// Staff panel: money amounts with thousands separators.

document.querySelectorAll('.money-auto').forEach(function(el){var raw=String(el.textContent||'').replace(/[^0-9-]/g,'');if(raw)el.textContent=Number(raw).toLocaleString('de-DE');});
