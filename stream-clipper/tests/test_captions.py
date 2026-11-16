from clipper.captions import build_ass, clean, group_words
from clipper.director import Beat, Plan, chat_mood, rule_plan
from clipper.transcribe import Word


def words(text, start=0.0, step=0.3):
    return [Word(start + i * step, start + i * step + 0.25, w) for i, w in enumerate(text.split())]


def test_chat_mood():
    assert chat_mood(["KEKW", "LMAOOO", "OMEGALUL OMEGALUL", "W"])[0] == "funny"
    assert chat_mood(["WWWW", "LETS GO", "POGGERS", "W"])[0] == "hype"
    assert chat_mood(["WTF", "???", "NO WAY", "huh"])[0] == "shock"


def test_rule_plan_uses_chat_and_name():
    meta = {"name": "Kai", "platform": "twitch", "explosion_offset": 30,
            "chat_timeline": [[30.1, "a", "KEKW"], [30.2, "b", "KEKW"], [30.3, "c", "LMAO"]]}
    p = rule_plan(meta, [])
    assert p.mood == "funny" and "Kai" in p.hook
    assert p.beats and p.beats[0].text == "CHAT: KEKW" and p.beats[0].t > 30


def test_grouping_breaks_on_pause_and_punctuation():
    ws = words("one two three four") + words("five", start=5) + [Word(6, 6.2, "end."), Word(6.3, 6.5, "next")]
    groups = [[w.text for w in g] for g in group_words(ws)]
    assert groups == [["one", "two", "three"], ["four"], ["five"], ["end."], ["next"]]


def test_ass_has_all_layers_and_strips_emoji():
    plan = Plan(hook="He did WHAT 😱 {x}", mood="shock", beats=[Beat(3, "NO WAY 🚓")], emphasis=["bridge"])
    ass = build_ass(plan, words("jump the bridge now"), 10.0)
    assert "HE DID WHAT X" in ass and "😱" not in ass and "🚓" not in ass
    assert ass.count(",Speech,") == 4           # one event per spoken word
    assert ",Beat,," in ass and "NO WAY" in ass
    assert "&H00303BFF" in ass                  # shock red as ASS &HAABBGGRR


def test_clean():
    assert clean("a{b}\\c 🔥\n d") == "abc d"
