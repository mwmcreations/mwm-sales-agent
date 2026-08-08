
(function () {
  /* ---- State ---- */
  var selectedHours = null;
  var editingEnabled = false;
  var selectedDate = null;
  var selectedSlot = null;

  /* ---- Pricing (display only — the server prices canonically) ---- */
  var pricing = {
    studio:  { perHour: 249, totals: { 1: 249, 2: 498, 3: 747, 4: 996, 5: 1245 } },
    editing: { perHour: 349, totals: { 1: 349, 2: 698, 3: 1047, 4: 1396, 5: 1745 } }
  };

  /* ---- DOM References ---- */
  var hourCards      = document.querySelectorAll('.bs-hour-card');
  var checkbox       = document.getElementById('bs-editing-checkbox');
  var priceDisplay   = document.getElementById('bs-price-display');
  var priceType      = document.getElementById('bs-price-type');
  var priceTotal     = document.getElementById('bs-price-total');
  var priceBreakdown = document.getElementById('bs-price-breakdown');
  var schedulerArea   = document.getElementById('bs-scheduler-area');
  var placeholder    = document.getElementById('bs-scheduler-placeholder');
  var picker         = null;

  function formatPrice(amount) {
    return '$' + amount.toLocaleString('en-US');
  }
  function currentTotal() {
    var tier = editingEnabled ? 'editing' : 'studio';
    return pricing[tier].totals[selectedHours] || 0;
  }
  function fmt12(hhmm) {
    var p = hhmm.split(':');
    var h = parseInt(p[0], 10);
    var ap = h >= 12 ? 'PM' : 'AM';
    h = h % 12; if (h === 0) h = 12;
    return h + ':' + p[1] + ' ' + ap;
  }

  /* ---- Update price UI (unchanged behavior) ---- */
  function update() {
    if (selectedHours) {
      var tier = editingEnabled ? 'editing' : 'studio';
      var info = pricing[tier];
      var total = info.totals[selectedHours];
      var label = editingEnabled ? 'STUDIO + EDITING' : 'STUDIO ONLY';
      var hourWord = selectedHours === 1 ? 'hour' : 'hours';
      priceTotal.classList.add('bs-fade');
      setTimeout(function () {
        priceType.textContent = label;
        priceTotal.textContent = formatPrice(total);
        priceBreakdown.innerHTML = selectedHours + ' ' + hourWord + ' \u00d7 ' + formatPrice(info.perHour) + '/hr';
        priceTotal.classList.remove('bs-fade');
      }, 150);
      priceDisplay.classList.add('bs-visible');
    } else {
      priceDisplay.classList.remove('bs-visible');
    }
    loadPicker();
  }

  /* ---- AJAX helper ---- */
  function ajax(action, data, cb) {
    var boot = window.MWM_RENTAL || {};
    if (!boot.ajaxurl || !boot.nonce) { cb({ success: false, data: { message: 'Booking is temporarily unavailable. Please refresh the page.' } }); return; }
    var fd = new FormData();
    fd.append('action', action);
    fd.append('nonce', boot.nonce);
    Object.keys(data).forEach(function (k) { fd.append(k, data[k]); });
    fetch(boot.ajaxurl, { method: 'POST', body: fd, credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(cb)
      .catch(function () { cb({ success: false, data: { message: 'Network error. Please try again.' } }); });
  }

  /* ---- Slot picker ---- */
  function loadPicker() {
    if (!selectedHours) {
      placeholder.style.display = '';
      schedulerArea.classList.remove('bs-loaded');
      if (picker) { picker.remove(); picker = null; }
      selectedSlot = null;
      return;
    }
    placeholder.style.display = 'none';
    schedulerArea.classList.add('bs-loaded');

    if (!picker) {
      picker = document.createElement('div');
      picker.className = 'bs-rs-wrap';
      picker.innerHTML =
        '\u003clabel class="bs-rs-label" for="bs-rs-date">1. Pick a date\u003c/label>' +
        '\u003cdiv class="bs-rs-cal" id="bs-rs-cal">\u003c/div>\u003cinput type="hidden" id="bs-rs-date">' +
        '\u003clabel class="bs-rs-label" id="bs-rs-slots-label" style="display:none">2. Pick a start time\u003c/label>' +
        '\u003cdiv class="bs-rs-slots" id="bs-rs-slots">\u003c/div>' +
        '\u003cp class="bs-rs-msg" id="bs-rs-msg">\u003c/p>' +
        '\u003cdiv class="bs-rs-form" id="bs-rs-form">' +
          '\u003clabel class="bs-rs-label">3. Your details\u003c/label>' +
          '\u003cinput type="text" id="bs-rs-name" class="bs-rs-input" placeholder="Full name" autocomplete="name">' +
          '\u003cinput type="email" id="bs-rs-email" class="bs-rs-input" placeholder="Email address" autocomplete="email">' +
          '\u003ctextarea id="bs-rs-notes" class="bs-rs-input" placeholder="Anything we should know? (optional)">\u003c/textarea>' +
          '\u003cbutton type="button" class="bs-rs-pay" id="bs-rs-pay">\u003c/button>' +
          '\u003cp class="bs-rs-note">Your time slot is held for 15 minutes while you complete payment. Secure checkout by Stripe. Free reschedule, or cancellation refunded minus payment-processing fees, up to 24 hours before your session. Within 24 hours bookings are non-refundable.\u003c/p>' +
          '\u003cp class="bs-rs-err" id="bs-rs-err">\u003c/p>' +
        '\u003c/div>';
      schedulerArea.appendChild(picker);

      var dateEl = picker.querySelector('#bs-rs-date');
      dateEl.addEventListener('change', function () {
        selectedDate = dateEl.value;
        selectedSlot = null;
        fetchSlots();
      });
      picker.querySelector('#bs-rs-pay').addEventListener('click', reserve);
      calInit();
    }
    calRefresh();
    if (selectedDate) fetchSlots(); else refreshForm();
  }

  /* ---- S19: availability-aware month calendar ---- */
  var calY = 0, calM = 0, calReq = 0;
  function calPad(n) { return n < 10 ? '0' + n : '' + n; }
  function calInit() {
    var now = new Date();
    calY = now.getFullYear();
    calM = now.getMonth() + 1;
  }
  function calStep(dir) {
    calM += dir;
    if (calM < 1) { calM = 12; calY -= 1; }
    if (calM > 12) { calM = 1; calY += 1; }
    calRefresh();
  }
  function calRefresh() {
    if (!picker) { return; }
    if (!selectedHours) { return; }
    var box = picker.querySelector('#bs-rs-cal');
    if (!box) { return; }
    calRender(box, null);
    var req = ++calReq;
    ajax('mwm_studio_rental_month', { year: calY, month: calM, duration: selectedHours }, function (res) {
      if (req !== calReq) { return; }
      if (!res.success) {
        var msg = picker.querySelector('#bs-rs-msg');
        var txt = 'Booking is temporarily unavailable.';
        if (res.data) { if (res.data.message) { txt = res.data.message; } }
        if (msg) { msg.textContent = txt; }
        calRender(box, {});
        return;
      }
      var map = {};
      res.data.days.forEach(function (d) { map[d] = true; });
      calRender(box, map);
    });
  }
  function calRender(box, map) {
    var dows = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    var months = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
    var now = new Date();
    var todayStr = now.getFullYear() + '-' + calPad(now.getMonth() + 1) + '-' + calPad(now.getDate());
    var horizon = new Date(now.getTime() + 60 * 86400000);
    var ymNow = now.getFullYear() * 12 + now.getMonth();
    var ymCal = calY * 12 + (calM - 1);
    var ymHor = horizon.getFullYear() * 12 + horizon.getMonth();
    var startDow = new Date(calY, calM - 1, 1).getDay();
    var dim = new Date(calY, calM, 0).getDate();
    var html = '\u003cdiv class="bs-rs-cal-head">';
    html += '\u003cbutton type="button" class="bs-rs-cal-nav" id="bs-rs-cal-prev"' + (ymCal <= ymNow ? ' disabled' : '') + '>‹\u003c/button>';
    html += '\u003cdiv class="bs-rs-cal-title">' + months[calM - 1] + ' ' + calY + '\u003c/div>';
    html += '\u003cbutton type="button" class="bs-rs-cal-nav" id="bs-rs-cal-next"' + (ymCal >= ymHor ? ' disabled' : '') + '>›\u003c/button>';
    html += '\u003c/div>\u003cdiv class="bs-rs-cal-grid">';
    var i;
    for (i = 0; i < 7; i++) { html += '\u003cdiv class="bs-rs-cal-dow">' + dows[i] + '\u003c/div>'; }
    for (i = 0; i < startDow; i++) { html += '\u003cdiv>\u003c/div>'; }
    var d;
    for (d = 1; d <= dim; d++) {
      var ds = calY + '-' + calPad(calM) + '-' + calPad(d);
      var ok = false;
      if (map) { if (map[ds]) { ok = true; } }
      var cls = 'bs-rs-cal-day';
      if (ok) { cls += ' bs-rs-cal-avail'; }
      if (ds === todayStr) { cls += ' bs-rs-cal-today'; }
      if (ds === selectedDate) { cls += ' bs-rs-cal-on'; }
      html += '\u003cbutton type="button" class="' + cls + '" data-d="' + ds + '"' + (ok ? '' : ' disabled') + '>' + d + '\u003c/button>';
    }
    html += '\u003c/div>';
    if (map === null) { html += '\u003cp class="bs-rs-cal-note">Loading availability…\u003c/p>'; }
    box.innerHTML = html;
    var prev = box.querySelector('#bs-rs-cal-prev');
    var next = box.querySelector('#bs-rs-cal-next');
    if (prev) { prev.addEventListener('click', function () { calStep(-1); }); }
    if (next) { next.addEventListener('click', function () { calStep(1); }); }
    var days = box.querySelectorAll('.bs-rs-cal-avail');
    for (i = 0; i < days.length; i++) {
      (function (el) {
        el.addEventListener('click', function () {
          var de = picker.querySelector('#bs-rs-date');
          de.value = el.getAttribute('data-d');
          var on = box.querySelectorAll('.bs-rs-cal-on');
          var k;
          for (k = 0; k < on.length; k++) { on[k].classList.remove('bs-rs-cal-on'); }
          el.classList.add('bs-rs-cal-on');
          de.dispatchEvent(new Event('change'));
        });
      })(days[i]);
    }
  }

  function fetchSlots() {
    if (!picker || !selectedDate || !selectedHours) return;
    var grid = picker.querySelector('#bs-rs-slots');
    var msg = picker.querySelector('#bs-rs-msg');
    var lbl = picker.querySelector('#bs-rs-slots-label');
    grid.innerHTML = '';
    lbl.style.display = '';
    msg.textContent = 'Loading available times…';
    refreshForm();
    ajax('mwm_studio_rental_slots', { date: selectedDate, duration: selectedHours }, function (res) {
      grid.innerHTML = '';
      if (!res || !res.success) {
        var d = (res ? res.data : null) || {};
        if (d.reason === 'availability_unavailable') {
          msg.innerHTML = 'Booking is temporarily unavailable. Please message us on \u003ca href="https://wa.me/14078716473" target="_blank" rel="noopener">WhatsApp\u003c/a> and we will get you booked.';
        } else {
          msg.textContent = (d.message || 'Could not load times. Please try another date.');
        }
        return;
      }
      var slots = res.data.slots || [];
      if (!slots.length) {
        msg.textContent = 'No times available for that date with ' + selectedHours + ' hour' + (selectedHours === 1 ? '' : 's') + '. Try another date.';
        return;
      }
      msg.textContent = '';
      slots.forEach(function (s) {
        var start = (typeof s === 'string' ? s : (s ? (s.start || '') : '')).slice(0, 5);
        if (!start) return;
        var b = document.createElement('button');
        b.type = 'button';
        b.className = 'bs-rs-slot';
        b.textContent = fmt12(start);
        b.setAttribute('data-start', start);
        b.addEventListener('click', function () {
          selectedSlot = start;
          picker.querySelectorAll('.bs-rs-slot').forEach(function (x) { x.classList.remove('bs-rs-on'); });
          b.classList.add('bs-rs-on');
          refreshForm();
        });
        grid.appendChild(b);
      });
    });
  }

  function refreshForm() {
    if (!picker) return;
    var form = picker.querySelector('#bs-rs-form');
    var pay = picker.querySelector('#bs-rs-pay');
    var err = picker.querySelector('#bs-rs-err');
    err.style.display = 'none';
    var ready = false;
    if (selectedSlot) { if (selectedHours) { ready = true; } }
    if (ready) {
      form.classList.add('bs-rs-show');
      pay.disabled = false;
      pay.textContent = 'Reserve ' + fmt12(selectedSlot) + ' \u0026 Pay ' + formatPrice(currentTotal());
    } else {
      form.classList.remove('bs-rs-show');
    }
  }

  function reserve() {
    var name = picker.querySelector('#bs-rs-name').value.trim();
    var email = picker.querySelector('#bs-rs-email').value.trim();
    var notes = picker.querySelector('#bs-rs-notes').value.trim();
    var pay = picker.querySelector('#bs-rs-pay');
    var err = picker.querySelector('#bs-rs-err');
    err.style.display = 'none';
    if (!name || !email || email.indexOf('@') < 1) {
      err.textContent = 'Please enter your name and a valid email.';
      err.style.display = 'block';
      return;
    }
    pay.disabled = true;
    pay.textContent = 'Securing your slot…';
    ajax('mwm_studio_hold_slot', {
      date: selectedDate,
      start_time: selectedSlot,
      hours: selectedHours,
      editing: editingEnabled ? '1' : '0',
      name: name,
      email: email,
      notes: notes
    }, function (res) {
      var okUrl = null;
      if (res) { if (res.success) { if (res.data) { okUrl = res.data.checkout_url; } } }
      if (okUrl) {
        pay.textContent = 'Redirecting to secure checkout…';
        window.location.href = okUrl;
        return;
      }
      var d = (res ? res.data : null) || {};
      if (d.reason === 'availability_unavailable') {
        err.innerHTML = 'Booking is temporarily unavailable. Please message us on \u003ca href="https://wa.me/14078716473" target="_blank" rel="noopener" style="color:#C8A96E">WhatsApp\u003c/a>.';
      } else {
        err.textContent = d.message || 'Something went wrong. Please try again.';
      }
      err.style.display = 'block';
      pay.disabled = false;
      refreshForm();
      fetchSlots();
    });
  }

  /* ---- Hour Card Clicks (unchanged behavior) ---- */
  hourCards.forEach(function (card) {
    card.addEventListener('click', function () {
      var hours = parseInt(card.getAttribute('data-hours'), 10);
      if (selectedHours === hours) {
        selectedHours = null;
        card.classList.remove('bs-active');
      } else {
        selectedHours = hours;
        hourCards.forEach(function (c) { c.classList.remove('bs-active'); });
        card.classList.add('bs-active');
      }
      selectedSlot = null;
      update();
    });
    card.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        card.click();
      }
    });
  });

  /* ---- Editing Toggle (unchanged behavior) ---- */
  checkbox.addEventListener('change', function () {
    editingEnabled = checkbox.checked;
    update();
  });

})();


/* ==== next script ==== */


	(function () {
		var qs = new URLSearchParams( window.location.search );
		var rawEditing = ( qs.get( 'editing' ) || '' ).toLowerCase();
		var wantEditing = ( rawEditing === '1' || rawEditing === 'true' || rawEditing === 'yes' );
		var wantHours = parseInt( qs.get( 'hours' ), 10 );
		var validHours = ( wantHours >= 1 && wantHours <= 5 );

		if ( ! wantEditing && ! validHours ) { return; }

		var tries = 0;

		function apply() {
			var cards = document.querySelectorAll( '.bs-hour-card' );
			var box   = document.getElementById( 'bs-editing-checkbox' );

			if ( ( ! cards.length || ! box ) && tries++ < 40 ) {
				return window.setTimeout( apply, 100 );
			}
			if ( ! cards.length || ! box ) { return; }

			if ( wantEditing && ! box.checked ) {
				box.checked = true;
				box.dispatchEvent( new Event( 'change', { bubbles: true } ) );
			}

			if ( validHours ) {
				Array.prototype.forEach.call( cards, function ( card ) {
					var h = parseInt( card.getAttribute( 'data-hours' ), 10 );
					if ( h === wantHours && ! card.classList.contains( 'bs-active' ) ) {
						card.click();
					}
				} );
			}
		}

		if ( document.readyState === 'loading' ) {
			document.addEventListener( 'DOMContentLoaded', apply );
		} else {
			apply();
		}
	})();
	