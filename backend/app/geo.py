"""Gazetteer: European departure cities and worldwide destinations.

Aliases are matched case-insensitively on word boundaries. An alias ending in
``*`` is a stem and also matches up to 4 trailing letters, which covers Polish,
Lithuanian and German declensions (e.g. ``tajlandi*`` -> Tajlandia/Tajlandii/Tajlandię).
Coordinates are approximate city/country centroids used for the map.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# --------------------------------------------------------------------------- origins
# (iata, city, country, lat, lon, priority(1=highest), aliases)
ORIGINS: list[tuple] = [
    ("VNO", "Vilnius", "LT", 54.687, 25.279, 1, ["vilnius", "wilno", "wilna", "vilniaus", "vilniuje", "iš vilniaus"]),
    ("KUN", "Kaunas", "LT", 54.898, 23.903, 1, ["kaunas", "kowno", "kauno"]),
    ("RIX", "Riga", "LV", 56.949, 24.105, 1, ["riga", "rīga", "ryga", "rygi", "rygos", "rīgas"]),
    ("TLL", "Tallinn", "EE", 59.437, 24.754, 1, ["tallinn", "tallin", "talin", "talina", "talino"]),
    ("WAW", "Warsaw", "PL", 52.229, 21.012, 1, ["warsaw", "warszaw*", "warschau", "varšuv*", "modlin*", "chopin"]),
    ("KRK", "Krakow", "PL", 50.064, 19.945, 2, ["krakow", "kraków", "krakowa", "krakau"]),
    ("GDN", "Gdansk", "PL", 54.352, 18.646, 2, ["gdansk", "gdańsk", "gdańska", "gdanska", "danzig"]),
    ("KTW", "Katowice", "PL", 50.264, 19.023, 2, ["katowice", "katowic", "kattowitz", "pyrzowic"]),
    ("POZ", "Poznan", "PL", 52.406, 16.925, 3, ["poznan", "poznań", "poznania"]),
    ("WRO", "Wroclaw", "PL", 51.107, 17.038, 3, ["wroclaw", "wrocław", "wrocławia", "breslau"]),
    ("VIE", "Vienna", "AT", 48.208, 16.373, 1, ["vienna", "wien", "wiedeń", "wiednia", "vienos", "viena", "vienne"]),
    ("BTS", "Bratislava", "SK", 48.148, 17.107, 2, ["bratislava", "bratysław*", "pressburg"]),
    ("BUD", "Budapest", "HU", 47.497, 19.040, 2, ["budapest", "budapeszt*", "budapešt*"]),
    ("PRG", "Prague", "CZ", 50.075, 14.437, 2, ["prague", "prag", "praga", "pragi", "praha"]),
    ("BER", "Berlin", "DE", 52.520, 13.405, 2, ["berlin", "berlina", "berlyn*"]),
    ("MUC", "Munich", "DE", 48.135, 11.582, 2, ["munich", "münchen", "muenchen", "monachium", "monachijum", "monaco di baviera"]),
    ("FRA", "Frankfurt", "DE", 50.110, 8.682, 2, ["frankfurt", "frankfurtu", "frankfurto", "francoforte"]),
    ("AMS", "Amsterdam", "NL", 52.367, 4.904, 3, ["amsterdam", "amsterdamu", "amsterdamo"]),
    ("BRU", "Brussels", "BE", 50.850, 4.352, 3, ["brussels", "brüssel", "bruksel*", "bruxelles", "bruselas", "briusel*"]),
    ("CPH", "Copenhagen", "DK", 55.676, 12.568, 3, ["copenhagen", "kopenhag*", "københavn", "copenaghen", "kopenhagos"]),
    ("ARN", "Stockholm", "SE", 59.329, 18.069, 3, ["stockholm", "sztokholm*", "stokholm*", "stoccolma"]),
    ("HEL", "Helsinki", "FI", 60.170, 24.938, 3, ["helsinki", "helsink*", "helsingfors"]),
    ("OSL", "Oslo", "NO", 59.914, 10.752, 3, ["oslo"]),
    ("MXP", "Milan", "IT", 45.464, 9.190, 3, ["milan", "milano", "mailand", "mediolan*", "milan bergamo", "bergamo"]),
    ("FCO", "Rome", "IT", 41.903, 12.496, 3, ["rome", "roma", "rom", "rzym*", "romos"]),
    ("CDG", "Paris", "FR", 48.857, 2.352, 3, ["paris", "paryż*", "paryz*", "parigi", "paryžiaus"]),
    ("LON", "London", "GB", 51.507, -0.128, 3, ["london", "londyn*", "londra", "londres", "londono", "heathrow", "gatwick", "stansted", "manchester", "edinburgh"]),
    ("MAD", "Madrid", "ES", 40.417, -3.704, 3, ["madrid", "madryt*", "madrido"]),
    ("BCN", "Barcelona", "ES", 41.385, 2.173, 3, ["barcelona", "barcelon*"]),
    ("IST", "Istanbul", "TR", 41.008, 28.978, 3, ["istanbul", "stambuł*", "stambul*", "istanbulo"]),
    ("LIS", "Lisbon", "PT", 38.722, -9.139, 3, ["lisbon", "lizbon*", "lissabon", "lisboa"]),
    ("ATH", "Athens", "GR", 37.984, 23.728, 3, ["athens", "aten*", "athen"]),
    ("DUB", "Dublin", "IE", 53.350, -6.260, 3, ["dublin", "dublina"]),
    ("ZRH", "Zurich", "CH", 47.377, 8.540, 3, ["zurich", "zürich", "zurych*"]),
    ("DUS", "Dusseldorf", "DE", 51.227, 6.773, 3, ["düsseldorf", "dusseldorf", "duesseldorf"]),
    ("HAM", "Hamburg", "DE", 53.551, 9.993, 3, ["hamburg", "hamburga"]),
]

# Default enabled set: the user's priority list
DEFAULT_ENABLED = {
    "VNO", "KUN", "RIX", "TLL", "WAW", "KRK", "GDN", "KTW", "VIE", "BTS", "BUD", "PRG",
    "BER", "MUC", "FRA", "AMS", "BRU", "CPH", "ARN", "HEL", "MXP", "FCO", "CDG", "LON",
    "MAD", "BCN", "IST",
}

# Country-level "various airports" origins used when a source implies a market
COUNTRY_ORIGINS = {
    "PL*": ("Poland (various airports)", 52.0, 19.4),
    "LT*": ("Lithuania (Vilnius/Kaunas)", 55.2, 23.9),
    "DE*": ("Germany/Austria (various)", 51.0, 10.4),
    "GB*": ("United Kingdom (various)", 52.5, -1.5),
    "IT*": ("Italy (various)", 42.8, 12.5),
    "EU*": ("Multiple European airports", 50.1, 14.4),
}

# --------------------------------------------------------------------------- regions
# Reference return economy fare from Europe (EUR) per region, used as the prior
# for the scoring engine. Sources: typical published fare ranges 2024-2026;
# see docs/SCORING.md. They are deliberately conservative "normal" prices.
REGIONS = {
    "europe":          {"label": "Europe",                 "ref_return": 160,  "hotel_night": 55, "long_haul": False},
    "canaries_nafrica": {"label": "Canaries & North Africa", "ref_return": 260,  "hotel_night": 50, "long_haul": False},
    "egypt_redsea":    {"label": "Egypt & Red Sea",        "ref_return": 330,  "hotel_night": 45, "long_haul": False},
    "middle_east":     {"label": "Middle East",            "ref_return": 420,  "hotel_night": 80, "long_haul": False},
    "central_asia":    {"label": "Caucasus & Central Asia", "ref_return": 380,  "hotel_night": 40, "long_haul": False},
    "south_asia":      {"label": "India & Sri Lanka",      "ref_return": 680,  "hotel_night": 45, "long_haul": True},
    "indian_ocean":    {"label": "Maldives, Seychelles, Mauritius", "ref_return": 850, "hotel_night": 110, "long_haul": True},
    "se_asia":         {"label": "Southeast Asia",         "ref_return": 720,  "hotel_night": 45, "long_haul": True},
    "east_asia":       {"label": "Japan & Korea",          "ref_return": 850,  "hotel_night": 85, "long_haul": True},
    "china_hk":        {"label": "China & Hong Kong",      "ref_return": 650,  "hotel_night": 80, "long_haul": True},
    "na_east":         {"label": "USA East & Canada",      "ref_return": 500,  "hotel_night": 140, "long_haul": True},
    "na_west":         {"label": "USA West & Hawaii",      "ref_return": 720,  "hotel_night": 150, "long_haul": True},
    "caribbean":       {"label": "Caribbean & Mexico",     "ref_return": 780,  "hotel_night": 90, "long_haul": True},
    "south_america":   {"label": "South America",          "ref_return": 880,  "hotel_night": 55, "long_haul": True},
    "east_africa":     {"label": "East Africa & Zanzibar", "ref_return": 720,  "hotel_night": 70, "long_haul": True},
    "southern_africa": {"label": "Southern Africa",        "ref_return": 820,  "hotel_night": 70, "long_haul": True},
    "west_africa":     {"label": "Cape Verde & West Africa", "ref_return": 380, "hotel_night": 60, "long_haul": False},
    "oceania":         {"label": "Australia & New Zealand", "ref_return": 1350, "hotel_night": 110, "long_haul": True},
}

# --------------------------------------------------------------------------- destinations
# (key, name, country, region, lat, lon, iata or "", aliases)
DESTINATIONS: list[tuple] = [
    # South Asia
    ("colombo", "Sri Lanka", "Sri Lanka", "south_asia", 7.87, 80.77, "CMB", ["sri lanka", "sri lank*", "šri lank*", "colombo", "kolombo"]),
    ("delhi", "Delhi", "India", "south_asia", 28.61, 77.21, "DEL", ["delhi", "new delhi", "nowe delhi", "delhi"]),
    ("mumbai", "Mumbai", "India", "south_asia", 19.08, 72.88, "BOM", ["mumbai", "bombaj"]),
    ("goa", "Goa", "India", "south_asia", 15.49, 73.83, "GOI", ["goa"]),
    ("india", "India", "India", "south_asia", 22.0, 79.0, "DEL", ["india", "indie", "indii", "indien", "indij*"]),
    ("kathmandu", "Nepal", "Nepal", "south_asia", 27.71, 85.32, "KTM", ["nepal*", "kathmandu", "katmandu"]),
    # Indian Ocean
    ("maldives", "Maldives", "Maldives", "indian_ocean", 4.18, 73.51, "MLE", ["maldives", "malediw*", "malediven", "maldyv*", "maldive"]),
    ("seychelles", "Seychelles", "Seychelles", "indian_ocean", -4.68, 55.49, "SEZ", ["seychelles", "seszel*", "seychellen", "seišel*"]),
    ("mauritius", "Mauritius", "Mauritius", "indian_ocean", -20.16, 57.50, "MRU", ["mauritius", "mauritiu*", "maurice", "mauricij*"]),
    # Southeast Asia
    ("bangkok", "Bangkok", "Thailand", "se_asia", 13.76, 100.50, "BKK", ["bangkok*", "bankok*"]),
    ("phuket", "Phuket", "Thailand", "se_asia", 7.88, 98.39, "HKT", ["phuket"]),
    ("thailand", "Thailand", "Thailand", "se_asia", 13.0, 101.0, "BKK", ["thailand", "tajlandi*", "tailand*", "thailandia", "krabi", "koh samui", "chiang mai"]),
    ("hanoi", "Hanoi", "Vietnam", "se_asia", 21.03, 105.85, "HAN", ["hanoi", "hanoj*"]),
    ("saigon", "Ho Chi Minh City", "Vietnam", "se_asia", 10.82, 106.63, "SGN", ["ho chi minh*", "saigon", "sajgon*"]),
    ("vietnam", "Vietnam", "Vietnam", "se_asia", 16.0, 107.0, "SGN", ["vietnam*", "wietnam*", "phu quoc", "da nang"]),
    ("bali", "Bali", "Indonesia", "se_asia", -8.65, 115.22, "DPS", ["bali", "denpasar"]),
    ("jakarta", "Jakarta", "Indonesia", "se_asia", -6.21, 106.85, "CGK", ["jakart*", "dżakart*", "indonesia", "indonezj*", "indonesien", "indonezij*"]),
    ("manila", "Philippines", "Philippines", "se_asia", 14.60, 120.98, "MNL", ["manila", "manili", "philippines", "filipin*", "philippinen", "cebu"]),
    ("kualalumpur", "Kuala Lumpur", "Malaysia", "se_asia", 3.14, 101.69, "KUL", ["kuala lumpur", "malaysia", "malezj*", "malaizij*", "langkawi", "penang"]),
    ("singapore", "Singapore", "Singapore", "se_asia", 1.35, 103.82, "SIN", ["singapore", "singapur*", "singapūr*"]),
    ("cambodia", "Cambodia", "Cambodia", "se_asia", 11.56, 104.92, "PNH", ["cambodia", "kambodż*", "kambodscha", "phnom penh", "siem reap"]),
    # East Asia
    ("tokyo", "Tokyo", "Japan", "east_asia", 35.68, 139.69, "TYO", ["tokyo", "tokio", "tokij*", "tōkyō"]),
    ("osaka", "Osaka", "Japan", "east_asia", 34.69, 135.50, "OSA", ["osaka", "osace", "osak*"]),
    ("japan", "Japan", "Japan", "east_asia", 36.2, 138.25, "TYO", ["japan", "japoni*", "giappone", "japonij*", "jpn"]),
    ("seoul", "Seoul", "South Korea", "east_asia", 37.57, 126.98, "SEL", ["seoul", "seul*", "south korea", "korea", "korei", "koreę", "südkorea", "pietų korėj*"]),
    # China
    ("hongkong", "Hong Kong", "Hong Kong", "china_hk", 22.32, 114.17, "HKG", ["hong kong*", "hongkong*"]),
    ("shanghai", "Shanghai", "China", "china_hk", 31.23, 121.47, "SHA", ["shanghai", "szanghaj*", "china", "chiny", "kinij*", "beijing", "pekin*", "peking", "chengdu", "guangzhou"]),
    ("taipei", "Taiwan", "Taiwan", "china_hk", 25.03, 121.57, "TPE", ["taipei", "taiwan", "tajwan*", "taivan*"]),
    # North America
    ("newyork", "New York", "United States", "na_east", 40.71, -74.01, "NYC", ["new york*", "nowy jork", "nowego jorku", "nowym jorku", "niujork*", "nyc", "newark", "jfk"]),
    ("boston", "Boston", "United States", "na_east", 42.36, -71.06, "BOS", ["boston*"]),
    ("washington", "Washington", "United States", "na_east", 38.91, -77.04, "WAS", ["washington", "waszyngton*", "dulles"]),
    ("miami", "Miami", "United States", "na_east", 25.76, -80.19, "MIA", ["miami", "florida", "floryd*", "orlando"]),
    ("chicago", "Chicago", "United States", "na_east", 41.88, -87.63, "CHI", ["chicago", "chicag*"]),
    ("toronto", "Toronto", "Canada", "na_east", 43.65, -79.38, "YTO", ["toronto", "montreal", "montréal", "canada", "kanad*", "vancouver"]),
    ("usa", "United States", "United States", "na_east", 39.8, -98.6, "NYC", ["usa", "united states", "stany zjednoczone", "stanów zjednoczonych", "jav", "vereinigte staaten", "amerik*"]),
    ("losangeles", "Los Angeles", "United States", "na_west", 34.05, -118.24, "LAX", ["los angeles", "l.a.", "kalifornia", "california", "kalifornien"]),
    ("sanfrancisco", "San Francisco", "United States", "na_west", 37.77, -122.42, "SFO", ["san francisco"]),
    ("lasvegas", "Las Vegas", "United States", "na_west", 36.17, -115.14, "LAS", ["las vegas"]),
    ("hawaii", "Hawaii", "United States", "na_west", 21.31, -157.86, "HNL", ["hawaii", "hawaj*", "honolulu"]),
    # Caribbean & Mexico
    ("cancun", "Cancun", "Mexico", "caribbean", 21.16, -86.85, "CUN", ["cancun", "cancún", "mexico", "meksyk*", "mexiko", "meksik*", "messico", "riviera maya", "playa del carmen", "mexico city"]),
    ("bahamas", "Bahamas", "Bahamas", "caribbean", 25.05, -77.35, "NAS", ["bahamas", "bahamy", "bahamach", "nassau", "cococay", "bahamų"]),
    ("cozumel", "Cozumel & Mexican Riviera", "Mexico", "caribbean", 20.42, -86.92, "CZM", ["cozumel", "mexican riviera", "ensenada", "cabo san lucas", "puerto vallarta"]),
    ("havana", "Cuba", "Cuba", "caribbean", 23.11, -82.37, "HAV", ["cuba", "kub*", "havana", "hawan*", "varadero"]),
    ("puntacana", "Dominican Republic", "Dominican Republic", "caribbean", 18.58, -68.40, "PUJ", ["dominican republic", "dominikan*", "dominikanische republik", "punta cana", "santo domingo", "repubblica dominicana"]),
    ("jamaica", "Jamaica", "Jamaica", "caribbean", 18.11, -77.30, "MBJ", ["jamaica", "jamajk*", "jamaika"]),
    ("barbados", "Barbados", "Barbados", "caribbean", 13.19, -59.54, "BGI", ["barbados"]),
    ("stlucia", "Saint Lucia", "Saint Lucia", "caribbean", 13.91, -60.98, "UVF", ["saint lucia", "st lucia", "st. lucia", "santa lucia"]),
    ("aruba", "Aruba & Curaçao", "Netherlands Antilles", "caribbean", 12.17, -68.99, "CUR", ["aruba", "curacao", "curaçao", "bonaire"]),
    ("guadeloupe", "Guadeloupe & Martinique", "France (Caribbean)", "caribbean", 16.25, -61.58, "PTP", ["guadeloupe", "gwadelup*", "martinique", "martynik*"]),
    ("caribbean", "Caribbean", "Caribbean", "caribbean", 18.0, -66.0, "PUJ", ["caribbean", "karaib*", "karibik", "caraibi", "karib*"]),
    # South America
    ("riodejaneiro", "Rio de Janeiro", "Brazil", "south_america", -22.91, -43.17, "RIO", ["rio de janeiro", "rio"]),
    ("saopaulo", "São Paulo", "Brazil", "south_america", -23.55, -46.63, "SAO", ["são paulo", "sao paulo", "brazil", "brazyli*", "brasilien", "brasile", "brazilij*", "fortaleza", "recife", "salvador"]),
    ("buenosaires", "Buenos Aires", "Argentina", "south_america", -34.60, -58.38, "BUE", ["buenos aires", "argentin*", "argentyn*", "argentinien"]),
    ("bogota", "Colombia", "Colombia", "south_america", 4.71, -74.07, "BOG", ["colombia", "kolumbi*", "kolumbien", "bogota", "bogotá", "cartagena", "medellin", "medellín"]),
    ("lima", "Peru", "Peru", "south_america", -12.05, -77.04, "LIM", ["peru", "lima", "cusco"]),
    ("santiago", "Chile", "Chile", "south_america", -33.45, -70.67, "SCL", ["chile", "santiago de chile", "čilė*"]),
    ("quito", "Ecuador", "Ecuador", "south_america", -0.18, -78.47, "UIO", ["ecuador", "ekwador*", "quito", "galapagos"]),
    # Africa
    ("zanzibar", "Zanzibar", "Tanzania", "east_africa", -6.17, 39.20, "ZNZ", ["zanzibar*", "sansibar", "zanzibaras"]),
    ("tanzania", "Tanzania", "Tanzania", "east_africa", -6.37, 34.89, "DAR", ["tanzani*", "tansania", "kilimanjaro", "dar es salaam"]),
    ("nairobi", "Kenya", "Kenya", "east_africa", -1.29, 36.82, "NBO", ["kenya", "keni*", "kenia", "nairobi", "mombasa"]),
    ("ethiopia", "Ethiopia", "Ethiopia", "east_africa", 8.98, 38.76, "ADD", ["ethiopia", "etiopi*", "addis abeba", "addis ababa"]),
    ("capetown", "Cape Town", "South Africa", "southern_africa", -33.92, 18.42, "CPT", ["cape town", "kapsztad*", "kapstadt", "south africa", "rpa", "südafrika", "afryk* południow*", "johannesburg", "kruger"]),
    ("namibia", "Namibia", "Namibia", "southern_africa", -22.56, 17.08, "WDH", ["namibi*", "windhoek"]),
    ("madagascar", "Madagascar", "Madagascar", "indian_ocean", -18.88, 47.51, "TNR", ["madagascar", "madagaskar*"]),
    ("capeverde", "Cape Verde", "Cape Verde", "west_africa", 16.0, -24.0, "SID", ["cape verde", "kapverden", "wyspy zielonego przylądka", "zielony przylądek", "capo verde", "sal island", "boa vista", "boavista", "žaliojo kyšulio"]),
    ("senegal", "Senegal", "Senegal", "west_africa", 14.72, -17.47, "DSS", ["senegal*", "dakar"]),
    ("egypt", "Egypt", "Egypt", "egypt_redsea", 27.26, 33.81, "HRG", ["egypt", "egipt*", "ägypten", "egiptas", "egiptą", "egitto", "hurghada", "hurgad*", "sharm el sheikh", "szarm el szejk", "marsa alam", "kair*", "cairo"]),
    ("morocco", "Morocco", "Morocco", "canaries_nafrica", 31.63, -8.0, "RAK", ["morocco", "marok*", "marokko", "marrakech", "marrakesz", "marrakesch", "agadir", "chefchaouen", "marocco"]),
    ("tunisia", "Tunisia", "Tunisia", "canaries_nafrica", 35.83, 10.64, "TUN", ["tunisia", "tunezj*", "tunesien", "tunisas", "djerba", "dżerba", "monastir", "hammamet"]),
    ("canaries", "Canary Islands", "Spain", "canaries_nafrica", 28.29, -16.63, "TFS", ["canary islands", "canaries", "kanary", "kanarach", "kanaren", "kanarų", "kanarai", "tenerife", "teneryf*", "teneriffa", "gran canaria", "lanzarote", "fuerteventura"]),
    ("madeira", "Madeira", "Portugal", "canaries_nafrica", 32.65, -16.91, "FNC", ["madeira", "madera", "maderę", "maderze", "funchal"]),
    # Middle East / Central Asia
    ("dubai", "Dubai", "UAE", "middle_east", 25.20, 55.27, "DXB", ["dubai", "dubaj*", "uae", "emiraty", "abu dhabi", "abu zabi", "ras al khaimah"]),
    ("oman", "Oman", "Oman", "middle_east", 23.59, 58.41, "MCT", ["oman*", "muscat", "maskat"]),
    ("jordan", "Jordan", "Jordan", "middle_east", 31.95, 35.93, "AMM", ["jordan*", "jordani*", "aqaba", "akaba", "amman"]),
    ("qatar", "Qatar", "Qatar", "middle_east", 25.29, 51.53, "DOH", ["qatar", "katar*", "doha"]),
    ("kuwait", "Kuwait", "Kuwait", "middle_east", 29.37, 47.98, "KWI", ["kuwait", "kuwejt*"]),
    ("iraq", "Iraq", "Iraq", "middle_east", 36.19, 44.01, "EBL", ["iraq", "irak*", "erbil"]),
    ("kazakhstan", "Kazakhstan", "Kazakhstan", "central_asia", 43.24, 76.89, "ALA", ["kazakhstan", "kazachst*", "almaty", "astana"]),
    ("uzbekistan", "Uzbekistan", "Uzbekistan", "central_asia", 41.30, 69.24, "TAS", ["uzbekistan", "uzbekist*", "tashkent", "taszkent", "samarkand*"]),
    ("kyrgyzstan", "Kyrgyzstan", "Kyrgyzstan", "central_asia", 42.87, 74.59, "FRU", ["kyrgyzstan", "kirgist*", "bishkek", "biszkek"]),
    ("georgia", "Georgia", "Georgia", "central_asia", 41.72, 44.79, "TBS", ["georgia (country)", "gruzj*", "georgien", "tbilisi", "tbilis*", "kutaisi", "kutaisu", "batumi"]),
    ("pakistan", "Pakistan", "Pakistan", "central_asia", 33.68, 73.05, "ISB", ["pakistan*", "islamabad", "lahore"]),
    # Oceania
    ("sydney", "Sydney", "Australia", "oceania", -33.87, 151.21, "SYD", ["sydney", "sydnej*", "australia", "australi*", "australien", "melbourne", "brisbane", "perth"]),
    ("auckland", "New Zealand", "New Zealand", "oceania", -36.85, 174.76, "AKL", ["new zealand", "nowa zelandia", "nowej zelandii", "neuseeland", "auckland", "naujoji zeland*"]),
    # Europe leisure destinations (so packages resolve correctly)
    ("crete", "Crete", "Greece", "europe", 35.24, 24.81, "HER", ["crete", "kreta", "krecie", "kretę", "heraklion"]),
    ("rhodes", "Rhodes", "Greece", "europe", 36.43, 28.22, "RHO", ["rhodes", "rodos", "rodosie", "rhodos"]),
    ("kos", "Kos", "Greece", "europe", 36.89, 27.29, "KGS", ["kos"]),
    ("corfu", "Corfu", "Greece", "europe", 39.62, 19.92, "CFU", ["corfu", "korfu"]),
    ("greece", "Greece", "Greece", "europe", 39.07, 21.82, "ATH", ["greece", "grecj*", "griechenland", "graikij*", "grecia", "zakynthos", "zakintos", "santorini"]),
    ("antalya", "Turkish Riviera", "Turkey", "europe", 36.90, 30.70, "AYT", ["antalya", "antalia", "antalij*", "turcj*", "türkei", "turkij*", "alanya", "bodrum", "dalaman"]),
    ("cyprus", "Cyprus", "Cyprus", "europe", 34.77, 32.42, "PFO", ["cyprus", "cypr*", "zypern", "kipr*", "paphos", "pafos", "larnaca", "larnaka"]),
    ("mallorca", "Mallorca", "Spain", "europe", 39.57, 2.65, "PMI", ["mallorca", "majork*", "majorka", "malljork*", "ibiza", "menorca", "minork*"]),
    ("sardinia", "Sardinia", "Italy", "europe", 40.12, 9.01, "OLB", ["sardinia", "sardyni*", "sardinien", "sardegna", "cagliari"]),
    ("sicily", "Sicily", "Italy", "europe", 37.6, 14.0, "CTA", ["sicily", "sycyli*", "sizilien", "sicilia", "catania", "palermo"]),
    ("tropea", "Calabria", "Italy", "europe", 38.68, 15.90, "SUF", ["tropea", "calabria", "kalabri*"]),
    ("porto", "Porto", "Portugal", "europe", 41.15, -8.61, "OPO", ["porto"]),
    ("algarve", "Algarve", "Portugal", "europe", 37.02, -7.93, "FAO", ["algarve", "faro"]),
    ("malta", "Malta", "Malta", "europe", 35.90, 14.51, "MLA", ["malta", "malcie", "maltę"]),
    ("lapland", "Lapland", "Finland", "europe", 67.80, 24.80, "KTT", ["lapland", "laponi*", "lappland", "levi", "rovaniemi", "kittilä", "kittila"]),
    ("iceland", "Iceland", "Iceland", "europe", 64.15, -21.94, "KEF", ["iceland", "islandi*", "islanda", "reykjavik", "reykjavík"]),
    ("albania", "Albania", "Albania", "europe", 41.33, 19.82, "TIA", ["albania", "albani*", "albanien", "tirana"]),
    ("montenegro", "Montenegro", "Montenegro", "europe", 42.43, 19.26, "TGD", ["montenegro", "czarnogór*", "juodkalnij*"]),
    ("croatia", "Croatia", "Croatia", "europe", 43.51, 16.44, "SPU", ["croatia", "chorwacj*", "kroatien", "kroatij*", "dubrovnik"]),
    ("bulgaria", "Bulgaria", "Bulgaria", "europe", 42.7, 27.7, "BOJ", ["bulgaria", "bułgari*", "bulgarien", "bulgarij*", "burgas", "warna", "varna"]),
    ("norway", "Norwegian fjords", "Norway", "europe", 60.39, 5.32, "BGO", ["fjord*", "bergen", "tromsø", "tromso", "lofoten"]),
    ("austria_alps", "Austrian Alps", "Austria", "europe", 47.27, 11.40, "INN", ["innsbruck", "tirol", "tyrol*", "austri*"]),
]

EUROPE_COUNTRIES = {
    "LT", "LV", "EE", "PL", "AT", "SK", "HU", "CZ", "DE", "NL", "BE", "DK", "SE", "FI", "NO", "IT", "FR",
    "GB", "ES", "PT", "GR", "IE", "CH", "TR",
}


@dataclass
class Place:
    key: str
    name: str
    country: str
    region: str
    lat: float
    lon: float
    iata: str = ""
    is_origin: bool = False
    priority: int = 3
    aliases: list[str] = field(default_factory=list)


def _alias_regex(alias: str) -> str:
    stem = alias.endswith("*")
    a = alias.rstrip("*")
    body = re.escape(a).replace(r"\ ", r"\s+")
    tail = r"[a-ząćęłńóśźżäöüßėįšųūž]{0,4}" if stem else ""
    return rf"(?<![\w]){body}{tail}(?![\w])"


ORIGIN_PLACES: dict[str, Place] = {}
for iata, city, cc, lat, lon, prio, aliases in ORIGINS:
    ORIGIN_PLACES[iata] = Place(iata, city, cc, "europe", lat, lon, iata, True, prio, aliases + [city.lower()])

DEST_PLACES: dict[str, Place] = {}
for key, name, country, region, lat, lon, iata, aliases in DESTINATIONS:
    DEST_PLACES[key] = Place(key, name, country, region, lat, lon, iata, False, 3, aliases)

IATA_TO_DEST = {p.iata: p for p in DEST_PLACES.values() if p.iata}


def _compile(places: dict[str, Place]):
    out = []
    for p in places.values():
        for a in sorted(set(p.aliases), key=len, reverse=True):
            out.append((re.compile(_alias_regex(a), re.IGNORECASE), p, len(a)))
    out.sort(key=lambda t: -t[2])
    return out


_ORIGIN_RX = _compile(ORIGIN_PLACES)
_DEST_RX = _compile(DEST_PLACES)


def find_places(text: str, kind: str = "dest") -> list[tuple[int, int, Place]]:
    """Return non-overlapping (start, end, place) matches, longest alias wins."""
    rx = _DEST_RX if kind == "dest" else _ORIGIN_RX
    taken: list[tuple[int, int]] = []
    found: list[tuple[int, int, Place]] = []
    for pattern, place, _ in rx:
        for m in pattern.finditer(text):
            s, e = m.span()
            if any(s < te and e > ts for ts, te in taken):
                continue
            taken.append((s, e))
            found.append((s, e, place))
    found.sort(key=lambda t: t[0])
    return found
