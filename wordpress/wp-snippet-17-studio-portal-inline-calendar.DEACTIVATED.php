<?php

/**
 * Studio Portal — Inline Booking Calendar (S14)
 */
// S14 cosmetic: Studio Portal inline booking calendar (replaces hard-to-see native date picker)
add_action('wp_footer', function () {
	if (strpos((string) ($_SERVER['REQUEST_URI'] ?? ''), 'studio-portal') === false) return;
	echo <<<'MWMCAL'
<style>
#mwmcal{max-width:360px;background:#171726;border-radius:16px;padding:16px;margin:8px 0 16px;overflow:hidden;}
#mwmcal, #mwmcal *{box-sizing:border-box;}
#mwmcal .mwmcal-head{display:flex;justify-content:space-between;align-items:center;color:#fff;font-weight:600;margin-bottom:10px;font-size:15px;}
#mwmcal button.mwmcal-nav{background:transparent;border:1px solid #3a3a55;color:#fff;border-radius:8px;width:32px;height:32px;min-width:0;padding:0;margin:0;cursor:pointer;font-size:18px;line-height:1;box-shadow:none;}
#mwmcal button.mwmcal-nav:disabled{opacity:.3;cursor:default;}
#mwmcal .mwmcal-grid{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:4px;}
#mwmcal .mwmcal-dow{color:#8a8aa3;font-size:11px;text-align:center;padding:4px 0;}
#mwmcal button.mwmcal-day{display:block;width:100%;aspect-ratio:1/1;min-width:0;height:auto;padding:0;margin:0;background:#22223a;border:none;color:#e8e8f0;border-radius:8px;cursor:pointer;font-size:14px;line-height:1;box-shadow:none;text-shadow:none;text-transform:none;letter-spacing:0;}
#mwmcal button.mwmcal-day:hover:not(:disabled){background:#e05a6d;color:#fff;}
#mwmcal button.mwmcal-day.sel{background:#e05a6d;color:#fff;font-weight:700;}
#mwmcal button.mwmcal-day.tdy{outline:1px solid #7c6cf0;}
#mwmcal button.mwmcal-day.dis{opacity:.25;cursor:default;background:#22223a;}
</style>
<script>
(function(){
  var tries = 0;
  function init() {
    var input = document.getElementById('mwm-book-date');
    if (!input) { if (++tries < 100) setTimeout(init, 300); return; }
    if (document.getElementById('mwmcal')) return;
    build(input);
  }
  function build(input) {
  var wrap = document.createElement('div');
  wrap.id = 'mwmcal';
  input.style.display = 'none';
  input.parentNode.insertBefore(wrap, input.nextSibling);
  var today = new Date(); today.setHours(0,0,0,0);
  var view = new Date(today.getFullYear(), today.getMonth(), 1);
  var sel = null;
  var MN = ['January','February','March','April','May','June','July','August','September','October','November','December'];
  function pad(n){return (n<10?'0':'')+n;}
  function iso(d){return d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate());}
  function render(){
    var startDow = new Date(view.getFullYear(), view.getMonth(), 1).getDay();
    var dim = new Date(view.getFullYear(), view.getMonth()+1, 0).getDate();
    var prevDis = view.getFullYear()===today.getFullYear() && view.getMonth()===today.getMonth();
    var h = '<div class="mwmcal-head"><button type="button" class="mwmcal-nav" data-d="-1"'+(prevDis?' disabled':'')+'>&#8249;</button><span>'+MN[view.getMonth()]+' '+view.getFullYear()+'</span><button type="button" class="mwmcal-nav" data-d="1">&#8250;</button></div><div class="mwmcal-grid">';
    var dows = ['S','M','T','W','T','F','S'];
    for (var w=0; w<7; w++) h += '<div class="mwmcal-dow">'+dows[w]+'</div>';
    for (var i=0; i<startDow; i++) h += '<div></div>';
    for (var d=1; d<=dim; d++){
      var dt = new Date(view.getFullYear(), view.getMonth(), d);
      var dis = dt < today;
      var cls = 'mwmcal-day'+(dis?' dis':'')+(sel===iso(dt)?' sel':'')+(iso(dt)===iso(today)?' tdy':'');
      h += '<button type="button" class="'+cls+'" data-date="'+iso(dt)+'"'+(dis?' disabled':'')+'>'+d+'</button>';
    }
    wrap.innerHTML = h + '</div>';
  }
  wrap.addEventListener('click', function(e){
    var b = e.target.closest('button'); if (!b) return;
    if (b.classList.contains('mwmcal-nav') && !b.disabled) { view.setMonth(view.getMonth()+parseInt(b.getAttribute('data-d'),10)); render(); return; }
    if (b.classList.contains('mwmcal-day') && !b.disabled) {
      sel = b.getAttribute('data-date');
      input.value = sel;
      input.dispatchEvent(new Event('change', {bubbles: true}));
      render();
    }
  });
  render();
  }
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); } else { init(); }
})();
</script>
MWMCAL;
}, 99);
