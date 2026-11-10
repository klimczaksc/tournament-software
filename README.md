# Tournament Software — Railway

Flask tournament manager based on v11. Existing formats, match scoring, pairing,
PDF/Excel exports and JSON tournament imports remain available to the administrator.

## Access

- **Administrator:** creates and edits tournaments, records scores, imports/exports,
  manages read-only accounts and publishes individual player links.
- **Viewer account:** sees the tournament archive, schedules, results, group tables,
  brackets and rankings. All editing endpoints are denied on the server.
- **Players:** no login; open `/players/<random-token>` for a single published
  tournament. No archive listing, management controls, JSON backup or account access.
  Pages refresh every 30 seconds while visible, retaining search and scroll position.
  Disable publication to revoke access; enabling again generates a new link.

All stored tournaments are visible to signed-in accounts, including ongoing events.
The schedule retains v11 match order and court assignments; it does not invent
clock times. Existing v11 double-elimination and Swiss generation behavior is retained.

## Railway deployment

1. Create a project and connect `klimczaksc/tournament-software`, branch `main`.
   Build from the repository root; Dockerfile handles the existing subdirectory.
2. Attach a persistent volume at **/data**. Use **one replica** for this SQLite app.
   The database (including hashed passwords) and uploaded logos are on this volume.
3. Set environment variables:
   - `DATA_DIR=/data`
   - `SECRET_KEY`: a randomly generated secret (at least 32 bytes).
   - `SETUP_TOKEN`: another independent, randomly generated secret.
   - `COOKIE_SECURE=1`
   Never commit these values to GitHub.
4. Deploy, check `/health`, then generate a Railway public domain.
5. Open `https://YOUR-DOMAIN/setup?token=YOUR-SETUP-TOKEN` privately. Create the
   first administrator (password minimum 8 characters). This endpoint permanently
   closes once the first administrator exists; remove SETUP_TOKEN afterwards.
6. Log in at `/login`. Use **Konta** to create read-only accounts or deactivate
   them/reset their passwords. Deactivation and resets invalidate existing sessions.
7. In a tournament, enable **Link dla graczy**, save, and copy the displayed URL.

The supplied ZIP contains **no tournament database or recorded events**. To migrate
old events, export each tournament as JSON from the old app and use **Import JSON**
as administrator. Alternatively migrate an existing v11 `tournament.db` and uploads
onto the volume before first start; startup adds the accounts table without deleting
existing tournaments. Imported JSON events are private until explicitly published.

## Operations

Set up Railway volume backups in the dashboard; JSON exports cover tournaments,
not user accounts or logos. Keep SECRET_KEY stable across restarts. SQLite requires
a single service replica. Rate limits use process memory with a single Gunicorn
worker; counters reset on restart. Sessions expire after 12 hours. CSRF protection
applies to all forms and JSON writes. TLS is supplied by the Railway domain.

## Local development

```
cd tournament_software_world_champs_v11
python -m pip install -r requirements.txt
# Set SETUP_TOKEN in your shell before starting.
python app.py
```

Local port: 5069. DATA_DIR defaults to the app directory; a local session secret
is generated when SECRET_KEY is absent. Keep databases, uploads and secrets out
of git. For tests: `pip install pytest && pytest test_online.py`.


### Timetable i ekran zawodników

W turnieju otwórz „Timetable · godziny meczów”, ustaw lokalną datę i godzinę startu,
czas meczu (domyślnie 30 minut) oraz strefę IANA (domyślnie `Europe/Warsaw`).
Pusta data wyłącza godziny. Ustawienie nie generuje ponownie drabinki i nie zmienia wyników.

„Start teraz” rejestruje rzeczywisty start. Pierwszy rozstrzygający wynik rejestruje
czas zakończenia; późniejsze korekty wyniku go zachowują. Przy opóźnionym wpisaniu
wyniku popraw czas w „Edytuj godziny meczu”. Planowany start jest dolnym ograniczeniem:
kort, zawodnicy, faza grupowa i źródłowe mecze muszą być dostępne. Prognozy są liczone
osobno dla każdego kortu; przekroczony czas trwającego meczu przesuwa jego następników.
Brak oznaczenia startu oznacza, że program nie wie, czy mecz rzeczywiście się rozpoczął.
Stare wyniki bez czasów korzystają z szacowanego przebiegu; nie otrzymują automatycznie
fikcyjnych rzeczywistych czasów. Godziny są też w eksporcie harmonogramu PDF i Excel.

Publiczny widok pokazuje pięć pierwszych trwających/nadchodzących meczów, rozwijaną
resztę oraz osobno rozwijane wyniki. Drabinki i tabele pozostają dostępne. Dane odświeżają
się co 15 sekund w aktywnym oknie, bez przeładowania strony i utraty pełnego ekranu.
„Tryb monitora” (`?display=1`) powiększa najbliższe mecze i dodaje zegar oraz pełny ekran.
W systemie wybierz rozszerzony pulpit, otwórz ten widok w osobnym oknie na drugim
monitorze, a na głównym pozostaw panel administratora. Wyłącz usypianie ekranu na czas turnieju.


### Sędziowie i punkty live

Włącz publiczny link oraz „Sędziowie · punkty live”. Przy każdym meczu administrator
widzi osobny 3-cyfrowy kod (również z zerem na początku), przeznaczony do wydania
przy stoliku. Sędzia otwiera mecz z publicznego widoku i wpisuje kod. Uprawnienie
obejmuje tylko ten mecz, maksymalnie przez 8 godzin. Reset lub wyłączenie paneli
unieważnia wcześniejszy dostęp; kodów nie ma w publicznym HTML ani JSON.

Domyślny sędzia to przegrany wcześniejszego spotkania na danym korcie. Przy pierwszych
meczach oraz konfliktach organizator wskazuje sędziego ręcznie. Można wybrać przegranego
konkretnego wcześniejszego meczu lub wpisać imię wybranej osoby z drużyny.

Kafelki +1 zapisują pojedyncze punkty na serwerze. Sety kończą się po osiągnięciu limitu
fazy z przewagą 2 punktów; większość wygranych setów pozwala zatwierdzić mecz. Cofnięcie
punktu działa do zatwierdzenia i pozwala otworzyć ponownie właśnie zakończony set.
Dopiero zatwierdzenie zapisuje oficjalny wynik, aktualizuje drabinkę i harmonogram.
Organizator zachowuje możliwość korekty wyniku. Punkty live są w bazie Railway;
standardowy eksport JSON zawiera oficjalne wyniki, przydziały i historię punktów, bez kodów dostępu.
Publiczny widok oraz telewizor pobierają punkty co 2 sekundy (wymagane połączenie).
Przy niepewnym zapisie panel pobiera wynik z serwera i nie ponawia sam punktu.


### Aktualizacje zdarzeń i statystyki meczów

Widoki turnieju otrzymują co 2 sekundy małe różnice JSON z wersjonowanym kursorem:
zmienione mecze, komórki drabinki, tabele grup i klasyfikację. Nie pobierają ponownie
całego dokumentu turnieju. Brak zmian zwraca HTTP 304. Przeglądarka zachowuje węzły DOM,
pełny ekran, rozwinięte sekcje, przewinięcie i niewysłane formularze. Po restarcie serwera
kursor sam odbudowuje stan. Zapis wyniku i „Start teraz” zwracają JSON i pobierają różnicę.
To transport HTTP delta z lokalnymi zdarzeniami `tournament:updated`, bez utrzymywania
połączeń WebSocket zajmujących wątki Gunicorna.

Sędzia rozpoczyna pomiar przyciskiem „Rozpocznij mecz i pomiar czasu”. Punkty mają znaczniki
UTC; cofnięcia i resety zostają w osobnym, trwałym dzienniku. „Statystyki i przebieg punktów”
pokazują skorygowany przebieg każdego seta, czas i historię korekt. Gdy brakuje historii
punktowej lub rzeczywistego startu, program nie odtwarza ich z końcowego wyniku.
Istniejąca historia bez znaczników czasu nadal pokazuje przebieg bez wymyślonych godzin.
Eksport/import bazy JSON zachowuje historię i pomiary, generując nowe kody dostępu.

„Statystyki czasu” zestawiają pomiary. Szacowanie porównuje mecze o tym samym limicie
punktów, best of i typie fazy. Korzysta z pełnych pomiarów 1 minuta–6 godzin, wyklucza
pomiary od pierwszego punktu oraz wyniki zmienione bez aktualizacji próbki. Pokazuje medianę
i kwartyle; po 5 próbkach sugeruje slot zaokrąglony w górę do 5 minut. Jest to opisowa
sugestia do ręcznej decyzji organizatora; domyślny slot nie zmienia się sam.


### Czas zawodnika i pozioma karta punktów

Panel sędziego ma dwa przyciski czasu: 2:00, raz na set na stronę (zawodnika/drużynę).
Limit i koniec przerwy sprawdza serwer, więc ponowne wejście ani drugi telefon nie
przywracają limitu. Podczas aktywnego czasu punkty i cofanie są zablokowane. Sędzia
może zakończyć przerwę wcześniej; wykorzystany limit pozostaje zużyty. Po zakończeniu
seta każda strona otrzymuje nowy limit. Informacja o czasie jest też na ekranie zawodników.
Historia zapisuje stronę, set i początek/koniec przerwy; czas całego meczu obejmuje przerwy.

Przebieg punktów ma osobną poziomą tabelę na każdy set. Dwa wiersze odpowiadają stronom,
a kolumny kolejnym zdobytym punktom. W komórce zdobywcy widnieje jego aktualny numer
punktu, a komórka przeciwnika jest pusta. Przykład: A „1, 2, pusto, 3”, B „pusto, pusto, 1, pusto”.
Tabele mają stałą kolumnę z nazwami i przewijanie poziome; cofnięcie usuwa odpowiednią kolumnę.
