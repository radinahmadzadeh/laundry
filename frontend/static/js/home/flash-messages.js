// Home page: one-time messages from the server.

// Confirmations fade after a while; errors and warnings stay until the customer closes them.
window.addEventListener('load', function(){
    setTimeout(function(){
        document.querySelectorAll('#flash-stack .flash-msg.success, #flash-stack .flash-msg.info').forEach(function(el){ el.remove(); });
    }, 10000);
});
