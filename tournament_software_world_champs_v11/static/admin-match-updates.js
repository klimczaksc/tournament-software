/* Save match controls in place, without navigating to a redirected #match anchor. */
(() => {
  const dirtyForms = new Set();
  let saving = false;
  const notice = document.createElement('div');
  notice.className = 'match-save-notice';
  notice.setAttribute('role', 'status');
  notice.setAttribute('aria-live', 'polite');
  notice.hidden = true;
  document.body.append(notice);
  let noticeTimer;
  function inform(message, error = false) {
    clearTimeout(noticeTimer);
    notice.textContent = message;
    notice.dataset.error = String(error);
    notice.hidden = false;
    if (!error) noticeTimer = setTimeout(() => { notice.hidden = true; }, 5000);
  }
  document.addEventListener('input', e => {
    if (e.target.form) dirtyForms.add(e.target.form);
  });
  document.addEventListener('change', e => {
    if (e.target.form) dirtyForms.add(e.target.form);
  });

  function updatePage(doc, submitted) {
    // Capture position at response time: the organiser may have moved while saving.
    const visible = [...document.querySelectorAll('#matches .match-card[id]')].find(el => {
      const rect = el.getBoundingClientRect();
      return rect.bottom > 0 && rect.top < window.innerHeight;
    });
    const anchorId = visible?.id;
    const anchorTop = visible?.getBoundingClientRect().top;
    const x = window.scrollX, y = window.scrollY;
    const root = document.documentElement;
    const oldBehavior = root.style.scrollBehavior, oldAnchoring = root.style.overflowAnchor;
    root.style.scrollBehavior = 'auto';
    root.style.overflowAnchor = 'none';
    const focus = document.activeElement;
    const focusCard = focus?.closest('.match-card[id]')?.id;
    const focusAction = focus?.form?.getAttribute('action');
    const focusName = focus?.name;
    const selection = focus?.selectionStart;
    let discarded = false;
    try {
      doc.querySelectorAll('#matches .match-card[id]').forEach(fresh => {
        const old = document.getElementById(fresh.id);
        if (!old) return;
        const samePlayers = old.dataset.player1 === fresh.dataset.player1 && old.dataset.player2 === fresh.dataset.player2;
        const openDetails = [...old.querySelectorAll('details')].map(d => d.open);
        const retained = [];
        old.querySelectorAll('form').forEach(form => {
          if (form === submitted || !dirtyForms.has(form)) return;
          if (!samePlayers) { discarded = true; return; }
          const target = [...fresh.querySelectorAll('form')].find(f => f.getAttribute('action') === form.getAttribute('action'));
          if (!target) return;
          [...form.elements].filter(el => el.name && el.type !== 'hidden' && el.tagName !== 'BUTTON').forEach(el => {
            const next = target.elements.namedItem(el.name);
            if (!next || next.disabled) return;
            next.value = el.value;
            if (el.type === 'checkbox' || el.type === 'radio') next.checked = el.checked;
          });
          retained.push(target);
        });
        old.querySelectorAll('form').forEach(f => dirtyForms.delete(f));
        fresh.querySelectorAll('details').forEach((d, i) => { d.open = !!openDetails[i]; });
        old.replaceWith(fresh);
        retained.forEach(f => dirtyForms.add(f));
      });
      // Results also update group tables, participant slots, pairings and draw sheets.
      for (const id of ['overview', 'group-tables', 'knockout-pairing', 'round-pairings', 'tree', 'standings']) {
        const old = document.getElementById(id), fresh = doc.getElementById(id);
        if (old && [...old.querySelectorAll('form')].some(f => dirtyForms.has(f))) continue;
        if (old && fresh) {
          const scrolls = [...old.querySelectorAll('.bracket-scroll')].map(el => [el.scrollLeft, el.scrollTop]);
          old.innerHTML = fresh.innerHTML;
          old.querySelectorAll('.bracket-scroll').forEach((el, i) => {
            if (scrolls[i]) { el.scrollLeft = scrolls[i][0]; el.scrollTop = scrolls[i][1]; }
          });
        } else if (old) old.remove();
        else if (fresh) {
          const before = ['knockout-pairing', 'round-pairings'].includes(id) ? 'timetable' : 'standings';
          document.getElementById(before)?.before(fresh);
        }
      }
      if (typeof drawBracketConnectors === 'function') drawBracketConnectors();
      if (focusCard && focusName) {
        const form = [...(document.getElementById(focusCard)?.querySelectorAll('form') || [])]
          .find(f => f.getAttribute('action') === focusAction);
        const field = form?.elements.namedItem(focusName);
        if (field && !field.disabled) {
          field.focus({preventScroll: true});
          if (selection != null && field.setSelectionRange && field.type !== 'number') field.setSelectionRange(selection, selection);
        }
      }
      const anchor = anchorId && document.getElementById(anchorId);
      window.scrollTo({left: x, top: anchor ? y + anchor.getBoundingClientRect().top - anchorTop : y, behavior: 'instant'});
    } finally {
      root.style.scrollBehavior = oldBehavior;
      root.style.overflowAnchor = oldAnchoring;
    }
    return discarded;
  }

  document.addEventListener('submit', async e => {
    const form = e.target;
    if (!form.matches('#matches .match-card form') || !/\/match\/\d+\/(result|timing)$/.test(new URL(form.action).pathname)) return;
    e.preventDefault();
    if (saving) { inform('Trwa zapisywanie poprzedniego meczu. Poczekaj chwilę.'); return; }
    saving = true;
    const data = new FormData(form);
    // FormData(form) omits the clicked button (notably action=start).
    if (e.submitter?.name) data.set(e.submitter.name, e.submitter.value);
    const controls = [...form.elements].filter(el => !el.disabled);
    controls.forEach(el => { el.disabled = true; });
    form.setAttribute('aria-busy', 'true');
    inform('Zapisywanie…');
    try {
      const response = await fetch(form.action, {method: 'POST', body: data});
      if (!response.ok) throw new Error(response.status === 400 ? 'Nie zapisano. Sprawdź wynik, godziny lub dostępność kortu i zawodników.' : 'Nie udało się zapisać. Sprawdź połączenie i sesję logowania.');
      const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
      if (!doc.querySelector('#matches')) throw new Error('Sesja wygasła. Zaloguj się ponownie w osobnej karcie, a następnie ponów zapis.');
      const messages = [...doc.querySelectorAll('.flash')].map(el => el.textContent.trim()).join(' ');
      if (!/Result saved\.|Zapisano czas meczu\./.test(messages)) { inform(messages || 'Nie udało się potwierdzić zapisu.', true); return; }
      const discarded = updatePage(doc, form);
      inform((messages || 'Zapisano.') + (discarded ? ' Zmienili się uczestnicy kolejnego meczu — sprawdź go przed wpisaniem wyniku.' : ''));
    } catch (error) {
      // A connection loss may happen after the server saved the result. Do not auto-retry.
      inform(error.message || 'Nie udało się potwierdzić zapisu. Sprawdź połączenie.', true);
    } finally {
      controls.forEach(el => { el.disabled = false; });
      form.removeAttribute('aria-busy');
      saving = false;
    }
  });
  document.addEventListener('toggle', e => {
    if (e.target.matches('details') && typeof drawBracketConnectors === 'function') requestAnimationFrame(drawBracketConnectors);
  }, true);
})();
