# BMW-ajopäiväkirja (Home Assistant -lisäosa)

Automaattinen ajopäiväkirja BMW 530e:lle (G30) ja iX3:lle (NA5). Lisäosa lukee autojen tiedot
**Home Assistantista** (BMW CarData -integraation entiteetit), tunnistaa ajot itse ja tekee niistä
Verohallinnon vaatimukset täyttävät PDF- ja Excel-raportit.

- **Ei omaa BMW-yhteyttä.** BMW sallii vain yhden CarData-streamin per tili, ja sen pitää jo HA:n
  CarData-integraatio. Lisäosa vain lukee HA:n tiloja (WebSocket), eikä se muuta mitään HA:ssa.
  Olemassa olevat automaatiot (ABB-latauksen oppiminen, kytkemättä jääneen 530e:n muistutus,
  dynaaminen latausvirta) toimivat ennallaan.
- **Autot pidetään aina erillään:** oma tietokanta, omat raportit, omat Drive-kansiot ja omat
  HA-sensorit per auto. Yhdistää voi vain saman auton matkoja.
- **Verottajaa varten:** mittarilukemien jatkuvuuden tarkistus, muutosloki jota ei voi muokata,
  kuukausien lukitus ja lukitun raportin SHA-256-tiiviste.
- **Raportit:** PDF (kuukausi ja vuosi), Excel-vuosityökirja kommenttisarakkeella ja CSV.
  Tulosteet voi rajata: kaikki ajot, vain työajot, vain yksityisajot tai vain työmatkat.
- **Drive:** lisäosa kirjoittaa kansioon `/share/ajopaivakirja/`, ja olemassa oleva
  **Rclone Backup** -lisäosa vie sen Driveen. Omaa Google-kirjautumista ei tarvita.

Tekninen määrittely: [docs/bmw_ajopaivakirja_spec_v2.md](docs/bmw_ajopaivakirja_spec_v2.md).

---

## 1. Asennus

1. Avaa HA: **Asetukset → Lisäosat → Lisäosakauppa**.
2. Kolmen pisteen valikko (⋮) → **Repositoriot** → lisää osoite
   `https://github.com/zuiker1974/bmw-logbook` → **Lisää**.
3. Päivitä sivu. Lisäosakaupan alalaitaan ilmestyy **BMW-ajopäiväkirja**. Avaa se ja paina **Asenna**.
4. Täytä asetukset (kohta 2) ennen ensimmäistä käynnistystä.
5. **Käynnistä**. Ota halutessasi käyttöön **Näytä sivupalkissa**, jolloin ajopäiväkirja näkyy
   HA:n sivupalkissa nimellä *BMW-ajopäiväkirja*.
6. Tarkista **Loki**-välilehdeltä, että lisäosa yhdisti Home Assistantiin, ja avaa ajopäiväkirjan
   **Asetukset**-sivu: jokaisen kartoitetun entiteetin vieressä pitää olla ✓.

Lisäosa käyttää Supervisorin omaa tunnusta, joten pitkäikäistä tunnusta ei tarvita. Jos Mosquitto
MQTT -välittäjä on asennettu, lisäosa luo autokohtaiset sensorit automaattisesti.

## 2. Autojen tiedot ja entiteetit

Kaikki asetukset syötetään lisäosan asetussivulla: **Asetukset → Lisäosat → BMW-ajopäiväkirja →
Määritykset**. Muutokset tulevat voimaan, kun lisäosa käynnistetään uudelleen.

Jokaisella autolla on oma kohta `vehicles`-listassa:

| Kenttä | Merkitys |
|---|---|
| `id` | Auton pysyvä tunniste (`530e`, `ix3`). Ei saa muuttaa sen jälkeen, kun autolle on kirjattu matkoja. |
| `plate` | Rekisteritunnus, esim. `ABC-123`. Näkyy raporteissa ja tiedostonimissä. |
| `make`, `model`, `powertrain` | Merkki, malli ja voimalinja (`PHEV` tai `BEV`). |
| `vin` | Valmistenumero (17 merkkiä) tai tyhjä. Excel-tuonti tarkistaa sen. |
| `driver` | Kuljettaja. |
| `enabled` | Kirjataanko auton ajoja. |
| `charging_pause_enabled`, `charging_pause_timeout_s` | Lataustauko kesken matkan: kuinka kauan lataus saa kestää ennen kuin matka katsotaan päättyneeksi (530e 45 min, iX3 90 min). Kotilataus ei koskaan ole lataustauko. |
| `entity_location`, `entity_odometer` | **Pakolliset**: sijainti (device_tracker) ja matkamittari. |
| `entity_motion` | Suositeltu: liiketila (binary_sensor). |
| `entity_soc`, `entity_charging_state`, `entity_charging_method`, `entity_hv_system_state` | Valinnaiset: akun varaus ja lataustiedot. |

530e:n entiteetit on valmiiksi täytetty (tarkistettu HA:sta 17.11.2026):

```yaml
entity_location: device_tracker.530e_xdrive_location
entity_odometer: sensor.530e_xdrive_vehicle_mileage
entity_motion: binary_sensor.autot_530e_xdrive_vehicle_motion_state
entity_soc: sensor.530e_xdrive_battery_ev_state_of_charge
entity_charging_state: sensor.charging_ev_charging_state
entity_charging_method: sensor.charging_ev_charging_method
entity_hv_system_state: sensor.charging_ev_hv_system_state
```

Älä nimeä 530e:n entiteettejä uudelleen: latausautomaatiot riippuvat niistä.

### iX3:n lisääminen, kun auto tulee

iX3 on asetuksissa valmiina, mutta pois päältä (`enabled: false`).

1. Kun iX3 näkyy BMW CarData -tilillä, avaa HA: **Asetukset → Laitteet ja palvelut → BMW CarData → iX3**.
2. Kopioi laitesivulta iX3:n entiteettien tunnisteet (sijainti, matkamittari, liiketila, akun varaus,
   lataustila ja latausmenetelmä). **Älä arvaa nimiä:** latausentiteeteissä ei ole auton nimeä, joten
   iX3:n vastaavat saavat todennäköisesti päätteen `_2` (esim. `sensor.charging_ev_charging_state_2`).
   Varmista jokainen laitesivulta.
3. Täytä ne iX3:n kohtaan, lisää rekisteritunnus ja VIN, ja vaihda `enabled: true`.
4. Käynnistä lisäosa uudelleen ja tarkista ajopäiväkirjan Asetukset-sivulta, että kaikissa on ✓.

Jos pakollinen entiteetti puuttuu, auto näkyy tilassa *Ei konfiguroitu*, eikä se vaikuta toisen auton
kirjaukseen.

### Muut asetukset

| Asetus | Oletus | Merkitys |
|---|---|---|
| `trip_end_timeout_s` | 600 | Matka päättyy, kun auto on ollut paikallaan näin kauan. |
| `trip_start_distance_m` | 100 | Sijainnin siirtymä, jonka jälkeen auto katsotaan liikkuneeksi. |
| `ghost_motion_max_s` | 90 | Lyhyet "liikkeessä"-jaksot ilman todellista siirtymää ohitetaan (530e lähettää pysäköinnin jälkeen usein noin 30 s haamuliikkeen). |
| `home_zones` | `zone.home` | Vyöhykkeet, joilla lataus ei ole lataustauko. |
| `stream_status_entity` | `sensor.cardata_debug_device_stream_connection_status` | Kun CarData-yhteys on poikki, matkaa ei päätetä aikakatkaisulla. |
| `backfill_max_hours` | 24 | Yhteyskatkon jälkeen puuttuva jakso haetaan HA:n historiasta enintään näin pitkältä ajalta. |
| `odometer_gap_tolerance_km` | 1 | Mittarilukemien sallittu ero peräkkäisten matkojen välillä. |
| `auto_lock_after_days` | 15 | Kuukausi lukitaan automaattisesti, kun sen päättymisestä on kulunut näin monta päivää ja tarkistukset ovat kunnossa (0 = vain käsin). |
| `commute_counts_as_private` | true | "Vain yksityisajot" -tuloste sisältää työmatkat. |
| `archive_filtered` | `[business]` | Lukittaessa arkistoidaan myös työajojen osaraportti. |
| `month_folder_format` | `%m` | Kuukausikansion nimi (`11`). |
| `report_xlsx`, `report_csv` | true, false | Kirjoitetaanko Excel ja CSV raporttikansioon. |

## 3. Käyttö

Ajopäiväkirja aukeaa HA:n sivupalkista. Etusivulla on autot korttina, ja jokaisella autolla on oma
näkymänsä (`/v/530e`, `/v/ix3`). Kaikkien autojen yhteistä näkymää ei ole.

- **Matkat:** suodata vuoden, kuukauden ja ajotyypin mukaan. Ajotyyppi, tarkoitus ja kommentti
  tallentuvat heti. Työajolle tarkoitus on pakollinen ennen jakson lukitusta.
- **Yhdistäminen:** valitse peräkkäiset matkapätkät ja paina *Yhdistä valitut matkat*. *Pura* palauttaa ne.
- **Mittariaukot:** jos seuraava matka alkaa suuremmalla lukemalla kuin edellinen päättyi, listassa
  näkyy varoitusrivi. Siitä voi lisätä puuttuvan ajon tai kuitata aukon perustellusti.
- **Korjaukset:** matkan *tiedot*-sivulla voi korjata paikan, ajan tai mittarilukeman. Korjaus vaatii
  perustelun, alkuperäinen arvo säilyy ja muutos näkyy muutoshistoriassa ja raportissa.
- **Raportit ja lukitus:** lataa PDF tai Excel selaimella, tuo kommentoitu Excel ja lukitse kuukausi.

### Lukitus

Lukittaessa tarkistetaan mittarijatkuvuus ja työajojen tarkoitukset, tuodaan odottavat Excelit ja
tallennetaan kuukauden PDF muuttumattomana kansioon `arkisto/`. Tiedoston SHA-256 tallennetaan
tietokantaan ja viereiseen `.sha256`-tiedostoon, ja PDF:n alatunnisteessa on raportin sisällön
SHA-256. Lukitun kuukauden matkoja ei voi muuttaa, mutta jälkikommentin voi lisätä (se merkitään
"lisätty lukituksen jälkeen"). Lukituksen avaaminen vaatii perustelun, ja uusi lukitus tuottaa uuden
arkistoversion (`_v2`) vanhaa poistamatta.

## 4. Kommentoidun Excelin palautus

Excel-työkirjassa on kuukausivälilehdet (01–12), joissa **Kommentti**, **Ajotyyppi** ja **Tarkoitus**
ovat muokattavissa (keltainen otsikko). Muut sarakkeet tulevat autosta ja ovat lukittuja. Piilotettu
Matka-ID-sarake yhdistää rivit takaisin ajopäiväkirjaan.

Kaksi tapaa palauttaa:

1. **Selaimella (suositus):** *Raportit ja lukitus → Tuo Excel*. Tulos näkyy heti.
2. **Driven kautta:** tallenna muokattu tiedosto Drivessa auton kansioon
   `Ajopaivakirja/<auto>_<rekisteritunnus>/tuonti/`. Rclone Backup hakee sen 15 minuutin välein,
   ajopäiväkirja tuo sen ja siirtää käsitellyn tiedoston kansioon `tuonnit/`.

> **Älä muokkaa Drivessa olevia raporttitiedostoja paikallaan.** Varmuuskopiojob kopioi
> paikallisen version Driveen aina, kun se muuttuu, ja ylikirjoittaa Drivessa tehdyt muutokset.

Tuonnissa:
- toisen auton Excel hylätään (auton tunniste ja VIN tarkistetaan);
- vain Excelissä muuttuneet kentät tuodaan; jos sama kenttä on muuttunut myös selaimessa, kommentit
  yhdistetään ja ajotyypin tai tarkoituksen ristiriita jää ratkaistavaksi Raportit-sivulle;
- lukittuja mittaussarakkeita ei koskaan tuoda, vaikka taulukon suojaus olisi poistettu;
- lukitulle kuukaudelle tuodaan vain kommentit (jälkikommentteina).

## 5. Rclone Backup: uusien jobien lisääminen

1. Asenna ja käynnistä BMW-ajopäiväkirja kerran, jotta kansio `/share/ajopaivakirja/` autokansioineen
   syntyy. Tarkista se esim. Samba-jaosta tai File editorista.
2. Avaa HA: **Asetukset → Lisäosat → Rclone Backup → Määritykset**.
3. Avaa kolmen pisteen valikosta (⋮) **Muokkaa YAML-muodossa**.
4. Lisää `jobs:`-listan loppuun kaksi uutta jobia. **Älä muuta Latauslogit-jobia** äläkä kohtia
   `config_path`, `dry_run` ja `log_level`. Sisennyksen on oltava sama kuin Latauslogit-jobissa
   (jokainen job alkaa `- name:` samalla tasolla), ja remoten nimi on `google_drive:` täsmälleen samassa
   muodossa kuin nykyisessä jobissa.

   ```yaml
     - name: Ajopaivakirja                    # raportit ja varmuuskopiot Driveen
       schedule: 20 3 * * *                   # päivittäin 03:20, tietokannan varmuuskopion jälkeen
       command: copy                          # copy, ei sync: Drivesta ei koskaan poisteta mitään
       source: /share/ajopaivakirja
       destination: google_drive:Ajopaivakirja
       exclude:
         - "*/tuonti/**"
         - "*.tmp"

     - name: Ajopaivakirja tuonti             # Driven tuonti-kansiot takaisin HA:han
       schedule: "*/15 * * * *"               # 15 minuutin välein
       command: move                          # siirtää tiedoston pois Drivesta, kun se on haettu
       source: google_drive:Ajopaivakirja
       destination: /share/ajopaivakirja
       include:
         - "*/tuonti/*.xlsx"
   ```

5. Paina **Tallenna** ja käynnistä Rclone Backup uudelleen (*Info → Käynnistä uudelleen*). Uudet jobit
   tulevat voimaan vasta uudelleenkäynnistyksen jälkeen.
6. **Testaa heti:** avaa *Loki*-välilehti ja tarkista, että käynnistyksessä näkyvät kaikki kolme jobia
   ilman virheitä. Kansio `Ajopaivakirja` ilmestyy Driveen ensimmäisellä ajolla (03:20). Jos haluat
   testata heti, vaihda *Ajopaivakirja*-jobin `schedule` hetkeksi muutaman minuutin päähän, tallenna,
   käynnistä uudelleen ja palauta aikataulu testin jälkeen.
7. **Testaa tuonti:** lataa auton Excel selaimella, lisää kommentti, tallenna tiedosto Drivessa kansioon
   `Ajopaivakirja/<auto>/tuonti/` ja odota enintään 15 minuuttia. Tiedosto katoaa Driven
   tuonti-kansiosta, ja kommentti näkyy ajopäiväkirjassa. Seuraavan varmuuskopioajon jälkeen käsitelty
   tiedosto näkyy Drivessa kansiossa `tuonnit/`.
8. **Jos siirto ei toimi:** tarkista Rclone Backupin loki. Yleisin syy on vanhentunut
   `google_drive`-remoten token, joka näkyy myös Latauslogit-jobissa. Se uusitaan samalla tavalla kuin
   Latauslokeja varten. Ajopäiväkirjan tiedostot odottavat sillä välin `/share`-kansiossa eivätkä katoa.

Raportit voi aina ladata myös suoraan selaimella, joten Driveen ei tarvitse odottaa.

### Kansiorakenne

```
/share/ajopaivakirja/                     →  google_drive:Ajopaivakirja/
├── 530e_ABC-123/
│   ├── 2026/
│   │   ├── Ajopaivakirja_530e_ABC-123_2026.xlsx
│   │   ├── Ajopaivakirja_530e_ABC-123_2026_vuosiraportti.pdf
│   │   └── 11/
│   │       ├── Ajopaivakirja_530e_ABC-123_2026_11.pdf
│   │       ├── Ajopaivakirja_530e_ABC-123_2026_11_tyoajot.pdf
│   │       └── Ajopaivakirja_530e_ABC-123_2026_11_yksityisajot.pdf
│   ├── arkisto/2026/                      (lukitut kuukaudet, ei koskaan ylikirjoiteta)
│   ├── varmuuskopiot/                     (tietokanta kerran päivässä ja jokaisen matkan jälkeen)
│   ├── tuonti/                            (Drivesta tuotavat Excelit)
│   └── tuonnit/                           (käsitellyt ja hylätyt tuonnit)
└── ix3_XYZ-789/
    └── (sama rakenne)
```

Raportit päivittyvät noin 5 minuutin kuluttua matkan päättymisestä tai muutoksesta.

## 6. Home Assistant -sensorit

Jos MQTT on käytössä, jokaiselle autolle luodaan oma laite (*BMW-ajopäiväkirja 530e*, *BMW-ajopäiväkirja ix3*)
ja sensorit `sensor.bmw_logbook_<auto>_status`, `_last_trip_distance`, `_last_trip_route`,
`_month_business_km`, `_month_private_km`, `_last_export` ja `_last_import`. Nämä ovat uusia entiteettejä
eivätkä muuta olemassa olevia.

## 7. Miten ajot tunnistetaan

- Ajo alkaa, kun auto oikeasti liikkuu: sijainti siirtyy yli 100 m tai mittarilukema kasvaa. Alkuajaksi
  otetaan liiketilan "on"-hetki, ja alkupaikaksi ja -lukemaksi viimeisin pysäköintipaikka ja -lukema.
- Ajo päättyy, kun auto on ollut paikallaan 10 minuuttia. Loppuajaksi otetaan pysähtymishetki.
- CarData kirjoittaa saman sijainnin HA:hon noin viisi kertaa: toistot ohitetaan.
- Pysäköinnin jälkeinen noin 30 sekunnin "haamuliike", jonka aikana auto ei liiku, ohitetaan, eikä se
  siirrä matkan loppuaikaa.
- Lataus kesken matkan muualla kuin kotona pitää matkan koossa lataustauon ajan, ja tauko kirjataan
  raporttiin (esim. "Lataustauko 35 min, Ionity Jyväskylä").
- Osoitteet haetaan OpenStreetMapin Nominatim-palvelusta (enintään 1 haku sekunnissa, välimuistilla).

