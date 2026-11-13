// Hittar ett 30-sekunders smakprov för en låt utan att visa vilken låt det är.
// 1) Spotifys smakprov om låten har ett (fältet pv i songs.js)
// 2) annars söker sidan upp låten i Apples och Deezers öppna musikkataloger.
(function (root) {
  const BAD = ["karaoke", "tribute", "cover", "made famous", "instrumental", "remix", "sped up", "slowed", "live", "acoustic", "demo", "8 bit", "lullaby", "originally performed"];

  function norm(s) {
    return String(s || "").toLowerCase().replace(/\$/g, "s").normalize("NFD").replace(/[̀-ͯ]/g, "")
      .replace(/\(.*?\)|\[.*?\]/g, " ").replace(/&/g, " and ").replace(/[^a-z0-9]+/g, " ").replace(/^the /, "").trim();
  }
  // "Mark Ronson ft. Bruno Mars" -> "Mark Ronson"
  function mainArtist(a) { return String(a).split(/\s+(?:ft\.?|feat\.?|och|x)\s+|\s*[&,]\s*/i)[0]; }
  function baseTitle(t) { return norm(String(t).replace(/\s+-\s+.*$/, "")); }

  // candidates: [{artist, title, album, url}] -> bästa träffen eller null
  function pickBest(song, candidates) {
    const wantA = norm(mainArtist(song.artist)), wantT = baseTitle(song.title), rawT = String(song.title).toLowerCase();
    let best = null, bestScore = 0;
    for (const c of candidates || []) {
      if (!c || !c.url) continue;
      const a = norm(c.artist), t = baseTitle(c.title);
      if (!a || !t || !(a.includes(wantA) || wantA.includes(a))) continue;
      // Samma titel, eller samma titel följd av t.ex. "feat. X" eller "remastered 2011".
      const extra = t.startsWith(wantT + " ") ? t.slice(wantT.length + 1) : null;
      let score = t === wantT ? 4 : (extra && /^(feat|ft|featuring|with|remaster|remastered|single|album|radio|original|mono|stereo|\d{4})\b/.test(extra)) ? 3 : 0;
      if (!score) continue;
      const hay = (c.title + " " + (c.album || "")).toLowerCase();
      for (const w of BAD) if (hay.includes(w) && !rawT.includes(w)) score -= 1.5;
      if (score > bestScore) { best = c; bestScore = score; }
    }
    return best;
  }

  const fromItunes = d => ((d && d.results) || []).map(r => ({ artist: r.artistName, title: r.trackName, album: r.collectionName, url: r.previewUrl }));
  const fromDeezer = d => ((d && d.data) || []).map(r => ({ artist: r.artist && r.artist.name, title: r.title, album: r.album && r.album.title, url: r.preview }));

  function jsonp(url, ms) {
    return new Promise((resolve, reject) => {
      const cb = "mqcb" + Math.random().toString(36).slice(2), s = document.createElement("script");
      const done = () => { clearTimeout(timer); try { delete root[cb]; } catch (e) { root[cb] = undefined; } s.remove(); };
      const timer = setTimeout(() => { done(); reject(new Error("timeout")); }, ms || 7000);
      root[cb] = data => { done(); resolve(data); };
      s.onerror = () => { done(); reject(new Error("network")); };
      s.src = url + (url.includes("?") ? "&" : "?") + "callback=" + cb;
      document.head.appendChild(s);
    });
  }

  // Ger en lista med funktioner som var och en försöker hitta en ljudadress, i prioritetsordning.
  function previewSources(song) {
    const term = encodeURIComponent(mainArtist(song.artist) + " " + String(song.title).replace(/\(.*?\)/g, " ").trim());
    const itunes = cc => async () => {
      const d = await jsonp("https://itunes.apple.com/search?media=music&entity=song&limit=25&country=" + cc + "&term=" + term);
      const hit = pickBest(song, fromItunes(d)); return hit && hit.url;
    };
    const deezer = async () => {
      const d = await jsonp("https://api.deezer.com/search?limit=25&output=jsonp&q=" + term);
      const hit = pickBest(song, fromDeezer(d)); return hit && hit.url;
    };
    const list = [];
    if (song.pv) list.push(async () => "https://p.scdn.co/mp3-preview/" + song.pv);
    list.push(itunes("SE"), deezer, itunes("US"));
    return list;
  }

  function spotifyLink(song) {
    return song.sp ? "https://open.spotify.com/track/" + song.sp
      : "https://open.spotify.com/search/" + encodeURIComponent(mainArtist(song.artist) + " " + song.title);
  }

  const api = { norm, mainArtist, pickBest, fromItunes, fromDeezer, previewSources, spotifyLink };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.MQPlayer = api;
})(typeof window !== "undefined" ? window : globalThis);
