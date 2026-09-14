"""Real eBay sold-listing titles, captured Sept 14, 2026.

The live search was `Charizard 4/102 PSA 10` (completed + sold, newest first) —
60 sales, $19.99 to $997,512.84 around a $564.50 median, with only 19 of them
within ±25% of it. The spread is not noise: the search returns genuine PSA 10s
of entirely different cards. That is what these fixtures exist to pin down, so
the filters are tested against what eBay actually serves rather than against
titles we imagined.

WANTED is the card we were pricing: Celebrations Classic Collection Charizard
4/102, a 2021 reprint of the 1999 Base Set card — the two share a number, so the
year is the only thing separating a ~$550 comp from a six-figure one.
"""

WANTED = {"number": "4/102", "year": 2021, "grading": "PSA", "grade": "10"}

# Titles that really are our card at our grade
KEEP = [
    "PSA 10 Charizard Celebrations Classic 4/102 Holo Base Set Pokemon Card 2021",
    "Pokemon Charizard Celebrations Classic Coll.-Base Set Holo #4 PSA 10 Gem Mint",
    "Pokemon Charizard 4/102 Celebrations: Classic Collection Holo PSA 10",
    "Charizard 4/102 PSA 10 Celebrations Pokemon TCG",
    "The Pokémon Company Charizard Celebrations Classic 4/102 Holo 2021 PSA 10",
    "Pokemon 2021 Charizard 4/102 Celebrations Classics PSA 10 MBA Silver Diamond",
    "2021 POKEMON CHARIZARD-HOLO CLASSIC COLL-BASE SET #4 PSA 10",
    "2021 Pokemon Celebrations Classic Base #4 Charizard Holo PSA 10 GEM MINT",
    "2021 Pokemon Celebrations Charizard #4 102 Classic Base Set Holo PSA 10 GEM MINT",
    "Pokémon TCG Charizard Holo 4/102 Celebrations Classic Collection | PSA 10",
    "Pokémon TCG PSA 10 Charizard 4/102 Celebrations: Classic Collection Holo ENG",
    "PSA 10 Charizard 4/102 Pokemon Celebrations Classic Collection Holo Graded Card",
    "2021 Pokemon Celebrations Charizard 4/102 Holo PSA 10 Classic Collection",
    "4031 Charizard 2021 Pokemon Sword & Shield Celebrations #4/102 Classic PSA 10",
]

# Titles that must NOT price this holding, with why
DROP = [
    # Another card entirely, same grade
    ("2016 POKEMON XY BREAKPOINT SECRET #123 FULL ART/GYARADOS EX PSA 10", "other card"),
    ("Charizard ex PSA 10 2023 Pokemon SV 151 #199/165 Special Illustration Rare 9933", "other card"),
    ("2016 Pokemon XY Evolutions Charizard EX Ultra Rare PSA 10 012/108", "other card"),
    ("2002 Pokemon Expedition Base Set Chansey Non Holo 72/165 PSA 10 Gem Mint POP 54", "other card"),
    ("2025 POKEMON MEGA CHARIZARD X EX SIR PHANTASMAL FLAMES #125/094 - PSA 10", "other card"),
    ("2021 POKEMON JP SWSH VMAX CLIMAX #017/184 CHARIZARD HOLO PSA 10", "other card"),
    ("2022 POKEMON JP SWSH VSTAR UNIVERSE #212 CHARIZARD VSTAR SPECIAL ART RARE PSA 10", "other card"),
    ("2024 POKEMON PALDEAN FATES #234 CHARIZARD EX SPECIAL ILLUSTRATION RARE PSA 10", "other card"),
    ("POKEMON •🔥 Charmander Base Set 46/102 • 🔥 PSA 10", "other card (46/102 is not 4/102)"),
    ("CHARIZARD POKEMON #SWSH066 PRERELEASE HOLO ((PSA 10 GEM MINT))", "other card"),
    ("2022 Pokemon Sword & Shield Brilliant Stars 154 Charizard V PSA 10 (plus gaurd!)", "other card"),
    # Same collector number, different print year — the expensive confusion
    ("1999 Pokemon 1st Edition Shadowless Charizard Base Set Holo Rare #4 PSA 10", "1999 original, not the 2021 reprint"),
    ("1999 Pokemon Charizard Base Set Unlimited Holo Rare #4 PSA 10 Gem Mint", "1999 original"),
    ("2000 POKEMON TEAM ROCKET FIRST EDITION #4/82 DARK CHARIZARD HOLO RARE PSA 10", "#4 of a different set"),
    # Not a single card
    ("POKEMON BASE SET BOOSTER PACK CHARIZARD ART SHADOWLESS 1999 PSA 10 GEM MINT", "graded booster pack"),
    ("1999 Pokemon GERMAN 1st Edition Base Set Glurak-Charizard Booster Pack PSA 10", "graded booster pack"),
    ("⚡️SLABROS⚡️ 💎PREMIUM💎 🔥HAND-MADE🔥😈Pokémon😈 PSA 10 Replica Holo-Keychains", "replica keychain"),
    ("Pokemon Japanese Base Charmander Charmeleon Charizard PSA 10 GEM MINT TRIO SET", "three cards"),
    ("Charizard. EeVee. Venusaur. Mega diancie PSA 10. First Ed Charmander Base Set", "several cards"),
]
