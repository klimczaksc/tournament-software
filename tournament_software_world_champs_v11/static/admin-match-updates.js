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

  document.addEventListener('submit', async e => {
    if(e.defaultPrevented)return;
    const form = e.target;
    if (!form.matches('#matches form, #timetable form, #referees form') || !/\/(?:match\/\d+\/(?:result|timing|referee-assignment|referee-reset)|tournament\/\d+\/(?:schedule|timetable|referees))$/.test(new URL(form.action).pathname)) return;
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
      const response = await fetch(form.action, {method: 'POST', body: data, headers: {'X-Tournament-Action':'1'}});
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error((result.messages || []).join(' ') || 'Nie zapisano. Sprawdź wynik, godziny lub sesję logowania.');
      dirtyForms.delete(form);
      await window.TournamentEvents.refresh({submitted:form});
      inform((result.messages || ['Zapisano.']).join(' '));
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
