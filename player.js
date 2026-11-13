// Allt ljud och alla länkar kommer från Spotify.
(function (root) {
  // Spotifys 30-sekunders smakprov för låten.
  function previewUrl(song) { return song.pv ? "https://p.scdn.co/mp3-preview/" + song.pv + ".mp3" : null; }

  // Länk som öppnar hela låten i Spotify.
  function spotifyLink(song) {
    if (!song.sp) return "https://open.spotify.com/search/" + encodeURIComponent(song.artist + " " + song.title);
    return song.sp.startsWith("album:") ? "https://open.spotify.com/album/" + song.sp.slice(6) : "https://open.spotify.com/track/" + song.sp;
  }

  const api = { previewUrl, spotifyLink };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.MQPlayer = api;
})(typeof window !== "undefined" ? window : globalThis);
