"""Live, per-court estimates. Times are local to the tournament's IANA zone."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def local_now(settings):
    return datetime.now(ZoneInfo(settings.get('schedule_timezone', 'Europe/Warsaw'))).replace(tzinfo=None, microsecond=0)


def parse_time(value):
    if not value:
        return None
    value = datetime.fromisoformat(value)
    if value.tzinfo is not None:
        raise ValueError('Use a local date and time.')
    return value


def build_timetable(tournament, matches, settings, meta_for, closing_match_kind, now=None):
    start = parse_time(settings.get('schedule_start'))
    if not start:
        return {}
    now = now or local_now(settings)
    duration = timedelta(minutes=int(settings.get('match_minutes', 30)))
    courts, players, ends, result = {}, {}, {}, {}
    busy_courts, busy_players = {}, {}
    keyed = {meta_for(m).get('key'): m for m in matches if meta_for(m).get('key')}
    # Reserve ongoing matches before placing any waiting matches on their courts.
    for m in matches:
        md = meta_for(m)
        actual = parse_time(md.get('actual_start'))
        if actual and not m.winner_id:
            end = max(actual + duration, now + timedelta(minutes=1))
            busy_courts[m.court_number] = max(busy_courts.get(m.court_number, start), end)
            for pid in (m.player1_id, m.player2_id):
                if pid:
                    busy_players[pid] = max(busy_players.get(pid, start), end)
    group_end = start
    batch_floors = {}
    previous_end = start
    remaining = list(sorted(matches, key=lambda m: m.order_index))
    while remaining:
        # Some old imported brackets may not be in dependency order.
        ready = next((m for m in remaining if all(key not in keyed or keyed[key].id in ends
                     for key in [s.get('match_key') for s in meta_for(m).get('sources', [])
                                 if s.get('kind') in ('winner', 'loser')])), None)
        if ready is None:
            raise ValueError('Cyclic match dependency in timetable.')
        m = ready
        remaining.remove(m)
        md = meta_for(m)
        actual = parse_time(md.get('actual_start'))
        finished = parse_time(md.get('actual_end')) if m.winner_id else None
        manual = parse_time(md.get('manual_start'))
        deps = [ends[keyed[s['match_key']].id] for s in md.get('sources', [])
                if s.get('kind') in ('winner', 'loser') and s.get('match_key') in keyed]
        floor = max([start, courts.get(m.court_number, start)] + deps +
                    [players.get(pid, start) for pid in (m.player1_id, m.player2_id) if pid])
        if tournament.system == 'group_knockout' and not m.bracket.startswith('group_'):
            floor = max(floor, group_end)
        batch = md.get('schedule_batch') if not m.bracket.startswith('group_') else None
        if batch is not None:
            # Preserve the inter-round rest wave even on an otherwise idle court.
            if batch not in batch_floors:
                batch_floors[batch] = max([start] + list(ends.values()))
            floor = max(floor, batch_floors[batch])
        if closing_match_kind(m):
            floor = max(floor, previous_end)
        bye = bool(m.winner_id and not (m.player1_id and m.player2_id))
        if m.winner_id:
            # Never invent a real completion time for historical results or BYEs.
            begin = actual or max(floor, manual or start)
            end = finished or (max(floor, begin) + (timedelta() if bye else duration))
            state = 'Wolny los' if bye else 'Zakończony'
        elif actual:
            begin = actual
            end = max(actual + duration, now + timedelta(minutes=1))
            state = 'W trakcie'
        else:
            begin = max([floor, manual or start, now, busy_courts.get(m.court_number, start)] +
                        [busy_players.get(pid, start) for pid in (m.player1_id, m.player2_id) if pid])
            end = begin + duration
            state = 'Oczekuje'
        ends[m.id] = end
        courts[m.court_number] = max(courts.get(m.court_number, start), end)
        for pid in (m.player1_id, m.player2_id):
            if pid:
                players[pid] = max(players.get(pid, start), end)
        if m.bracket.startswith('group_'):
            group_end = max(group_end, end)
        previous_end = max(previous_end, end)
        result[m.id] = dict(start=begin, end=end, state=state, actual=bool(actual),
                            shifted=bool(manual and begin > manual), bye=bye)
    return result


def format_time(value):
    return value.strftime('%d.%m %H:%M') if value else '—'
