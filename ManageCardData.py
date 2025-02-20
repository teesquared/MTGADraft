import mmap
import json
import requests
import ijson
import os
import gzip
import urllib
import sys
import re
import glob
import decimal
from itertools import groupby
import functools
from pprint import pprint
import math as m1
from ordered_enum import OrderedEnum


class Rarity(OrderedEnum):
    mythic: int = 4
    rare: int = 3
    uncommon: int = 2
    common: int = 1


ScryfallSets = 'data/scryfall-sets.json'
BulkDataPath = 'data/scryfall-all-cards.json'
BulkDataArenaPath = 'data/BulkArena.json'
FinalDataPath = 'data/MTGCards.json'
SetsInfosPath = 'client/public/data/SetsInfos.json'
BasicLandIDsPath = 'src/data/BasicLandIDs.json'
RatingSourceFolder = 'data/LimitedRatings/'
JumpstartBoostersFolder = 'data/JumpstartBoosters'
JumpstartSwaps = "data/JumpstartSwaps.json"
JumpstartBoostersDist = 'src/data/JumpstartBoosters.json'
JumpstartHHBoostersDist = 'src/data/JumpstartHHBoosters.json'
RatingsDest = 'data/ratings.json'
ManaSymbolsFile = "src/data/mana_symbols.json"

ArenaRarity = {
    1: "basic",  # I guess?
    2: "common",
    3: "uncommon",
    4: "rare",
    5: "mythic"
}

ForceDownload = ForceExtract = ForceCache = ForceRatings = ForceJumpstart = ForceJumpstartHH = ForceSymbology = FetchSet = False
SetToFetch = ""
if len(sys.argv) > 1:
    Arg = sys.argv[1].lower()
    ForceDownload = Arg == "dl"
    ForceCache = ForceDownload or Arg == "cache"
    ForceRatings = Arg == "ratings"
    ForceJumpstart = Arg == "jmp"
    ForceJumpstartHH = Arg == "jhh"
    ForceSymbology = Arg == "symb"
    FetchSet = Arg == "set" and len(sys.argv) > 2
    if(FetchSet):
        SetToFetch = sys.argv[2].lower()
        ForceCache = True

MTGADataFolder = "H:\MtGA\MTGA_Data\Downloads\Data"
MTGALocFiles = glob.glob('{}\data_loc_*.mtga'.format(MTGADataFolder))
MTGACardsFiles = glob.glob('{}\data_cards_*.mtga'.format(MTGADataFolder))
MTGALocalization = {}
for path in MTGALocFiles:
    with open(path, 'r', encoding="utf8") as file:
        locdata = json.load(file)
        for lang in locdata:
            langcode = lang['isoCode'][:2]
            if langcode not in MTGALocalization:
                MTGALocalization[langcode] = {}
            for o in lang['keys']:
                MTGALocalization[langcode][o['id']] = o['text']

# Get mana symbols info from Scryfall
SymbologyFile = "./data/symbology.json"
if not os.path.isfile(ManaSymbolsFile) or ForceSymbology:
    if not os.path.isfile(SymbologyFile):
        urllib.request.urlretrieve(
            "https://api.scryfall.com/symbology", SymbologyFile)
    mana_symbols = {}
    with open(SymbologyFile, 'r', encoding="utf8") as file:
        symbols = json.load(file)
        for s in symbols["data"]:
            mana_symbols[s['symbol']] = {
                "cmc": s["cmc"],
                "colors": s["colors"]
            }
    with open(ManaSymbolsFile, 'w', encoding="utf8") as outfile:
        json.dump(mana_symbols, outfile)

MTGATranslations = {"en": {},
                    "es": {},
                    "fr": {},
                    "de": {},
                    "it": {},
                    "pt": {},
                    "ja": {},
                    "ko": {},
                    "ru": {},
                    "zhs": {},
                    "zht": {},
                    "ph": {}}
CardsCollectorNumberAndSet = {}
CardNameToArenaID = {}
AKRCards = {}
KLRCards = {}
for path in MTGACardsFiles:
    with open(path, 'r', encoding="utf8") as file:
        carddata = json.load(file)
        for o in carddata:
            if not ('isSecondaryCard' in o and o['isSecondaryCard']):
                o['set'] = o['set'].lower()
                if o['set'] == 'conf':
                    o['set'] = 'con'
                if o['set'] == 'dar':
                    o['set'] = 'dom'
                collectorNumber = o['CollectorNumber'] if "CollectorNumber" in o else o['collectorNumber']
                # Process AKR cards separately (except basics)
                if o["set"] == "akr":
                    if o['rarity'] != 1:
                        AKRCards[MTGALocalization['en'][o['titleId']].replace(" /// ", " // ")] = (
                            o['grpid'], collectorNumber, ArenaRarity[o['rarity']])
                if o["set"] == "klr":
                    if o['rarity'] != 1:
                        KLRCards[MTGALocalization['en'][o['titleId']].replace(" /// ", " // ")] = (
                            o['grpid'], collectorNumber, ArenaRarity[o['rarity']])
                else:
                    # Jumpstart introduced duplicate (CollectorNumbet, Set), thanks Wizard! :D
                    # Adding name to disambiguate.
                    CardsCollectorNumberAndSet[(
                        MTGALocalization['en'][o['titleId']], collectorNumber, o['set'])] = o['grpid']

                # Also look of the Arena only version (ajmp) of the card on Scryfall
                if o['set'] == 'jmp':
                    CardsCollectorNumberAndSet[(
                        MTGALocalization['en'][o['titleId']], collectorNumber, 'ajmp')] = o['grpid']

                for lang in MTGALocalization:
                    MTGATranslations[lang][o['grpid']] = {
                        'printed_name': MTGALocalization[lang][o['titleId']]}

                # From Jumpstart: Prioritizing cards from JMP and M21
                if MTGALocalization['en'][o['titleId']] not in CardNameToArenaID or o['set'] in ['jmp', 'm21']:
                    CardNameToArenaID[MTGALocalization['en']
                                      [o['titleId']]] = o['grpid']


print("AKRCards length: {}".format(len(AKRCards.keys())))
print("KLRCards length: {}".format(len(KLRCards.keys())))

with open('data/MTGADataDebug.json', 'w') as outfile:
    MTGADataDebugToJSON = {}
    for key in CardsCollectorNumberAndSet.keys():
        MTGADataDebugToJSON[str(key)] = CardsCollectorNumberAndSet[key]
    json.dump(MTGADataDebugToJSON, outfile, sort_keys=True, indent=4)

if not os.path.isfile(BulkDataPath) or ForceDownload:
    # Get Bulk Data URL
    response = requests.get("https://api.scryfall.com/bulk-data")
    bulkdata = json.loads(response.content)
    allcardURL = next(x for x in bulkdata['data'] if x['type'] == "all_cards")[
        'download_uri']
    print("Downloading {}...".format(allcardURL))
    urllib.request.urlretrieve(allcardURL, BulkDataPath)

if not os.path.isfile(ScryfallSets) or ForceDownload:
    urllib.request.urlretrieve("https://api.scryfall.com/sets", ScryfallSets)
SetsInfos = json.load(open(ScryfallSets, 'r', encoding="utf8"))['data']
PrimarySets = [s['code'] for s in SetsInfos if s['set_type']
               in ['core', 'expansion', 'masters', 'draft_innovation']]
PrimarySets.extend(['ugl', 'unh', 'ust', 'und'])


def append_set_cards(allcards, results):
    for c in results["data"]:
        try:
            idx = next(i for i, card in enumerate(allcards) if c["id"] == card["id"])
            allcards[idx] = c
            print("Updated: {}".format(c["name"]))
        except StopIteration:
            allcards.append(c)
            print("Added: {}".format(c["name"]))


# Manually fetch up-to-date data for a specific set (really unoptimized)
if FetchSet:
    print("Fetching cards from {}...".format(SetToFetch))
    setcards = requests.get(json.loads(requests.get("https://api.scryfall.com/sets/{}".format(SetToFetch)).content)["search_uri"]).json()
    allcards = []
    with open(BulkDataPath, 'r', encoding="utf8") as file:
        allcards = json.load(file)
    append_set_cards(allcards, setcards)
    while setcards["has_more"]:
        setcards = requests.get(setcards["next_page"]).json()
        append_set_cards(allcards, setcards)
    with open(BulkDataPath, 'w', encoding="utf8") as file:
        json.dump(allcards, file)


def handleTypeLine(typeLine):
    arr = typeLine.split(' — ')
    types = arr[0]
    subtypes = []  # Unused for now
    if len(arr) > 1:
        subtypes = arr[1].split()
    return types, subtypes


CardRatings = {}
with open('data/ratings_base.json', 'r', encoding="utf8") as file:
    CardRatings = dict(CardRatings, **json.loads(file.read()))
if not os.path.isfile(RatingsDest) or ForceRatings:
    for path in glob.glob('{}/*.htm*'.format(RatingSourceFolder)):
        with open(path, 'r', encoding="utf8") as file:
            text = file.read()
            matches = re.findall(
                r"<h3>([^<]+)<\/h3>\s*<b>Pro Rating: ([0-9]*\.?[0-9]*( \/\/ )?[0-9]*\.?[0-9]*)<\/b>", text)
            print("Extracting ratings from ", path,
                  ": Found ", len(matches), " matches.")
            for m in matches:
                try:
                    rating = float(m[1])
                except ValueError:
                    vals = m[1].split("//")
                    rating = (float(vals[0]) + float(vals[1]))/2
                # print(m[0], " ", rating)
                CardRatings[m[0]] = rating

    with open(RatingsDest, 'w') as outfile:
        json.dump(CardRatings, outfile)
else:
    with open(RatingsDest, 'r', encoding="utf8") as file:
        CardRatings = dict(CardRatings, **json.loads(file.read()))

if not os.path.isfile(FinalDataPath) or ForceCache:
    all_cards = []
    with open(BulkDataPath, 'r', encoding="utf8") as file:
        objects = ijson.items(file, 'item')
        ScryfallCards = (o for o in objects)

        akr_candidates = {}
        klr_candidates = {}
        sys.stdout.write("PreProcessing... ")
        sys.stdout.flush()
        copied = 0
        handled = 0
        for c in ScryfallCards:
            handled += 1

            if c['oversized'] or c['layout'] in ["token", "double_faced_token", "emblem", "art_series"]:
                continue

            # Tag this card as a candidate for AKR card images (to avoid using MTGA images)
            if c['name'] in AKRCards:
                if c["name"] not in akr_candidates:
                    akr_candidates[c["name"]] = {}
                # Prioritize version of cards from Amonkhet (AKH) or Hour of Devastation (HOU)
                if (c['set'].lower() in ['akh', 'hou']) or c['lang'] not in akr_candidates[c['name']] or (akr_candidates[c['name']][c['lang']]['set'] not in ['akh', 'hou'] and (c['released_at'] > akr_candidates[c["name"]][c['lang']]['released_at'] or (c['frame'] == "2015" and akr_candidates[c["name"]][c['lang']]['frame'] == "1997"))):
                    akr_candidates[c["name"]][c["lang"]] = c
            if c['name'] in KLRCards:
                if c["name"] not in klr_candidates:
                    klr_candidates[c["name"]] = {}
                # Prioritize version of cards from Kaladesh (KLD) or Aether Revolt (AER)
                if (c['set'].lower() in ['kld', 'aer']) or c['lang'] not in klr_candidates[c['name']] or (klr_candidates[c['name']][c['lang']]['set'] not in ['kld', 'aer'] and (c['released_at'] > klr_candidates[c["name"]][c['lang']]['released_at'] or (c['frame'] == "2015" and klr_candidates[c["name"]][c['lang']]['frame'] == "1997"))):
                    klr_candidates[c["name"]][c["lang"]] = c

            frontName = c['name']
            if ' //' in frontName:
                frontName = frontName.split(' //')[0]
            if ((c['name'], c['collector_number'], c['set'].lower()) in CardsCollectorNumberAndSet):
                c['arena_id'] = CardsCollectorNumberAndSet[(c['name'],
                                                            c['collector_number'], c['set'].lower())]
            elif ((frontName, c['collector_number'], c['set'].lower()) in CardsCollectorNumberAndSet):
                c['arena_id'] = CardsCollectorNumberAndSet[(frontName,
                                                            c['collector_number'], c['set'].lower())]

            # Workaround for Teferi, Master of Time (M21) variations (exclude all except the first one from boosters)
            if(c['set'] == 'm21' and c['collector_number'] in ['275', '276', '277']):
                c['booster'] = False
            # Workaround for premium version of some afr cards
            if(c['set'] == 'afr' and ('★' in c['collector_number'] or int(c['collector_number']) > 281)):
                c['booster'] = False

            all_cards.append(c)
            copied += 1
            if handled % 1000 == 0:
                sys.stdout.write("\b" * 100)  # return to start of line
                sys.stdout.write(
                    "PreProcessing...    {}/{} cards added...".format(copied, handled))
        sys.stdout.write("\b" * 100)
        sys.stdout.write(
            "PreProcessing done! {}/{} cards added.\n".format(copied, handled))

        sys.stdout.write("Fixing AKR images...")
        MissingAKRCards = AKRCards.copy()
        for name in akr_candidates:
            del MissingAKRCards[name]
        if len(MissingAKRCards) > 0:
            print("MissingAKRCards: ", MissingAKRCards)
        MissingKLRCards = KLRCards.copy()
        for name in klr_candidates:
            del MissingKLRCards[name]
        if len(MissingKLRCards) > 0:
            print("MissingAKRCards: ", MissingKLRCards)

        for c in all_cards:
            if c['set'] == 'akr' and c['name'] in akr_candidates and c['lang'] in akr_candidates[c['name']]:
                c['image_uris']['border_crop'] = akr_candidates[c['name']
                                                                ][c['lang']]['image_uris']['border_crop']
            if c['set'] == 'klr' and c['name'] in klr_candidates and c['lang'] in klr_candidates[c['name']]:
                c['image_uris']['border_crop'] = klr_candidates[c['name']
                                                                ][c['lang']]['image_uris']['border_crop']

        sys.stdout.write(" Done!\n")
    cards = {}
    cardsByName = {}
    Translations = {}
    print("Generating card data cache...")
    meldCards = []
    for c in all_cards:
        if c['id'] not in cards:
            cards[c['id']] = {'id': c['id']}

        key = (c['name'], c['set'], c['collector_number'])
        if key not in Translations:
            Translations[key] = {
                'printed_names': {}, 'image_uris': {}}

        if 'printed_name' in c:
            Translations[key
                         ]['printed_names'][c['lang']] = c['printed_name']
        elif 'card_faces' in c and 'printed_name' in c['card_faces'][0]:
            Translations[key]['printed_names'][c['lang']
                                               ] = c['card_faces'][0]['printed_name']

        if 'image_uris' in c and 'border_crop' in c['image_uris']:
            Translations[key]['image_uris'][c['lang']
                                            ] = c['image_uris']['border_crop']
        elif 'card_faces' in c and 'image_uris' in c['card_faces'][0] and 'border_crop' in c['card_faces'][0]['image_uris']:
            Translations[key]['image_uris'][c['lang']
                                            ] = c['card_faces'][0]['image_uris']['border_crop']

        # Handle back side of double sided cards
        if c['layout'] == 'transform' or c['layout'] == 'modal_dfc':
            if 'back' not in Translations[key]:
                Translations[key]['back'] = {'name': c['card_faces'][1]['name'], 'printed_names': {}, 'image_uris': {}}
                Translations[key]['back']['type'], Translations[key]['back']['subtypes'] = handleTypeLine(c['card_faces'][1]['type_line'])
            Translations[key]['back']['printed_names'][c['lang']
                                                       ] = c['card_faces'][1]['printed_name'] if 'printed_name' in c['card_faces'][1] else c['card_faces'][1]['name']
            if 'image_uris' not in c['card_faces'][1]:  # Temp workaround while STX data is still incomplete
                print("/!\ {}: Missing back side image.".format(c['name']))
            else:
                Translations[key]['back']['image_uris'][c['lang']
                                                        ] = c['card_faces'][1]['image_uris']['border_crop']

        if c['lang'] == 'en':
            if c['name'] in cardsByName:
                cardsByName[c['name']].append(c)
            else:
                cardsByName[c['name']] = [c]

            selection = {key: value for key, value in c.items() if key in {
                'arena_id', 'name', 'set', 'mana_cost', 'rarity', 'collector_number'}}
            if 'mana_cost' not in selection and "card_faces" in c:
                selection["mana_cost"] = c["card_faces"][0]["mana_cost"]
            selection['type'], selection['subtypes'] = handleTypeLine(c['type_line'].split(" //")[0])
            if selection['name'] in CardRatings:
                selection['rating'] = CardRatings[selection['name']]
            elif selection['name'].split(" //")[0] in CardRatings:
                selection['rating'] = CardRatings[selection['name'].split(
                    " //")[0]]
            else:

                selection['rating'] = 0.5
            selection['in_booster'] = (c['booster'] and (c['layout'] != 'meld' or not selection['collector_number'].endswith("b")))  # Exclude melded cards from boosters
            if c['set'] == 'akr' or c['set'] == 'klr':
                selection['in_booster'] = c['booster'] and not c['type_line'].startswith("Basic")
            elif not c['booster'] or c['type_line'].startswith("Basic"):
                selection['in_booster'] = False
                selection['rating'] = 0
            if c['set'] in ['sta']:  # Force STA in booster
                selection['in_booster'] = not selection['collector_number'].endswith("e")

            if c['layout'] == "split":
                if 'Aftermath' in c['keywords']:
                    selection['layout'] = 'split-left'
                elif not (c['layout'] == 'split' and c['set'] == 'cmb1'):  # Mystery booster play-test split cards use the 'normal' layout
                    selection['layout'] = 'split'
            if c['layout'] == "flip":
                selection['layout'] = 'flip'
            if c['layout'] == 'meld':  # Defer dealing with meld cards until we have all the relevant information
                meldCards.append(c)

            cards[c['id']].update(selection)

    MTGACards = {}
    for cid in list(cards):
        c = cards[cid]
        if 'name' in c:
            key = (c['name'], c['set'], c['collector_number'])
            if key in Translations:
                c.update(Translations[key])
        else:
            del cards[cid]
        if 'arena_id' in c:
            MTGACards[c['arena_id']] = c

    # Set result of melding cards as their back
    for c in meldCards:
        meldResult = [a for a in c['all_parts'] if a['component'] == 'meld_result']
        if len(meldResult) > 0:
            meldResult = cards[meldResult[0]['id']]
            cards[c['id']]['back'] = {'name': meldResult['name'], 'type': meldResult['type'], 'subtypes': meldResult['subtypes'],
                                      'printed_names': meldResult['printed_names'], 'image_uris': meldResult['image_uris']}
        else:
            print("Warning: Could not find part info for meld card (ignore if this is a result card) ", c["name"])

    # Select the "best" (most recent, non special) printing of each card
    def selectCard(a, b):
        if 'arena_id' in a and 'arena_id' not in b:
            return a
        if 'arena_id' not in a and 'arena_id' in b:
            return b
        if a['set'] in PrimarySets and not b['set'] in PrimarySets:
            return a
        if a['set'] not in PrimarySets and b['set'] in PrimarySets:
            return b
        if not a['promo'] and b['promo']:
            return a
        if a['promo'] and not b['promo']:
            return b
        return a if a['released_at'] > b['released_at'] or (a['released_at'] == a['released_at'] and (a['collector_number'] < b['collector_number'] if not (a['collector_number'].isdigit() and b['collector_number'].isdigit()) else int(a['collector_number']) < int(b['collector_number']))) else b

    for name in cardsByName:
        cardsByName[name] = functools.reduce(
            selectCard, cardsByName[name])['id']
    # Handle both references to the full names for just the front face
    for name in list(cardsByName):
        if " // " in name and name.split(" //")[0] not in cardsByName:
            cardsByName[name.split(" //")[0]] = cardsByName[name]

    with open(FinalDataPath, 'w', encoding="utf8") as outfile:
        json.dump(cards, outfile, ensure_ascii=False)

    with open("data/CardsByName.json", 'w', encoding="utf8") as outfile:
        json.dump(cardsByName, outfile, ensure_ascii=False)

    with open("client/public/data/MTGACards.json", 'w', encoding="utf8") as outfile:
        json.dump(MTGACards, outfile, ensure_ascii=False)

cards = {}
with open(FinalDataPath, 'r', encoding="utf8") as file:
    cards = json.loads(file.read())

# Retrieve basic land ids for each set
BasicLandIDs = {}
for cid in cards:
    if cards[cid]["type"].startswith("Basic"):
        if(cards[cid]["set"] not in BasicLandIDs):
            BasicLandIDs[cards[cid]["set"]] = []
        BasicLandIDs[cards[cid]["set"]].append(cid)
    for mtgset in BasicLandIDs:
        BasicLandIDs[mtgset].sort()
with open(BasicLandIDsPath, 'w+', encoding="utf8") as basiclandidsfile:
    json.dump(BasicLandIDs, basiclandidsfile, ensure_ascii=False)

###############################################################################
# Generate Jumpstart pack data

if not os.path.isfile(JumpstartBoostersDist) or ForceJumpstart:
    print("Extracting Jumpstart Boosters...")
    jumpstartBoosters = []

    regex = re.compile("(\d+) (.*)")
    swaps = {}
    with open(JumpstartSwaps, 'r', encoding="utf8") as file:
        swaps = json.loads(file.read())
    for path in glob.glob('{}/*.txt'.format(JumpstartBoostersFolder)):
        with open(path, 'r', encoding="utf8") as file:
            lines = file.readlines()
            booster = {"name": lines[0].strip(), "cards": []}
            for line in lines[1:]:
                m = regex.match(line.strip())
                if m:
                    count = int(m.group(1))
                    name = m.group(2)
                    if name in swaps:
                        name = swaps[name]
                    if name in CardNameToArenaID:
                        cid = None
                        for c in cards:
                            if 'arena_id' in cards[c] and cards[c]['arena_id'] == CardNameToArenaID[name]:
                                cid = cards[c]['id']
                                break
                        # Some cards are labeled as JMP in Arena but not on Scryfall (Swaped cards). We can search for an alternative version.
                        if cid == None:
                            print("{} ({}) not found in cards...".format(name, cid))
                            candidates = [
                                key for key, val in cards.items() if val['name'] == name and val['set'] != 'jmp']
                            if len(candidates) == 0:
                                print(
                                    " > Cannot find a good candidate ID for {} !!".format(name))
                            else:
                                cid = max(candidates)
                                print("> Using {}".format(cid))
                        booster["cards"] += [cid] * count
                    else:
                        print("Jumpstart Boosters: Card '{}' not found.".format(name))
            jumpstartBoosters.append(booster)
    print("Jumpstart Boosters: ", len(jumpstartBoosters))
    with open(JumpstartBoostersDist, 'w', encoding="utf8") as outfile:
        json.dump(jumpstartBoosters, outfile, ensure_ascii=False)
    print("Jumpstart boosters dumped to disk.")


###############################################################################
# Retreive Jumpstart: Historic Horizons pack information directly from Wizards' site

PacketListURL = "https://magic.wizards.com/en/articles/archive/magic-digital/jumpstart-historic-horizons-packet-lists-2021-07-26"
TitleRegex = r"<span class=\"deck-meta\">\s*<h4>([^<]+)</h4>"
CardsRegex = r"<span class=\"card-count\">(\d+)</span>\s*<span class=\"card-name\">(?:<a[^>]*>)?([^<]+)(?:</a>)?</span>"
AlternateLinesRegex = r"<tr[\s\S]*?<\/tr>"
AlternateCardsRegex = r"<td><a href=\"https://gatherer\.wizards\.com/Pages/Card/Details\.aspx\?name=.*\" class=\"autocard-link\" data-image-url=\"https://gatherer\.wizards\.com/Handlers/Image\.ashx\?type=card&amp;name=.*\">(.+)</a></td>\s*<td>(\d+)%</td>"
TotalRegex = r"<div class=\"regular-card-total\">(\d+) Cards"

if not os.path.isfile(JumpstartHHBoostersDist) or ForceJumpstartHH:
    CardIDsByName = {}
    for cid in cards:
        cardname = cards[cid]["name"].split(" //")[0]
        if cardname not in CardIDsByName:
            CardIDsByName[cardname] = []
        CardIDsByName[cardname].append(cid)

    CyclingLands = {
        "W": "f27cfdab-7a27-4cd9-9f0d-c6fe8294e6c7", "U": "9db4c029-3f8d-4fd7-bb40-0414ca6fd4a0", "B": "bbf00df0-3857-4bd7-8993-656eb3426511", "R": "5e82b3fa-a7b8-4ca2-9ce3-054475b407cf", "G": "9ffbc971-f61c-4e04-bc52-4f9b5c31ef37"
    }

    def getIDFromNameForJHH(name):
        if name not in CardIDsByName:
            # print("Could not find a suitable CardID for '{}'".format(name))
            return None
        candidates = CardIDsByName[name]
        best = cards[candidates[0]]
        for cid in candidates:
            if cards[cid]["set"] == "j21":
                return cid
            elif cards[cid]["set"] == "mh2":
                best = cards[cid]
            elif cards[cid]["set"] == "m20" and best["set"] != "mh2":
                best = cards[cid]
            elif best["set"] == cards[cid]["set"] and cards[cid]["collector_number"].isdigit() and (not best["collector_number"].isdigit() or int(cards[cid]["collector_number"]) < int(best["collector_number"])):
                best = cards[cid]
            if "arena_id" in cards[cid] and "arena_id" not in best:
                best = cards[cid]
        return best["id"]

    NameFixes = {
        "Serra, the Benevolent": "Serra the Benevolent",
        "Storm-God's Oracle": "Storm God's Oracle",
        "Fall of the Imposter": "Fall of the Impostor",
        "Aliros, Enraptured": "Alirios, Enraptured",
        "Filligree Attendent": "Filigree Attendant",
        "Imposter of the Sixth Pride": "Impostor of the Sixth Pride",
        "Gadrak, the Crown Scourge": "Gadrak, the Crown-Scourge",
        "Scour all Possibilities": "Scour All Possibilities",
        "Storm-Kin Artist": "Storm-Kiln Artist",
        "Maurading Boneslasher": "Marauding Boneslasher",
        "Cemetary Recruitment": "Cemetery Recruitment",
        "Radiant&rsquo;s Judgment": "Radiant's Judgment",
        "Djeru&rsquo;s Renunciation": "Djeru's Renunciation",
        "Imposing Vantasau": "Imposing Vantasaur"
    }

    def fix_cardname(n):
        r = n.split(" //")[0].strip()
        if(r in NameFixes):
            return NameFixes[r]
        return r

    print("Extracting Jumpstart: Historic Horizons Boosters...")
    jumpstartHHBoosters = []
    page = requests.get(PacketListURL).text
    matches = re.finditer(TitleRegex, page)
    matches_arr = []
    for m in matches:
        matches_arr.append(m)
    for idx in range(len(matches_arr)):
        start = page.find("<div class=\"sorted-by-rarity-container sortedContainer\" style=\"display:none;\">", matches_arr[idx].span()[1])
        end = matches_arr[idx + 1].span()[0] if idx < len(matches_arr) - 1 else len(page)
        total_expected_cards = int(re.search(TotalRegex, page[start:end]).group(1))
        cards_matches = re.findall(CardsRegex, page[start:end])
        jhh_cards = []
        colors = set()
        cycling_land = False
        rarest_card = None
        for c in cards_matches:
            cardname = fix_cardname(c[1])
            if(cardname == "Cycling Land"):
                jhh_cards.append(CyclingLands[next(iter(colors))])
                continue
            cid = getIDFromNameForJHH(cardname)
            if cid == None:  # FIXME: Temp workaround, remove it when all cards are here.
                cid = getIDFromNameForJHH("\"{}\"".format(cardname))
            if cid != None:
                for color in filter(lambda a: a in "WUBRG", cards[cid]["mana_cost"]):
                    colors.add(color)
                if(rarest_card == None or Rarity[cards[cid]["rarity"]] < Rarity[cards[rarest_card]["rarity"]]):
                    rarest_card = cid
                for i in range(int(c[0])):  # Add the card c[0] times
                    jhh_cards.append(cid)
            else:
                print("Jumpstart: Historic Horizons Boosters: Card '{}' ('{}') not found.".format(cardname, c[1]))
        altcards = []
        altline_matches = re.findall(AlternateLinesRegex, page[start:end])
        for l in altline_matches:
            alt_matches = re.findall(AlternateCardsRegex, l)
            if len(alt_matches) > 0:
                altslot = []
                for altidx, alt in enumerate(alt_matches):
                    cardname = fix_cardname(alt[0])
                    cid = None
                    if cardname == "Cycling Land":
                        cid = CyclingLands[next(iter(colors))]
                    else:
                        cid = getIDFromNameForJHH(cardname)
                    if cid == None:
                        print("Jumpstart: Historic Horizons Boosters: Card '{}' ('{}') not found.".format(cardname, alt[0]))
                    else:
                        altslot.append({"name": cards[cid]["name"], "id": cid, "weight": int(alt[1])})
                        if altidx == 0 and cid in jhh_cards:
                            jhh_cards.remove(cid)
                if len(altslot) > 0:
                    altcards.append(altslot)
                else:
                    print("Jumpstart: Historic Horizons Boosters: Empty Alt Slot.")
                    print(alt_matches)
        found_cards = len(jhh_cards) + len(altcards)
        if found_cards != total_expected_cards:
            print("\tUnexpected number of cards for {} ({}/{})!".format(matches_arr[idx].group(1), found_cards, total_expected_cards))
        else:
            print("Added Pack '{}', {} + {} = {}/{} cards.".format(matches_arr[idx].group(1), len(jhh_cards), len(altcards), found_cards, total_expected_cards))
            jumpstartHHBoosters.append({"name": matches_arr[idx].group(1), "colors": list(colors), "cycling_land": cycling_land,
                                        "image": cards[rarest_card]["image_uris"]["en"] if rarest_card != None else None, "cards": jhh_cards, "alts": altcards})
    print("Jumpstart Boosters: {}/46".format(len(jumpstartHHBoosters)))
    with open(JumpstartHHBoostersDist, 'w', encoding="utf8") as outfile:
        json.dump(jumpstartHHBoosters, outfile, indent=4, ensure_ascii=False,)
    print("Jumpstart: Historic Horizons boosters dumped to disk.")

###############################################################################


def overrideViewbox(svgPath, expectedViewbox, correctedViewbox):
    with open(svgPath, 'r') as inputFile:
        inputFile.seek(0)
        content = inputFile.read()
        if 'viewBox="%s"' % expectedViewbox not in content:
            print("svg did not have expected viewbox: %s" % svgPath)
            return
        content = content.replace(
            'viewBox="%s"' % expectedViewbox, 'viewBox="%s"' % correctedViewbox)
    with open(svgPath, 'w') as outputFile:
        outputFile.write(content)


array = []
for key, value in cards.items():
    array.append(value)

print("Cards in database: ", len(array))
array.sort(key=lambda c: c['set'])
groups = groupby(array, lambda c: c['set'])
setinfos = {}


def getIcon(mtgset, icon_path):
    if not os.path.isfile("client/public/" + icon_path):
        try:
            response = requests.get(
                "https://api.scryfall.com/sets/{}".format(mtgset))
            scryfall_set_data = json.loads(response.content)
            if scryfall_set_data and 'icon_svg_uri' in scryfall_set_data:
                urllib.request.urlretrieve(
                    scryfall_set_data['icon_svg_uri'], "client/public/" + icon_path)
                if set == "rna":
                    overrideViewbox(icon_path, "0 0 32 32", "0 6 32 20")
                return icon_path
        except:
            print("Error getting set '{}' icon:".format(mtgset), sys.exc_info()[0])
    else:
        return icon_path
    return None


nth = 1
set_per_line = m1.floor(os.get_terminal_size().columns / 14)
subsets = []  # List of sub-sets associated to a larger, standard set.
for mtgset, group in groups:
    cardList = list(group)
    setdata = next(x for x in SetsInfos if x['code'] == mtgset)
    if("parent_set_code" in setdata):
        subsets.append(mtgset)
    setinfos[mtgset] = {"code": mtgset,
                        "fullName": setdata['name'],
                        "cardCount": len(cardList),

                        "isPrimary": mtgset in PrimarySets
                        }
    if 'block' in setdata:
        setinfos[mtgset]["block"] = setdata['block']
    # con is a reserved keyword on windows
    icon_path = "img/sets/{}.svg".format(mtgset if mtgset != 'con' else 'conf')
    if getIcon(mtgset, icon_path) != None:
        setinfos[mtgset]['icon'] = icon_path
    print(' | {:6s} {:4d}'.format(mtgset, len(cardList)), end=(' |\n' if nth % set_per_line == 0 else ''))
    nth += 1
    cardList.sort(key=lambda c: c['rarity'])
    for rarity, rarityGroup in groupby(cardList, lambda c: c['rarity']):
        rarityGroupList = list(rarityGroup)
        setinfos[mtgset][rarity + "Count"] = len(rarityGroupList)
with open(SetsInfosPath, 'w+', encoding="utf8") as setinfosfile:
    json.dump(setinfos, setinfosfile, ensure_ascii=False)

constants = {}
with open("src/data/constants.json", 'r', encoding="utf8") as constantsFile:
    constants = json.loads(constantsFile.read())
constants['PrimarySets'] = [
    s for s in PrimarySets if s in setinfos and s not in subsets and s not in []]  # Exclude some codes that are actually part of larger sets (tsb, fmb1, h1r... see subsets), or aren't out yet ()
with open("src/data/constants.json", 'w', encoding="utf8") as constantsFile:
    json.dump(constants, constantsFile, ensure_ascii=False, indent=4)
