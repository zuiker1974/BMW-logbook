# Tekninen määrittely: BMW-ajopäiväkirja Home Assistantin datalla (Python), versio 2

> **Muutos versioon 1:** Ajopäiväkirja ei enää avaa omaa yhteyttä BMW CarDataan. Data luetaan Home Assistantista, jossa BMW CarData -integraatio pitää jo yllä ainoaa sallittua MQTT-stream-yhteyttä. Lisäksi järjestelmä on alusta asti monen auton järjestelmä, jossa **jokainen auto käsitellään aina erikseen**: omat matkat, oma tietokanta, omat raportit, omat Drive-tiedostot ja omat HA-sensorit. Raportit tehdään PDF:nä ja muokattavana Excelinä, ja koska ne ovat verottajaa varten, määrittelyyn on lisätty mittarijatkuvuuden tarkistus, muutosloki ja jaksojen lukitus (luvut 5.3–5.5). Siirto Driveen hoidetaan HA:n Rclone Backup -lisäosalla (luku 7).

## 1. Yleiskuvaus ja tavoite
Tavoitteena on toteuttaa kevyt, itsenäinen Python-taustapalvelu ja web-käyttöliittymä, joka lukee BMW-autojen telemetrian **Home Assistantista** (HA WebSocket API), tunnistaa ajotapahtumat automaattisesti (myös lataustauot), tallentaa ajopäiväkirjan pysyvästi paikalliseen SQLite-tietokantaan ja kirjoittaa raportit ja varmuuskopiot HA:n `/share`-kansioon, josta HA:n olemassa oleva **Rclone Backup** -lisäosa siirtää ne Google Driveen.

Palvelu tarjoaa oman selainpohjaisen hallintanäkymän ajopäiväkirjan selaamiseen, matkojen luokitteluun, matkapätkien yhdistämiseen ja raportointiin. Se julkaisee omat tilatietonsa Home Assistantiin MQTT Discoveryn kautta. Järjestelmä **ei tukeudu Home Assistantin Recorderiin** pitkäaikaistallennuksessa. Recorderin historiaa käytetään ainoastaan lyhyiden katkosten paikkaamiseen (ks. 3.1).

### 1.1. Ajoneuvot
| Tunniste (`vehicle_id`) | Auto | Voimalinja | Tila HA:ssa |
|---|---|---|---|
| `530e` | BMW 530e xDrive (G30) | Lataushybridi (PHEV), noin 11 kWh:n akku, vain AC-lataus | Entiteetit olemassa |
| `ix3` | BMW iX3 (NA5) | Täyssähköauto (BEV), AC- ja DC-pikalataus | Entiteetit eivät vielä ole olemassa, lisätään kun auto tulee CarData-tilille |

### 1.2. Autojen erillisyysperiaate (koskee koko määrittelyä)
Kaksi autoa ovat **aina erillisiä kirjanpitoja**. Tämä ei ole pelkkä suodatin, vaan rakenteellinen sääntö:
1. Jokaisella autolla on oma tilakone, oma SQLite-tietokanta, oma aktiivisen ajon tilatiedosto ja omat asetukset.
2. Käyttöliittymässä ei ole "kaikki autot" -näkymää. Valittu auto näkyy aina näkymän otsikossa ja URL-polussa.
3. Matkoja voi yhdistää vain saman auton sisällä. Eri autojen matkoja ei voi valita samaan yhdistämiseen, ja tietokantataso estää sen myös.
4. Raportit (PDF/Excel), Drive-kansiot ja -kansiot sekä HA-sensorit ovat autokohtaisia, ja auton tunniste on aina tiedostonimessä ja entiteetin tunnisteessa.
5. Yhteenvedot ja prosenttiosuudet (työajo-%) lasketaan aina yhden auton matkoista.

### Referenssitoteutus
Toimintalogiikka ja tilakone mukautetaan avoimen lähdekoodin projektista:
* **Repositorio:** `https://github.com/JonathanSchndr/bmw-logbook`
* **Hyödynnetään:**
  * Ajotunnistuksen tilakone (liikkeellelähtö + aikakatkaisupohjainen matkan päättäminen), laajennettuna lataustaukojen tuella.
  * Käänteinen geokoodaus OpenStreetMap Nominatimilla.
  * Ajopäiväkirjaraportointi sovellettuna Suomen Verohallinnon ohjeistukseen.
* **Ei hyödynnetä:** referenssin BMW OAuth 2.0 Device Code Flow -kirjautumista, tokenien hallintaa eikä suoraa MQTT-yhteyttä `mqtt.bmwgroup.com`-palvelimeen. BMW sallii vain yhden MQTT-stream-yhteyden per GCID, ja sen pitää jo HA:n BMW CarData -integraatio (`sensor.cardata_debug_device_stream_connection_status = connected`). Oma yhteys katkaisisi HA:n yhteyden tai jäisi itse ilman dataa.

---

## 2. Arkkitehtuuri ja sijoitusympäristö

Palvelu toteutetaan **Home Assistantin add-onina** (Python 3.11+, asyncio-taustaprosessi ja FastAPI-verkkopalvelin samassa prosessissa). Erillistä Docker- tai `systemd`-asennusta ei tueta.
* **Käyttöliittymä HA:n Ingressin kautta:** add-on näkyy HA:n sivupalkissa ("BMW-ajopäiväkirja"), ja kirjautuminen hoituu HA:n omalla käyttäjätunnistuksella. Porttia ei avata verkkoon (`ingress: true`, `ingress_port: 8099`, ei `ports`-määritystä).
* **HA-yhteys:** `homeassistant_api: true`, jolloin add-on käyttää Supervisorin automaattisesti antamaa tunnusta (`SUPERVISOR_TOKEN`). Pitkäikäistä tunnusta ei tarvita.
* **MQTT:** `services: ["mqtt:want"]`, jolloin Mosquitto-brokerin osoite ja tunnukset haetaan Supervisorilta automaattisesti.
* **Tallennus:** tietokannat ja sisäinen tila add-onin `/data`-hakemistossa. Raportit, arkisto ja tietokantavarmuuskopiot kirjoitetaan kansioon `/share/ajopaivakirja/` (`map: ["share:rw"]`), josta Rclone Backup -lisäosa vie ne Driveen (luku 7). Molemmat kansiot kuuluvat HA:n omiin varmuuskopioihin.
* **Ei omaa Google-yhteyttä:** add-on ei käytä Google API:a eikä OAuthia. Driveen siirto on kokonaan Rclone Backupin vastuulla, ja sen nykyinen `google_drive`-remote ja `/homeassistant/rclone.conf` säilyvät ennallaan.

```
[BMW 530e]        [BMW iX3]
     │                 │
     └──── BMW CarData Cloud (yksi MQTT-stream per GCID) ────┐
                                                             ▼
                              [Home Assistant: BMW CarData -integraatio]
                               (entiteetit per auto: sijainti, mittari,
                                liiketila, lataustila, SoC ...)
                                             │
                     HA WebSocket API (vain luku: subscribe_entities)
                                             ▼
                 [HA-add-on: ajopäiväkirjapalvelu & Web UI (Ingress)]
                   ├─ Tilakone 530e ──► data/530e/logbook.db
                   ├─ Tilakone ix3  ──► data/ix3/logbook.db
                   ├─► Web UI (autovalinta → listanäkymä, yhdistäminen, PDF/CSV)
                   ├─► PDF- ja CSV-raportit (autokohtaiset)
                   ├─► /share/ajopaivakirja/<auto>/ ──► [Rclone Backup] ──► Google Drive
                   └─► HA MQTT-broker (Discovery: autokohtaiset logbook-sensorit)
```

---

## 3. Toiminnalliset vaatimukset

### 3.1. Datan lukeminen Home Assistantista

#### 3.1.1. Valittu tapa: HA WebSocket API (suositus)
Palvelu yhdistää HA:n WebSocket-rajapintaan (`ws://supervisor/core/websocket`, tunnisteena `SUPERVISOR_TOKEN`) ja tilaa vain konfiguraatiossa nimettyjen entiteettien muutokset komennolla `subscribe_entities` (`entity_ids`-lista). Kirjastona esim. `aiohttp` tai `hass-client`.

Perustelut verrattuna vaihtoehtoon, jossa HA välittää tilat paikalliseen MQTT-brokeriin:
* **Ei muutoksia HA:hon.** MQTT-välitys vaatisi uuden `mqtt_statestream`-konfiguraation tai automaation HA:ssa. WebSocket toimii add-onin valmiilla tunnuksella.
* **Attribuutit ja aikaleimat mukana.** `device_tracker`-entiteetin koordinaatit ovat attribuutteja (`latitude`, `longitude`, `gps_heading_deg`), ja jokaisessa muutoksessa tulee HA:n `last_updated`-aika. Tilakone käyttää tätä aikaa, ei vastaanottohetkeä.
* **Katkosten paikkaus.** Uudelleenyhdistettäessä puuttuva jakso haetaan HA:n historiasta (`history/history_during_period`, vain konfiguroidut entiteetit, enintään esim. 24 h taaksepäin). Tämä on ainoa Recorderin käyttö.
* **Vain luku.** Palvelu ei kutsu HA:n palveluita eikä muuta entiteettejä.

Vaihtoehto (ei suositella): `mqtt_statestream` → Mosquitto → palvelu tilaa aiheet. Kevyt kuluttaja, mutta vaatii HA-konfiguraatiomuutoksen, välittää attribuutit erillisinä aiheina ja ei tarjoa historiaa katkosten jälkeen.

#### 3.1.2. Entiteettikartoitus per auto
Jokaiselle autolle määritellään konfiguraatiossa (ks. luku 8) sen omat HA-entiteetit roolin mukaan. Koodi ei sisällä yhtään kovakoodattua entiteettitunnistetta.

| Rooli | Pakollinen | 530e (tarkistettu HA:sta 17.11.2026) | iX3 |
|---|---|---|---|
| `location` (device_tracker, attribuutit `latitude`/`longitude`) | Kyllä | `device_tracker.530e_xdrive_location` | täytetään myöhemmin |
| `odometer` (km) | Kyllä | `sensor.530e_xdrive_vehicle_mileage` | täytetään myöhemmin |
| `motion` (binary_sensor, `on` = liikkeessä) | Suositeltu | `binary_sensor.autot_530e_xdrive_vehicle_motion_state` | täytetään myöhemmin |
| `soc` (%) | Valinnainen | `sensor.530e_xdrive_battery_ev_state_of_charge` | täytetään myöhemmin |
| `charging_state` (`CHARGING` / `NOCHARGING` ...) | Suositeltu | `sensor.charging_ev_charging_state` | täytetään myöhemmin |
| `charging_method` (esim. `AC_TYPE2PLUG`, DC) | Valinnainen | `sensor.charging_ev_charging_method` | täytetään myöhemmin |
| `hv_system_state` | Valinnainen | `sensor.charging_ev_hv_system_state` | täytetään myöhemmin |

**Huomio entiteettien nimistä:** 530e:n latausentiteeteissä ei ole auton nimeä (`sensor.charging_ev_*`). Kun iX3 lisätään CarData-integraatioon, HA todennäköisesti antaa iX3:n vastaaville entiteeteille päätteen (esim. `sensor.charging_ev_charging_state_2`). Siksi:
* iX3:n entiteetit kartoitetaan käsin laitteen (device) perusteella HA:n laiterekisteristä, ei nimen arvaamalla.
* 530e:n olemassa olevia entiteettejä **ei nimetä uudelleen**, koska seuraavat automaatiot riippuvat niistä: *ABB - Latauksen oppiminen (530e)*, *ABB - Muistutus kytkemättä jääneestä 530e:stä* ja *Dynaaminen latausvirran säätö*.
* Palvelu tarkistaa käynnistyessään, että jokainen kartoitettu entiteetti on olemassa, ja kirjaa varoituksen sekä näyttää sen käyttöliittymässä. Puuttuvien entiteettien auto (esim. iX3 ennen toimitusta) on tilassa `NOT_CONFIGURED` eikä vaikuta toisen auton toimintaan.

#### 3.1.3. Vaikutus olemassa oleviin automaatioihin
Palvelu on HA:n suhteen pelkkä lukija. Se ei muuta, nimeä uudelleen, poista tai kirjoita yhtäkään olemassa olevaa entiteettiä, eikä se avaa BMW-yhteyttä. Ainoa asia, jonka palvelu tuo HA:hon, on uusia, omalla `bmw_logbook_`-etuliitteellä nimettyjä MQTT Discovery -entiteettejä (luku 6). Näin edellä mainitut kolme latausautomaatiota toimivat kuten ennenkin.

#### 3.1.4. Datan ominaisuudet, jotka tilakoneen on siedettävä
* CarData-stream lähettää päivityksiä harvakseltaan, kun auto on pysäköitynä (esim. viimeisin viesti saattaa olla tuntien takaa). Pitkä hiljaisuus ei siis yksin tarkoita mitään.
* Tilat voivat hetkellisesti olla `unavailable` / `unknown` (esim. HA:n uudelleenkäynnistys). Näitä arvoja ei käsitellä mittausarvoina, vaan ne ohitetaan.
* Matkamittari ja sijainti voivat päivittyä eri viesteissä. Tilakone yhdistää ne `last_updated`-aikojen perusteella.

### 3.2. Ajotunnistuksen tilakone ja lataustaukojen hallinta
Jokaisella autolla on **oma, toisistaan riippumaton** tilakoneinstanssi. Tilakone saa tapahtumia vain oman autonsa entiteeteistä.

1. **Lepotila (`IDLE`):** Viimeisin tunnettu sijainti, mittarilukema ja lataustila pidetään muistissa.
2. **Ajon alkaminen (`IDLE` → `DRIVING`):** Ajo alkaa, kun jokin seuraavista toteutuu (ensimmäinen ratkaisee):
   * `motion`-entiteetti vaihtuu tilaan `on` (ensisijainen signaali, jos kartoitettu),
   * sijainti siirtyy yli `trip_start_distance_m` (oletus 100 m, Haversine) edellisestä tunnetusta sijainnista, tai
   * mittarilukema kasvaa vähintään 1 km.
   * Matkan aloitustiedoiksi otetaan **ajoa edeltävä viimeisin pysäköintisijainti ja -mittarilukema** (ei ensimmäistä liikkeessä mitattua pistettä), jotta harvat päivitykset eivät lyhennä matkaa.
   * Lähtöosoite haetaan taustalla (Nominatim).
3. **Ajon aikana (`DRIVING`):** Päivitetään viimeisin sijainti, mittarilukema, lataustila ja `last_movement_time`.
4. **Pysähdys ja lataustauko (`DRIVING` → `PAUSED_CHARGING` / `IDLE`):**
   * **Tavallinen pysähdys:** Jos auto ei lataa ja liikettä ei havaita `trip_end_timeout_s` sekunnissa (oletus 600 s) tai `motion` on ollut `off` saman ajan, matka päätetään.
   * **Lataustauko kesken matkan:** Jos `charging_state` muuttuu tilaan `CHARGING` pysähdyksen aikana, siirrytään tilaan `PAUSED_CHARGING`, ja matkaa ei katkaista tavallisella aikakatkaisulla. Sen sijaan sovelletaan autokohtaista `charging_pause_timeout_s`-arvoa.
     * Jos auto lähtee liikkeelle ennen aikakatkaisua, matka jatkuu samana ajona ja välipysähdys/lataus kirjataan (`charging_stops`-tauluun).
     * Jos aikakatkaisu umpeutuu (esim. yöksi lataukseen), matka päätetään hetkeen `last_movement_time`.
   * **Kotilataus ei ole lataustauko:** Jos auto on pysähtynyt HA:n `zone.home`-alueelle (tai muulle konfiguroidulle "päätepisteet"-vyöhykkeelle), matka päätetään tavallisella aikakatkaisulla latauksesta riippumatta.
5. **Autokohtaiset oletukset:**
   * **iX3 (BEV):** lataustauot ovat pitkillä matkoilla tavallisia ja olennaisia. `charging_pause_timeout_s = 5400` (90 min). DC-pikalatauksen (`charging_method` = DC) aikana tauko tunnistetaan aina lataustauoksi.
   * **530e (PHEV):** lataus kesken matkan on harvinaista (vain AC, pieni akku), ja auto voi jatkaa bensiinillä. `charging_pause_timeout_s = 2700` (45 min) oletuksena; arvo on säädettävissä ja tarvittaessa kytkettävissä pois (`charging_pause_enabled: false`).
6. **Matkan päättäminen:** Kirjataan `end_time`, `end_lat`, `end_lon`, `end_odometer`; `distance_km = end_odometer - start_odometer` (varalla GPS-reitin pituus). Haetaan pääteosoite ja tallennetaan matka auton omaan tietokantaan.

### 3.3. Paikallinen tietokanta (ei HA Recorderia)
* **Jokaisella autolla on oma SQLite-tiedosto**: `data/<vehicle_id>/logbook.db` (esim. `data/530e/logbook.db`, `data/ix3/logbook.db`) pysyvällä levyllä. Erilliset tiedostot takaavat, ettei eri autojen matkoja voi sekoittaa kyselyvirheelläkään, ja ne voi varmuuskopioida ja palauttaa erikseen.
* Jokaisessa tietokannassa on taulu `vehicle_info` (`vehicle_id`, `vin`, `make`, `model`, `plate`, `driver`, `valid_from`; uusi rivi aina, kun add-onin asetussivun autotiedot muuttuvat, ks. luku 8), ja palvelu tarkistaa käynnistyksessä, että tiedosto kuuluu oikealle autolle.
* **Taulu `trips`:**
  * `id` (INTEGER PRIMARY KEY AUTOINCREMENT)
  * `vehicle_id` (TEXT NOT NULL, CHECK = tiedoston auto) — *varmistus myös tiedostojen erillisyyden lisäksi*
  * `start_time` (TEXT NOT NULL), `end_time` (TEXT NOT NULL)
  * `start_lat`, `start_lon` (REAL), `start_address` (TEXT)
  * `end_lat`, `end_lon` (REAL), `end_address` (TEXT)
  * `start_odometer`, `end_odometer`, `distance_km` (REAL)
  * `start_soc`, `end_soc` (REAL, valinnainen)
  * `trip_type` (TEXT DEFAULT 'private') — *`business` (Työajo), `private` (Yksityisajo), `commute` (Työmatka)*
  * `purpose` (TEXT DEFAULT '')
  * `comment` (TEXT DEFAULT '') — *vapaa kommentti, jota voi muokata sekä käyttöliittymässä että Excelissä (ks. 5.3)*
  * `comment_updated_at` (TEXT), `comment_source` (TEXT) — *`ui` tai `excel`*
  * `source` (TEXT DEFAULT 'auto') — *`auto` tai `manual`*
  * `merged_into_id` (INTEGER DEFAULT NULL), `is_merged_parent` (INTEGER DEFAULT 0)
  * `updated_at` (TEXT)
* **Taulu `trip_changes` (muutosloki, vain lisäys):** `id`, `trip_id`, `changed_at`, `field`, `old_value`, `new_value`, `source` (`ui` / `excel_drive` / `excel_upload` / `merge` / `unmerge` / `manual_add` / `gap_fill`), `reason` (TEXT). Rivejä ei koskaan muokata eikä poisteta; tietokantaan luodaan triggerit, jotka estävät `UPDATE`- ja `DELETE`-lauseet tähän tauluun.
* **Alkuperäisten mittaustietojen suojaus:** autosta tallennetut kentät (`start_time`, `end_time`, koordinaatit, `start_odometer`, `end_odometer`) tallennetaan lisäksi sarakkeisiin `orig_*`, joita sovellus ei koskaan päivitä. Jos käyttäjä korjaa aikaa, osoitetta tai mittarilukemaa, muutos tehdään varsinaiseen sarakkeeseen, kirjataan `trip_changes`-tauluun ja vaatii perustelun (`reason`). Raportissa korjattu rivi merkitään.
* **Taulu `periods`:** `year`, `month`, `status` (`open` / `locked`), `locked_at`, `report_sha256`, `odometer_start`, `odometer_end` (ks. 5.5).
* **Taulu `charging_stops`:** `id`, `trip_id`, `start_time`, `end_time`, `lat`, `lon`, `address`, `soc_start`, `soc_end`, `method` (AC/DC). Näkyy matkan lisätietoina ja raportin selitteessä.

---

## 4. Web-käyttöliittymä

Kevyt mobiili- ja työpöytäystävällinen käyttöliittymä (**FastAPI + HTMX / Alpine.js**), näkyy HA:n sivupalkissa Ingressin kautta. Käyttöliittymässä on myös **Asetukset**-sivu, jossa näkyvät entiteettien tarkistus, `/share`-kansion viimeisimmät kirjoitukset ja Excel-tuontien tila.

### 4.1. Autovalinta
* Etusivu näyttää autot kortteina (nimi, rekisterinumero, tila: Pysäköity / Ajossa / Lataustauolla / Ei konfiguroitu).
* Kaikki näkymät ovat auton polun alla: `/v/530e/...`, `/v/ix3/...`. Valittu auto näkyy otsikossa selvästi (nimi + rekisterinumero), ja autoa vaihdetaan välilehdillä yläpalkissa.
* Viimeksi valittu auto muistetaan selaimessa.

### 4.2. Listanäkymä ja pikamuokkaus (auton sisällä)
* **Suodatus:** vuosi, kuukausi ja ajotyyppi. Näytetään aktiiviset matkat (`merged_into_id IS NULL`) vain valitulta autolta.
* **Sarakkeet:**
  1. Valintaruutu yhdistämistä varten.
  2. Päivämäärä ja kellonaika (alku – loppu).
  3. Lähtöosoite → pääteosoite (muokattavissa). Lataustauot näytetään kuvakkeella.
  4. Matkamittari (alku – loppu) ja km.
  5. Ajotyyppi pikavalintana (Työajo / Yksityisajo / Työmatka).
  6. Selite tekstikenttänä, tallentuu automaattisesti (`onblur` / Enter).
  7. Kommentti tekstikenttänä (sama kenttä kuin Excelin kommenttisarake). Excelistä tuotu kommentti merkitään pienellä Excel-kuvakkeella.

### 4.3. Matkapätkien yhdistäminen ja purkaminen
* **Yhdistäminen vain saman auton sisällä.** Koska lista näyttää aina yhden auton matkat, valinta voi sisältää vain sen auton matkoja. Rajapinta (`POST /v/<vehicle_id>/trips/merge`) hylkää pyynnön, jos yksikin id ei löydy kyseisen auton tietokannasta.
* Yhdistetty rivi: alkutiedot ensimmäisestä, lopputiedot viimeisestä matkasta, `distance_km` mittarilukemista (varalla osamatkojen summa), `trip_type` = `business`, jos yksikin osa oli työajo, muuten ensimmäisen matkan tyyppi, `purpose` yhdistää osien selitteet.
* Osamatkat merkitään `merged_into_id = <uusi_id>`.
* **Purkaminen:** "Pura yhdistäminen" palauttaa osamatkat näkyviin ja poistaa yhdistetyn rivin.

### 4.4. Yhteenvetopalkki ja manuaalinen lisäys
* Valitun auton ja ajanjakson kokonais-km sekä erittely: työajot (km, %), yksityisajot (km, %), työmatkat (km).
* Puuttuvan ajon voi lisätä käsin. Lomake on aina sen auton alla, jota katsotaan, eikä siinä ole autovalintaa. Käsin lisätty ajo merkitään (`source = manual`), sen lisäys kirjataan muutoslokiin, ja raportissa se näkyy merkinnällä "käsin lisätty".
* **Mittarilukemien aukot** näytetään listassa omina varoitusriveinään matkojen välissä (ks. 5.4), ja niistä voi suoraan luoda käsin lisätyn ajon.
* Rivin historian (muutosloki) saa auki rivikohtaisesta kuvakkeesta.

### 4.5. Raporttien lataus selaimella
* Auton näkymässä on **Raportit**-osio, josta valitulle kuukaudelle tai vuodelle voi ladata selaimella tietokoneelle: PDF-kuukausiraportin, PDF-vuosiraportin ja Excel-vuosityökirjan (`Content-Disposition: attachment`, tiedostonimet luvun 5.1 mukaan). CSV on ladattavissa, jos se on otettu käyttöön.
* **Ajotyyppisuodatin:** latauksen yhteydessä valitaan *Kaikki ajot* (oletus), *Vain työajot* tai *Vain yksityisajot*. Yksityisajoihin sisältyvät työmatkat (asunnon ja työpaikan väliset ajot) oletuksena, koska verotuksessa ne luetaan yksityisajoiksi. Valinnan voi muuttaa ruksilla "sisällytä työmatkat". Lisäksi on valinta *Vain työmatkat*. Suodatin koskee sekä PDF:ää että Exceliä (5.6).
* Lataus tehdään aina tuoreesta tietokannan tilasta. Lukitun jakson PDF ladataan arkistoidusta, muuttumattomasta tiedostosta (5.5).
* Samassa osiossa on "Tuo Excel" (5.3) ja jakson lukitus (5.5).

---

## 5. PDF- ja Excel-raportointi

Raportit noudattavat Verohallinnon ajopäiväkirjavaatimuksia. PDF tehdään `WeasyPrint`- tai `ReportLab`-kirjastolla ja Excel (.xlsx) `openpyxl`-kirjastolla. **Jokainen raportti koskee täsmälleen yhtä autoa.** Yhdistettyä usean auton raporttia ei tehdä. Mukaan otetaan vain aktiiviset matkat (`merged_into_id IS NULL`).

PDF on lukittu, arkistoitava versio (esim. verottajalle). Excel on työkopio, jota voi täydentää kommenteilla, ja kommentit tuodaan takaisin ajopäiväkirjaan (5.3).

### 5.1. Tiedostot (per auto)
1. Kuukausiraportti: `Ajopaivakirja_<vehicle_id>_<REKNRO>_YYYY_MM.pdf` (esim. `Ajopaivakirja_530e_ABC-123_2026_11.pdf`)
2. Vuosiraportti: `Ajopaivakirja_<vehicle_id>_<REKNRO>_YYYY_vuosiraportti.pdf`
3. Excel-vuosityökirja: `Ajopaivakirja_<vehicle_id>_<REKNRO>_YYYY.xlsx` (yksi tiedosto per auto per vuosi)
4. CSV (valinnainen, oletuksena pois): `Ajopaivakirja_<vehicle_id>_<REKNRO>_YYYY.csv`
5. Ajotyypin mukaan suodatetut tulosteet (5.6) saavat tiedostonimeen päätteen: `_tyoajot`, `_yksityisajot` tai `_tyomatkat`, esim. `Ajopaivakirja_530e_ABC-123_2026_11_tyoajot.pdf` ja `Ajopaivakirja_ix3_XYZ-789_2026_yksityisajot.xlsx`.

### 5.2. Sisältö

**Verohallinnon edellyttämät tiedot.** Raportissa on oltava ainakin seuraavat (Verohallinnon ohje ajopäiväkirjasta; tarkistetaan voimassa olevasta ohjeesta ennen käyttöönottoa):
* Auton tiedot: rekisterinumero ja malli.
* Matkamittarin lukema verovuoden (jakson) alussa ja lopussa.
* Jokaisesta ajosta: päivämäärä, matkamittarin lukema ajon alussa ja lopussa, ajetut kilometrit, lähtö- ja määräpaikka, ajoreitti (jos se ei ole suorin tai ilmeinen), ajon tarkoitus (työajossa esim. asiakas tai tehtävä) sekä kuljettaja, jos autoa ajaa useampi henkilö.
* Yhteenveto: työajojen ja yksityisajojen kilometrit ja niiden osuudet.

Sovellus estää jakson lukituksen (5.5), jos jollakin työajoksi merkityllä ajolla ei ole tarkoitusta, ja varoittaa siitä listassa jo aiemmin. Raportissa ei ole tyhjiä pakollisia kenttiä ilman merkintää.
* **Otsikko-osa:** auton merkki, malli, voimalinja (PHEV/BEV), rekisterinumero, VIN, kuljettaja, raportointijakso, mittarilukema jakson alussa ja lopussa, kokonais-km, työajot km ja %, yksityisajot km ja %. Auton tunniste ja rekisterinumero toistuvat jokaisen sivun ylätunnisteessa.
* **Vuosiraportin kuukausierittely:** tammi–joulu (alkulukema, loppulukema, työajot km, yksityisajot km, yhteensä km), jokainen kuukausi omana osionaan.
* **Ajokohtainen taulukko:** päivämäärä, alku- ja loppuaika, lähtö- ja päätepaikka, mittarilukemat, km, ajotyyppi, tarkoitus. Lataustauot merkitään selitteeseen (esim. "Lataustauko 35 min, Ionity Jyväskylä").
* **PDF** sisältää myös kommentin, jos se on täytetty.
* **CSV** (jos käytössä) sisältää samat ajokohtaiset sarakkeet sekä `vehicle_id`- ja `rekisterinumero`-sarakkeet.

### 5.3. Excel-työkirja ja kommenttien tuonti takaisin

**Rakenne:**
* Välilehti **Yhteenveto**: auton tiedot (nimi, rekisterinumero, VIN, voimalinja), vuoden mittarilukemat ja kuukausierittely (tammi–joulu), laskettu kaavoilla kuukausivälilehdistä.
* Välilehdet **01 … 12**: kuukauden matkat, yksi rivi per matka. Sarakkeet: päivämäärä, alku, loppu, lähtöpaikka, päätepaikka, mittari alussa, mittari lopussa, km, ajotyyppi, tarkoitus, lataustauot, **Kommentti**, sekä piilotettu sarake **Matka-ID** (`trip_id`).
* Välilehdet **Työajot** ja **Yksityisajot** (sekä **Työmatkat**, jos niitä on): koko vuoden kyseisen ajotyypin ajot yhtenä taulukkona aikajärjestyksessä, samoilla sarakkeilla, kuukausikohtaisilla välisummilla ja vuoden kokonaissummalla. Nämä välilehdet ovat kokonaan lukittuja (vain luku), ja niiden yläreunassa on ohje: "Kommentit kirjoitetaan kuukausivälilehdille". Näin samaa matkaa ei voi kommentoida kahdessa paikassa ristiriitaisesti.
* Välilehti **_meta** (piilotettu): `vehicle_id`, VIN, vuosi, luontiaika ja jokaisen rivin viedyt arvot (ajotyyppi, tarkoitus, kommentti) muutosten tunnistamista varten.
* Solujen suojaus: vain **Kommentti**-, **Ajotyyppi**- ja **Tarkoitus**-sarakkeet ovat muokattavissa (taulukon suojaus ilman salasanaa, jotta käyttäjä voi tarvittaessa poistaa sen). Ajotyypissä on pudotusvalikko (Työajo / Yksityisajo / Työmatka). Muut sarakkeet ovat lukittuja, koska ne tulevat autosta.

**Tuonti takaisin (Matka-ID:n perusteella):**
1. **Selaimesta (ensisijainen tapa):** käyttöliittymän **"Tuo Excel"**-toiminto auton näkymässä. Tiedosto ladataan selaimella, tuonti tehdään heti ja tulos näytetään.
2. **Driven kautta:** muokatun tiedoston voi tallentaa Drivessa auton kansion `tuonti/`-alikansioon. Rclone Backupin tuontijob siirtää sen kansioon `/share/ajopaivakirja/<auto>/tuonti/` (7.3), add-on tarkistaa kansion minuutin välein ja tuo tiedoston. Käsitelty tiedosto siirretään kansioon `<auto>/tuonnit/` aikaleimalla nimettynä, joten se näkyy myöhemmin Drivessa todisteena tuonnista.
   * **Drivessa olevia raporttitiedostoja ei muokata paikallaan.** Varmuuskopiojob kopioi paikallisen version Driveen aina, kun se muuttuu, ja ylikirjoittaa silloin Drivessa tehdyt muutokset. Tämä kerrotaan myös Excelin Yhteenveto-välilehdellä: "Tämä on varmuuskopio. Tallenna kommentoitu versio auton tuonti-kansioon tai tuo se ajopäiväkirjan selainnäkymässä." 
3. Tuonnissa tarkistetaan, että `_meta`-välilehden `vehicle_id` ja VIN vastaavat auton tietoja (ja Driven kautta tuotaessa myös sitä, minkä auton `tuonti/`-kansiossa tiedosto oli). **Toisen auton Exceliä ei voi tuoda**, vaan tuonti hylätään. Hylätty tiedosto siirretään kansioon `<auto>/tuonnit/hylatyt/` ja syy näytetään käyttöliittymässä sekä sensorissa `sensor.bmw_logbook_<vehicle_id>_last_import`.
4. Rivit yhdistetään `trip_id`:n perusteella. Rivit, joilla ei ole tunnettua Matka-ID:tä (esim. käyttäjän lisäämät), raportoidaan käyttäjälle eikä niitä tuoda automaattisesti.
5. Kenttä tuodaan vain, jos se on **muuttunut Excelissä** (eroaa `_meta`-välilehden viedystä arvosta). Jos sama kenttä on muuttunut myös käyttöliittymässä viennin jälkeen, kyseessä on ristiriita: molemmat versiot näytetään käyttöliittymässä valittaviksi, eikä kumpaakaan ylikirjoiteta hiljaa. Kommenttien kohdalla oletuksena on yhdistäminen (molemmat tekstit erotettuna).
6. Jos matka on viennin jälkeen yhdistetty toiseen, Excelin kommentti siirretään yhdistetylle päämatkalle (`merged_into_id`-viittauksen kautta).
7. Jokainen tuonti kirjataan (`import_log`-taulu: aika, lähde Drive-tuonti/selain, tiedostonimi, muuttuneet rivit), ja jokainen tuotu muutos kirjataan myös muutoslokiin (`trip_changes`, lähde `excel_drive` tai `excel_upload`). Tuonnin tulos näytetään käyttöliittymässä.

**Kommenttien pitäminen erillään alkuperäisestä datasta:**
* Excelistä tuodaan ensisijaisesti vain **Kommentti**-sarake, joka tallennetaan omaan `comment`-kenttäänsä. Se ei koskaan korvaa autosta tullutta tietoa (ajat, paikat, mittarilukemat) eikä ajon tarkoitusta.
* Lukitut mittaussarakkeet ohitetaan tuonnissa aina, vaikka käyttäjä olisi poistanut taulukon suojauksen ja muuttanut niitä. Tällaiset poikkeamat raportoidaan tuonnin yhteenvedossa ("Excelissä muutettu lukittua tietoa, ei tuotu").
* Ajotyypin ja tarkoituksen muutokset Excelistä tuodaan vain avoimelle jaksolle ja muutoslokin kautta. Lukitulle jaksolle niitä ei tuoda.
* Kommentti näkyy raporteissa omana sarakkeenaan "Kommentti (lisätieto)", erillään ajon tarkoituksesta.
* Lukitun jakson ajoille kommentin voi edelleen lisätä jälkikommenttina: se kirjataan muutoslokiin päivättynä eikä muuta lukittua PDF:ää (näkyy seuraavassa tulosteessa merkinnällä "lisätty lukituksen jälkeen").

### 5.4. Mittarilukemien jatkuvuus ja aukkojen tunnistus
* Saman auton peräkkäisten aktiivisten matkojen välillä tarkistetaan, että `start_odometer(n) = end_odometer(n-1)`. Toleranssi on `odometer_gap_tolerance_km` (oletus 1 km, CarDatan pyöristysten vuoksi).
* **Aukko** (seuraava matka alkaa suuremmalla lukemalla) tarkoittaa kirjaamatonta ajoa. Se näytetään listassa varoitusrivinä ("Kirjaamatta 23 km, 12.11. klo 17:40 – 13.11. klo 07:15"), ja käyttäjä voi luoda siitä käsin lisätyn ajon (`source = gap_fill`, oletuksena yksityisajo). Aukkoja voi syntyä esim. CarData-streamin katkoksesta.
* **Päällekkäisyys** (seuraava matka alkaa pienemmällä lukemalla) tai matka, jonka loppulukema on pienempi kuin alkulukema, merkitään virheeksi.
* Jakson alku- ja loppulukemaa verrataan HA:n mittarilukemaan (`odometer`-entiteetin historia) jakson rajalla, ja ero näytetään.
* Jaksoa **ei voi lukita**, jos siinä on käsittelemättömiä aukkoja tai virheitä. Aukon voi kuitata myös perustellusti ilman ajon lisäämistä (esim. "auto huollossa, korjaamon koeajo"), ja kuittaus kirjataan muutoslokiin ja näkyy raportissa.
* Raportin yhteenvedossa ilmoitetaan: jakson kokonais-km mittarilukemista, kirjattujen ajojen summa ja niiden erotus (tavoite 0).

### 5.5. Jakson lukitus ja arkistointi
* Kuukausi lukitaan käyttäjän toimesta (tai automaattisesti, kun kuukauden päättymisestä on kulunut `auto_lock_after_days`, oletus 15 päivää, ja tarkistukset ovat kunnossa).
* Lukittaessa:
  1. Ajetaan tarkistukset: mittarijatkuvuus (5.4) ja pakolliset kentät (5.2).
  2. Käsitellään `tuonti/`-kansiossa odottavat Excelit (5.3).
  3. Luodaan lopullinen kuukausi-PDF ja tallennetaan se muuttumattomana arkistoon: `/share/ajopaivakirja/<auto>/arkisto/`, josta Rclone vie sen Driveen. Arkistotiedostoja ei koskaan ylikirjoiteta, ja koska varmuuskopiojob käyttää `copy`-komentoa, Drivesta ei myöskään poisteta mitään.
  4. PDF:n SHA-256-tiiviste tallennetaan `periods`-tauluun ja tulostetaan PDF:n alatunnisteeseen yhdessä luontiajan ja sovellusversion kanssa. Tiivisteellä voi jälkikäteen osoittaa, ettei arkistoitua raporttia ole muutettu.
* Lukitun jakson matkoja ei voi muokata, yhdistää, purkaa eikä poistaa (vain jälkikommentit, 5.3). Lukituksen voi avata vain erillisellä toiminnolla, joka vaatii perustelun, kirjataan muutoslokiin ja tuottaa uudelleenlukittaessa uuden arkistoversion (`_v2`) vanhaa poistamatta.
* Vuoden päätyttyä ja kaikkien kuukausien ollessa lukittuja luodaan lukittu vuosiraportti (PDF) ja vuoden Excel-työkirjan arkistokopio samalla tavalla.
* Muutosloki voidaan tulostaa raportin liitteeksi (PDF-vuosiraportin loppuun "Muutoshistoria"-osio: käsin lisätyt ajot, korjaukset, kuitatut aukot).


### 5.6. Ajotyypin mukaan suodatetut tulosteet
* **PDF:** valitulla ajotyypillä tulostetaan sama raporttipohja, mutta ajokohtainen taulukko sisältää vain kyseisen ajotyypin ajot. Taulukon lopussa on välisumma kuukausittain ja jakson summa.
  * Otsikko-osassa on selvä merkintä "Osaraportti: vain työajot" (tai yksityisajot / työmatkat). Otsikko-osan yhteenvedossa näytetään silti koko jakson mittarilukemat, kokonais-km sekä työ- ja yksityisajojen kilometrit ja osuudet, jotta osaraportin voi suhteuttaa kokonaisuuteen.
  * Osaraportti on aina lisätuloste. Jakson virallinen, arkistoitu raportti on koko jakson raportti (5.5). Lukittaessa arkistoidaan lisäksi työajojen osaraportti, koska sitä tarvitaan yleisimmin (asetus `archive_filtered: [business]`).
* **Excel:** vuosityökirjassa on aina ajotyyppikohtaiset välilehdet (5.3). Lisäksi suodatetun Excelin voi ladata erillisenä tiedostona. Siinä on Yhteenveto-välilehti ja kuukausivälilehdet vain valitun ajotyypin ajoilla, sekä kommenttisarake. Suodatetun tiedoston kommentit voi tuoda takaisin samalla tavalla Matka-ID:n perusteella (`_meta`-välilehdelle kirjataan käytetty suodatin).
* Suodatus tehdään aina yhden auton sisällä, kuten kaikki muukin raportointi.

---

## 6. Home Assistant -integraatio (MQTT Discovery, autokohtaiset entiteetit)
Palvelu julkaisee paikalliseen HA:n MQTT-brokeriin (Mosquitto) Discovery-viestit. **Jokaiselle autolle luodaan oma HA-laite** (`BMW-ajopäiväkirja 530e`, `BMW-ajopäiväkirja iX3`) ja omat entiteetit, joiden tunnisteessa on auton tunniste:

* `sensor.bmw_logbook_<vehicle_id>_status` (`Pysäköity` / `Ajossa` / `Lataustauolla` / `Ei konfiguroitu`)
* `sensor.bmw_logbook_<vehicle_id>_last_trip_distance` (km)
* `sensor.bmw_logbook_<vehicle_id>_last_trip_route` (lähtö → pääte)
* `sensor.bmw_logbook_<vehicle_id>_month_business_km` ja `..._month_private_km`
* `sensor.bmw_logbook_<vehicle_id>_last_export` (aika, jolloin auton raportit viimeksi kirjoitettiin `/share`-kansioon)
* `sensor.bmw_logbook_<vehicle_id>_last_import` (viimeisimmän Excel-tuonnin aika ja tulos)
* *(Valinnainen pikaluokittelu)* `select.bmw_logbook_<vehicle_id>_last_trip_type` ja `text.bmw_logbook_<vehicle_id>_last_trip_purpose`

Versiosta 1 poistetaan `device_tracker.bmw_logbook_location` ja `sensor.bmw_logbook_odometer`, koska CarData-integraatio tarjoaa jo sijainnin ja mittarilukeman (päällekkäisiä entiteettejä ei luoda). MQTT-aiheet: `bmw_logbook/<vehicle_id>/...`. Nämä ovat uusia entiteettejä eivätkä muuta olemassa olevia.

Brokerin tunnukset saadaan Supervisorilta (`services: mqtt:want`). Jos Mosquittoa ei ole asennettu, HA-sensorit jäävät pois (`ha_mqtt_enabled: false`), eikä se vaikuta ajopäiväkirjan toimintaan.

---

## 7. Varmuuskopiointi Google Driveen (Rclone Backup -lisäosan kautta)

Add-on ei ota itse yhteyttä Googleen. Se kirjoittaa kaikki siirrettävät tiedostot kansioon `/share/ajopaivakirja/`, ja HA:ssa jo käytössä oleva **Rclone Backup** -lisäosa vie ne Driveen samalle `google_drive`-remotelle, jota nykyinen *Latauslogit*-job käyttää. Nykyiseen jobiin ja tiedostoon `/homeassistant/rclone.conf` ei kosketa. Lisätään vain kaksi uutta jobia (7.3).

### 7.1. Kansiorakenne (paikallisesti ja Drivessa sama)
Rakenne noudattaa Latauslokien mallia (`Latauslokit/2026/<kuukausi>/`), mutta ylimpänä tasona on auto, jotta autot pysyvät kokonaan erillään. Kuukausikansion nimi on oletuksena kaksinumeroinen kuukausi (`11`). Muodon voi vaihtaa asetuksella `month_folder_format`, jos se halutaan täsmälleen samaksi kuin Latauslokeissa.

```
/share/ajopaivakirja/                     →  google_drive:Ajopaivakirja/
├── 530e_ABC-123/
│   ├── 2026/
│   │   ├── Ajopaivakirja_530e_ABC-123_2026.xlsx
│   │   ├── Ajopaivakirja_530e_ABC-123_2026_vuosiraportti.pdf
│   │   ├── 11/
│   │   │   ├── Ajopaivakirja_530e_ABC-123_2026_11.pdf
│   │   │   ├── Ajopaivakirja_530e_ABC-123_2026_11_tyoajot.pdf
│   │   │   └── Ajopaivakirja_530e_ABC-123_2026_11_yksityisajot.pdf
│   │   └── 12/ ...
│   ├── arkisto/2026/                      (lukitut jaksot, ei koskaan ylikirjoiteta, 5.5)
│   ├── varmuuskopiot/bmw_logbook_530e_backup_2026-11.db
│   ├── tuonti/                            (Drivesta tuotavat Excelit, ei varmuuskopioida)
│   └── tuonnit/                           (käsitellyt ja hylätyt tuonnit)
└── ix3_XYZ-789/
    └── (sama rakenne)
```

* Auton kansion nimi on `<vehicle_id>_<rekisteritunnus>`. Jos rekisteritunnus muuttuu, kansiota ei nimetä uudelleen (vanhat tiedostot säilyvät), vaan uudet tiedostot kirjoitetaan uuden nimiseen kansioon ja muutos kirjataan muutoslokiin.
* Kansio luodaan add-onin ensimmäisellä käynnistyksellä.

### 7.2. Mitä add-on kirjoittaa ja milloin
1. **Tietokantavarmuuskopio:** kerran vuorokaudessa klo 03:00 ja jokaisen päättyneen matkan jälkeen auton tietokanta kopioidaan `sqlite3`:n backup API:lla tiedostoon `varmuuskopiot/bmw_logbook_<vehicle_id>_backup_YYYY-MM.db` (kuukauden tiedosto päivittyy kuun aikana). Paikallisesti säilytetään 12 kuukautta. Drivesta vanhoja ei poisteta, koska job käyttää `copy`-komentoa (tiedostot ovat pieniä).
2. **Raportit:** kun auton matkoja muutetaan tai uusi matka päättyy (viive 5 min), sekä kuukauden vaihtuessa, kirjoitetaan uudelleen **vain sen auton** kuluvan kuukauden PDF:t (myös työ- ja yksityisajojen osaraportit), vuosiraportti ja Excel-työkirja.
3. **Lukitut jaksot** kirjoitetaan `arkisto/`-kansioon (5.5).
4. **Atominen kirjoitus:** jokainen tiedosto kirjoitetaan ensin väliaikaisella nimellä (`.tmp`) ja nimetään lopulliseksi vasta valmiina, jotta Rclone ei koskaan siirrä puolivalmista tiedostoa. Rclone-job ohittaa `.tmp`-tiedostot.

### 7.3. Rclone Backupin jobit
Raporttien päivittyminen Driveen riippuu **jobin aikataulusta**. Selaimesta (luku 4.5) raportit ladataan aina heti tietokannan nykytilasta, joten Driveen ei tarvitse odottaa. Drive on varmuuskopio ja arkisto, ei ensisijainen tapa hakea raportteja.

Lisättävät jobit (muoto sama kuin nykyisessä Latauslogit-jobissa):

```yaml
jobs:
  - name: Latauslogit                      # NYKYINEN, ei muuteta
    schedule: 30 12 * * *
    command: copy
    source: /share/charging_logs
    destination: google_drive:Latauslokit

  - name: Ajopaivakirja                    # UUSI: raportit ja varmuuskopiot Driveen
    schedule: 20 3 * * *                   # päivittäin 03:20, DB-varmuuskopion jälkeen
    command: copy                          # copy, ei sync: Drivesta ei koskaan poisteta mitään
    source: /share/ajopaivakirja
    destination: google_drive:Ajopaivakirja
    exclude:
      - "*/tuonti/**"
      - "*.tmp"

  - name: Ajopaivakirja tuonti             # UUSI: Driven tuonti-kansiot takaisin HA:han
    schedule: "*/15 * * * *"               # 15 minuutin välein
    command: move                          # siirtää tiedoston pois Drivesta, kun se on haettu
    source: google_drive:Ajopaivakirja
    destination: /share/ajopaivakirja
    include:
      - "*/tuonti/*.xlsx"
```

* Jos Driven halutaan päivittyvän tiheämmin, varmuuskopiojobin aikatauluksi voi vaihtaa esim. `5 * * * *` (kerran tunnissa). Rclone siirtää vain muuttuneet tiedostot, joten tiheämpi ajo on kevyt.
* `copy` ylikirjoittaa Drivessa tiedoston, jonka paikallinen versio on muuttunut. Siksi Drivessa olevia raportteja ei muokata paikallaan, vaan kommentoitu Excel tallennetaan `tuonti/`-kansioon (5.3).
* Add-on ei näe, onnistuiko Rclone-siirto. Siirron tila tarkistetaan Rclone Backupin lokista. Add-on näyttää omalta osaltaan, milloin tiedostot viimeksi kirjoitettiin (`sensor.bmw_logbook_<vehicle_id>_last_export`).

---

## 8. Konfigurointi (add-onin asetussivu)

Kaikki asetukset syötetään **HA:n add-onin asetussivulla** (*Asetukset → Lisäosat → BMW-ajopäiväkirja → Määritykset*). `.env`-tiedostoa ei ole. Asetukset määritellään add-onin `config.yaml`-tiedoston `options`- ja `schema`-osioissa, jolloin HA näyttää ne lomakkeena, tarkistaa tyypit ja tallentaa ne tiedostoon `/data/options.json`. Add-on lukee asetukset käynnistyessään, ja muutokset tulevat voimaan add-onin uudelleenkäynnistyksellä.

**Asetussivulla syötettävät tiedot:**
* **Autot** (lista, yksi kohta per auto): tunniste, rekisteritunnus, merkki, malli, voimalinja (PHEV/BEV), VIN, kuljettaja, onko käytössä, lataustauon asetukset ja HA-entiteettien kartoitus.
* **Ajotunnistus ja raportit:** kynnysarvot ja raporttiasetukset.

Ajopäiväkirjan omalla Asetukset-sivulla (Ingress) on lisäksi:
* `/share/ajopaivakirja/`-kansion tila: viimeisimmät kirjoitetut tiedostot autoittain sekä odottavat ja käsitellyt Excel-tuonnit.
* Entiteettitarkistus: jokaisen auton kartoitetut entiteetit, niiden nykyinen tila ja puuttuvat entiteetit (korvaa komentorivityökalun).
* Rekisteritunnus ja muut autotiedot näytetään vain luku -muodossa, ja niiden vieressä on linkki add-onin asetussivulle. Näin tiedot ovat yhdessä paikassa.

**Rekisteritunnuksen tai kuljettajan muuttuminen kesken vuoden:** tiedot tallennetaan auton tietokannan `vehicle_info`-tauluun voimassaolopäivineen (`valid_from`). Raportti käyttää kullekin ajolle sitä tietoa, joka oli voimassa ajon päivänä. Muutos kirjataan muutoslokiin. Lukittuja raportteja ei muuteta. Auton tunnistetta (`id`) ei voi muuttaa sen jälkeen, kun autolle on kirjattu matkoja.

**`config.yaml` (add-onin oletusasetukset ja skeema, ote):**

```yaml
name: BMW-ajopäiväkirja
slug: bmw_logbook
ingress: true
ingress_port: 8099
panel_icon: mdi:car-clock
panel_title: BMW-ajopäiväkirja
homeassistant_api: true
services: ["mqtt:want"]
map: ["share:rw"]                        # vain /share (raportit Rclonea varten)

options:
  vehicles:
    - id: 530e
      plate: ""
      make: BMW
      model: 530e xDrive (G30)
      powertrain: PHEV
      vin: ""
      driver: ""
      enabled: true
      charging_pause_enabled: true
      charging_pause_timeout_s: 2700
      entity_location: device_tracker.530e_xdrive_location
      entity_odometer: sensor.530e_xdrive_vehicle_mileage
      entity_motion: binary_sensor.autot_530e_xdrive_vehicle_motion_state
      entity_soc: sensor.530e_xdrive_battery_ev_state_of_charge
      entity_charging_state: sensor.charging_ev_charging_state
      entity_charging_method: sensor.charging_ev_charging_method
      entity_hv_system_state: sensor.charging_ev_hv_system_state
    - id: ix3
      plate: ""
      make: BMW
      model: iX3 (NA5)
      powertrain: BEV
      vin: ""
      driver: ""
      enabled: false                     # päälle, kun entiteetit ovat HA:ssa
      charging_pause_enabled: true
      charging_pause_timeout_s: 5400
      entity_location: ""
      entity_odometer: ""
      entity_motion: ""
      entity_soc: ""
      entity_charging_state: ""
      entity_charging_method: ""
      entity_hv_system_state: ""
  export_dir: /share/ajopaivakirja
  month_folder_format: "%m"             # kuukausikansion nimi (strftime), esim. "11"
  trip_start_distance_m: 100
  trip_end_timeout_s: 600
  home_zones: ["zone.home"]
  backfill_max_hours: 24
  ha_mqtt_enabled: true
  report_xlsx: true
  report_csv: false
  xlsx_import_poll_s: 60                 # tuonti-kansioiden tarkistusväli
  odometer_gap_tolerance_km: 1
  auto_lock_after_days: 15               # 0 = vain käsin lukitus
  commute_counts_as_private: true        # työmatkat mukaan "vain yksityisajot" -tulosteeseen
  archive_filtered: ["business"]         # lukittaessa arkistoitavat osaraportit
  nominatim_user_agent: bmw-logbook-fi/2.0

schema:
  vehicles:
    - id: match(^[a-z0-9_]{2,16}$)
      plate: str
      make: str
      model: str
      powertrain: list(PHEV|BEV)
      vin: match(^$|^[A-HJ-NPR-Z0-9]{17}$)
      driver: str
      enabled: bool
      charging_pause_enabled: bool
      charging_pause_timeout_s: int(0,86400)
      entity_location: str?
      entity_odometer: str?
      entity_motion: str?
      entity_soc: str?
      entity_charging_state: str?
      entity_charging_method: str?
      entity_hv_system_state: str?
  export_dir: str
  month_folder_format: str
  # ... muut kentät vastaavasti
```

Add-on tarkistaa käynnistyessään, että autotunnisteet ovat yksilöllisiä ja että käytössä olevalla autolla on vähintään `entity_location` ja `entity_odometer`. Virheellinen auto jätetään pois ja virhe näytetään sekä add-onin lokissa että käyttöliittymässä, mutta muut autot toimivat normaalisti. Add-onin asetussivulle käyttöliittymän kenttänimet ja ohjetekstit annetaan suomeksi (`translations/fi.yaml`).

Pysyvät tiedostot `/data`-hakemistossa: `options.json` (HA:n hallinnoima) sekä `<vehicle_id>/logbook.db` ja `<vehicle_id>/active_trip.json`. Kaikki Driveen menevä on kansiossa `/share/ajopaivakirja/` (7.1).

BMW CarDatan `client_id`, `GCID` ja tokenit eivät kuulu konfiguraatioon lainkaan.

---

## 9. Virheenkäsittely ja luotettavuus
* **HA-yhteyden katkeaminen:** palvelu yhdistää uudelleen eksponentiaalisella viiveellä. Yhteyden palattua puuttuva jakso haetaan HA:n historiasta (enintään `backfill_max_hours`) ja syötetään tilakoneelle aikajärjestyksessä ennen live-tapahtumia.
* **CarData-streamin katkos HA:ssa:** palvelu seuraa entiteettiä `sensor.cardata_debug_device_stream_connection_status` (vain luku). Kun tila ei ole `connected`, käyttöliittymä ja `..._status`-sensori näyttävät varoituksen, eikä aikakatkaisua tulkita matkan päättymiseksi ennen kuin data on taas saatavilla.
* **Uudelleenkäynnistyksen sieto:** aktiivisen ajon tila tallennetaan autokohtaisesti (`data/<vehicle_id>/active_trip.json`).
* **Toisen auton vika ei vaikuta toiseen:** autokohtaiset tilakoneet ja tietokannat ajetaan erillisinä tehtävinä. Yhden auton virhe (puuttuva entiteetti, korruptoitunut tiedosto) kirjataan ja näytetään, mutta toisen auton kirjaus jatkuu.
* **Drive-katkokset:** add-on kirjoittaa aina paikalliseen `/share`-kansioon, joka on tiedostojen ensisijainen sijainti. Jos Rclone-job epäonnistuu (esim. verkkokatko tai vanhentunut `google_drive`-remoten token), tiedostot siirtyvät seuraavalla onnistuneella ajolla. Mitään ei menetetä, ja selainlataus toimii koko ajan.
* **Nominatim:** max 1 pyyntö/s ja välimuisti lähekkäisille koordinaateille (jaettu autojen kesken, koska se ei sisällä ajopäiväkirjatietoa).
* **Tietojen eheys:** SQLite ajetaan WAL-tilassa, ja `PRAGMA integrity_check` ajetaan päivittäin ennen varmuuskopiointia. Epäonnistunut tarkistus estää varmuuskopion korvaamisen ja näkyy käyttöliittymässä.
* **Ei omaa BMW-yhteyttä:** palvelu ei koskaan avaa yhteyttä BMW CarDataan, koska BMW sallii vain yhden stream-yhteyden per GCID ja sen pitää HA.

---

## 10. Toimitettavat kokonaisuudet
1. **Python-lähdekoodi** moduuleittain: `ha_client.py` (WebSocket-tilaus ja historiapaikkaus), `vehicle_registry.py` (asetusten luku `options.json`-tiedostosta ja entiteettitarkistus), `trip_manager.py` (tilakone, yksi instanssi per auto), `database.py` (autokohtaiset tietokannat), `web_ui.py`, `pdf_report.py`, `xlsx_report.py` (vienti ja kommenttien tuonti), `csv_report.py`, `integrity.py` (mittarijatkuvuus, pakolliset kentät, jakson lukitus ja arkistointi, muutosloki), `ha_mqtt.py`, `exporter.py` (atominen kirjoitus `/share`-kansioon, kansiorakenne, DB-varmuuskopiot), `import_watcher.py` (tuonti-kansioiden seuranta), `main.py`. Versiosta 1 poistuvat `auth.py` ja `bmw_mqtt.py`.
2. **HTML/HTMX-pohjat** (`templates/`): autovalinta, listanäkymä, yhdistäminen/purku, raporttien lataus ja Asetukset-sivu (entiteettitarkistus, `/share`-kansion ja tuontien tila).
3. **Home Assistant -add-on-paketti:** `config.yaml` (asetusskeema, Ingress, `homeassistant_api`, `services: mqtt:want`, `map: share:rw`), `Dockerfile`, `run.sh`, `translations/fi.yaml`, `icon.png`, `logo.png` sekä `repository.yaml`, jotta add-onin voi asentaa omana add-on-repositorionaan (*Lisäosakauppa → ⋮ → Repositoriot*).
4. **Käyttöohje (`README.md`)**, jossa vähintään:
   * Add-onin asennus repositoriosta ja ensimmäinen käynnistys.
   * Autojen tietojen ja entiteettien syöttö asetussivulla, myös iX3:n entiteettien etsiminen HA:n laitesivulta (*Asetukset → Laitteet ja palvelut → BMW CarData → iX3*), kun auto tulee.
   * **Rclone Backup -jobien lisääminen vaihe vaiheelta** (10.1).
   * Kommentoidun Excelin palautus: selaimella tai Driven `tuonti/`-kansion kautta, sekä varoitus, ettei Drivessa olevia raportteja muokata paikallaan.

### 10.1. README: uusien jobien lisääminen Rclone Backupiin
1. Asenna ja käynnistä BMW-ajopäiväkirja-add-on kerran, jotta kansio `/share/ajopaivakirja/` autokansioineen syntyy. Tarkista se esim. Samba-jaosta tai File editorista.
2. Avaa HA: *Asetukset → Lisäosat → Rclone Backup → Määritykset*.
3. Avaa kolmen pisteen valikosta (⋮) **Muokkaa YAML-muodossa**.
4. Lisää `jobs:`-listan loppuun luvun 7.3 kaksi uutta jobia (*Ajopaivakirja* ja *Ajopaivakirja tuonti*). **Älä muuta Latauslogit-jobia** äläkä kohtia `config_path`, `dry_run` ja `log_level`.
   * Sisennyksen on oltava sama kuin Latauslogit-jobissa (jokainen job alkaa `- name:` samalla tasolla).
   * Remoten nimi on `google_drive:` täsmälleen samassa muodossa kuin nykyisessä jobissa.
5. Paina **Tallenna** ja käynnistä Rclone Backup uudelleen (*Info → Käynnistä uudelleen*). Uudet jobit tulevat voimaan vasta uudelleenkäynnistyksen jälkeen.
6. **Testaa heti ilman aikataulun odottamista:** avaa *Loki*-välilehti ja tarkista, että käynnistyksessä näkyvät kaikki kolme jobia ilman virheitä. Kansio `Ajopaivakirja` ilmestyy Driveen ensimmäisellä ajolla (03:20). Jos haluat testata heti, vaihda *Ajopaivakirja*-jobin `schedule` hetkeksi muutaman minuutin päähän, tallenna, käynnistä uudelleen ja palauta aikataulu testin jälkeen.
7. **Testaa tuonti:** lataa auton Excel selaimella, lisää kommentti, tallenna tiedosto Drivessa kansioon `Ajopaivakirja/<auto>/tuonti/` ja odota enintään 15 minuuttia. Tiedosto katoaa Driven tuonti-kansiosta, ja kommentti näkyy ajopäiväkirjassa. Seuraavan varmuuskopioajon jälkeen käsitelty tiedosto näkyy Drivessa kansiossa `tuonnit/`.
8. **Jos siirto ei toimi:** tarkista Rclone Backupin loki. Yleisin syy on vanhentunut `google_drive`-remoten token, joka näkyy myös Latauslogit-jobissa. Se uusitaan samalla tavalla kuin Latauslokeja varten (Rclone Backupin web-käyttöliittymä). Ajopäiväkirjan tiedostot odottavat sillä välin `/share`-kansiossa eivätkä katoa.
