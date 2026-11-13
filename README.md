# Musikquiz

Ett musikspel med utskrivbara kort. Skanna kortets QR-kod, lyssna på låten utan att se vad den heter, och lägg kortet på rätt plats i din tidslinje. Först till tio kort vinner.

Spelet finns på <https://sludde05-coder.github.io/musikquiz/>.

## Innehåll

| Fil | Vad den gör |
| --- | --- |
| `index.html` | Startsidan |
| `spela.html` | Spelar låten som hör till ett kort (`spela.html?k=17`), eller slumpar en låt |
| `kort.html` | Utskrivbara kort: QR-kod på framsidan, år, artist och titel på baksidan |
| `regler.html` | Regler och brickor att skriva ut |
| `songs.js` | Låtlistan |
| `player.js` | Bygger Spotify-länkarna för smakprov och hel låt |
| `config.js` | Adressen som QR-koderna pekar på |

## Skriva ut

1. Öppna `kort.html` och tryck på **Skriv ut korten**. Välj A4, skala 100 % och dubbelsidigt, vänd längs långa kanten.
2. Öppna `regler.html` och skriv ut regler och brickor enkelsidigt.
3. Klipp ut korten och brickorna.

## Ändra låtarna

Låtarna ligger i `songs.js`. Varje låt har ett fast nummer (`id`) som står i QR-koden, så lägg nya låtar sist med nya nummer och ändra inte numret på en låt som redan är utskriven.

Alla låtar spelas via Spotify. `sp` är Spotify-låtens ID (det som står efter `/track/` i en låtlänk) och `pv` är Spotifys 30-sekunders smakprov, som spelas utan att titeln syns. Varje kort har också en knapp som öppnar hela låten i Spotify.

## Flytta spelet

QR-koderna pekar på adressen i `config.js`. Byter du användarnamn eller reponamn måste du ändra adressen där och skriva ut korten igen.

QR-koderna skapas med [qrcode-generator](https://github.com/kazuhikoarase/qrcode-generator) (MIT-licens).
