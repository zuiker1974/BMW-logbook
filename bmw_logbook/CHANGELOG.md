# Muutosloki

## 0.2.0
- Kululaskenta (vain määrät): lataukset kWh ja 530e:n tankkaukset litroina, autokohtaisesti.
  - Kotilataus luetaan kotilaturin istuntomittarista (`entity_charger_energy`, esim. `sensor.abb_energy_delivered`), muualla ladattu arvioidaan varaustason noususta (`charge_kwh_per_pct`).
  - Tankkaus tunnistetaan tankin litramäärän noususta (`entity_fuel_level`, `refuel_min_l`), ja kuukauden kulutus lasketaan tankin lukemista.
- Uusi Kulut-näkymä: rivit, kuukauden määrät, vapaaehtoinen yksikköhinta (€/kWh, €/l), kommentti, perusteltu korjaus ja käsin lisäys.
- Kuukausi-PDF:ään Kulut-osio, vuosi-PDF:ään kuukausittainen yhteenveto ja Exceliin Kulut-välilehti, jonka yksikköhinnat ja kommentit tuodaan takaisin.
- Uudet HA-sensorit: `_month_charged_kwh`, `_month_refuelled_l`, `_month_fuel_used_l`.
- Sama entiteetti (esim. kotilaturi) voi kuulua usealle autolle.

## 0.1.1
- Ajo päättyy oikeaan aikaan, vaikka 530e lähettää pysäköinnin jälkeen noin 7 minuutin "haamuliikkeen" (liiketila on, auto ei liiku). Aiemmin haamu siirsi loppuaikaa ja pidensi tilaa "Ajossa".
- Loppuaikana käytetään mittarilukeman omaa aikaleimaa, kun liiketilan pysähdystieto tulee BMW:ltä myöhässä (havaittu noin 5 min).
- Pitkä pysähdys (yli 10 min) jakaa ajot myös silloin, kun haamuliike osui pysähdyksen alkuun, ja myös add-onin uudelleenkäynnistyksen jälkeisessä historiapaikkauksessa.
- Ajon alkuaika on ensimmäinen siirtymä pysäköintipaikalta.
- Lataus ajon lähtöpaikalla ei ole lataustauko, vaikka kotivyöhykettä ei olisi määritelty.
- Uusi tila "Pysähtynyt": auto seisoo, ajo päättyy kun 10 min on kulunut.

## 0.1.0
- Ensimmäinen versio: automaattinen ajopäiväkirja BMW 530e:lle ja iX3:lle Home Assistantin CarData-datasta.
- Autokohtaiset tietokannat, raportit (PDF, Excel, CSV), Drive-kansiot ja HA-sensorit.
- Mittarijatkuvuuden tarkistus, muutosloki, jakson lukitus SHA-256-arkistolla ja Excel-kommenttien tuonti.
