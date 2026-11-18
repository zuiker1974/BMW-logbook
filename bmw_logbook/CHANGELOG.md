# Muutosloki

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
