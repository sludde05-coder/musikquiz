# Musikquiz

Ett musikspel i stil med Hitster med utskrivbara kort. Framsidan har en QR-kod som öppnar låten i Spotify, och baksidan visar år, artist och titel.

## Skriva ut korten

1. Öppna `index.html` i en webbläsare. Om GitHub Pages är på kan du i stället gå till `https://<användarnamn>.github.io/musikquiz/`.
2. Tryck på **Skriv ut** och välj dubbelsidig utskrift, vänd längs långa kanten och skala 100 %.
3. Klipp ut korten längs de streckade linjerna.

## Ändra låtarna

Låtarna finns i `songs.js`. Varje låt har `title`, `artist`, `year` och kan ha ett `spotifyId`, som är ID:t i en låtlänk som `https://open.spotify.com/track/<ID>`. Med `spotifyId` öppnar QR-koden just den låten. Utan det öppnar QR-koden en Spotify-sökning.

## Regler i korthet

- Varje spelare börjar med ett kort med året uppåt.
- När det är din tur skannar du en QR-kod och spelar låten. Lägg telefonen med skärmen nedåt.
- Placera kortet på din tidslinje där du tror att låten hör hemma, och vänd det.
- Hamnade kortet rätt i tidsordningen får du behålla det. Den som först har 10 kort vinner.

QR-koderna skapas med [qrcode-generator](https://github.com/kazuhikoarase/qrcode-generator) (MIT-licens).
