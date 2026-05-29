"""Callsign-prefix -> continent mapping.

The goal is *continent-level* accuracy (NA, SA, EU, AF, AS, OC), which is all the
band-recommendation logic needs. The table is intentionally kept in its own
module and uses longest-prefix matching so it is easy to extend: add a more
specific prefix and it automatically wins over a shorter one.

Continent codes: NA, SA, EU, AF, AS, OC.
"""

from __future__ import annotations

from .callsign import location_token

CONTINENTS = ("NA", "SA", "EU", "AF", "AS", "OC")
UNKNOWN_CONTINENT = "?"

# prefix -> continent. Order does not matter; matching uses the longest prefix.
# This is a pragmatic table covering the prefixes that actually show up as RBN
# skimmers (very dense in NA/EU) plus broad country coverage elsewhere. Extend
# freely; longer/more-specific keys override shorter ones automatically.
PREFIX_CONTINENT: dict[str, str] = {}


def _add(continent: str, *prefixes: str) -> None:
    for p in prefixes:
        PREFIX_CONTINENT[p.upper()] = continent


# --- North America ---------------------------------------------------------
# USA. Single-letter K/N/W are NA, but the US Pacific (KH/NH/WH/AH) is OC and
# must override via longer prefix.
_add("NA", "K", "N", "W")
_add("NA", "AA", "AB", "AC", "AD", "AE", "AF", "AG", "AI", "AJ", "AK", "AL")
_add("OC", "AH", "KH", "NH", "WH")  # US Pacific (Hawaii, Guam, ...)
_add("NA", "KL", "NL", "WL", "AL")  # Alaska
_add("NA", "KP", "NP", "WP")  # Puerto Rico / US Virgin Is. (NA)
# Canada
_add("NA", "VE", "VA", "VO", "VY", "CY", "CZ", "VB", "VC", "VD", "VF", "VG", "VX")
# Mexico
_add("NA", "XE", "XF", "XA", "XB", "XC", "XD", "XG", "XH", "XI", "4A", "4B", "4C", "6D", "6E", "6F", "6G", "6H", "6I", "6J")
# Central America / Caribbean (all NA)
_add("NA", "TG", "TD")  # Guatemala
_add("NA", "YS")  # El Salvador
_add("NA", "HR", "HQ")  # Honduras
_add("NA", "YN", "HT")  # Nicaragua
_add("NA", "TI", "TE")  # Costa Rica
_add("NA", "HP", "HO", "H3", "H8", "H9", "3E", "3F")  # Panama
_add("NA", "V3")  # Belize
_add("NA", "CO", "CM", "CL", "T4")  # Cuba
_add("NA", "HI", "HH")  # Dominican Rep / Haiti
_add("NA", "6Y")  # Jamaica
_add("NA", "C6")  # Bahamas
_add("NA", "VP9")  # Bermuda
_add("NA", "ZF")  # Cayman
_add("NA", "8P")  # Barbados
_add("NA", "J3", "J6", "J7", "J8", "V4", "VP2", "FG", "FM", "FS", "PJ", "FJ")  # Lesser Antilles

# --- South America ---------------------------------------------------------
_add("SA", "PY", "PP", "PR", "PS", "PT", "PU", "PV", "PW", "PX", "ZV", "ZW", "ZX", "ZY", "ZZ")  # Brazil
_add("SA", "LU", "LO", "LP", "LQ", "LR", "LS", "LT", "LV", "LW", "AY", "AZ", "L2")  # Argentina
_add("SA", "CE", "CA", "CB", "CC", "CD", "XQ", "XR", "3G")  # Chile
_add("SA", "HK", "HJ", "5J", "5K")  # Colombia
_add("SA", "YV", "YW", "YX", "YY", "4M")  # Venezuela
_add("SA", "OA", "OB", "OC", "4T")  # Peru
_add("SA", "HC", "HD")  # Ecuador
_add("SA", "CP")  # Bolivia
_add("SA", "ZP")  # Paraguay
_add("SA", "CX", "CV", "CW")  # Uruguay
_add("SA", "8R")  # Guyana
_add("SA", "PZ")  # Suriname
_add("SA", "FY")  # French Guiana
_add("SA", "HC8")  # Galapagos (still SA region)

# --- Europe ----------------------------------------------------------------
_add("EU", "G", "M", "2E", "2M", "2W", "2I", "2D", "2J", "2U", "GM", "GW", "GI", "GD", "GJ", "GU", "MM", "MW", "MI", "MD", "MJ", "MU")  # UK & crown
_add("EU", "EI", "EJ")  # Ireland
_add("EU", "DL", "DA", "DB", "DC", "DD", "DF", "DG", "DH", "DJ", "DK", "DM", "DO", "DP", "DQ", "DR")  # Germany
_add("EU", "F", "TM", "TK", "TV", "TW", "TH", "TP", "TQ")  # France (TK=Corsica still EU)
_add("EU", "I", "IK", "IZ", "IW", "IN", "IO", "IQ", "IR", "IS", "IT", "IU", "IV", "II")  # Italy
_add("EU", "EA", "EB", "EC", "ED", "EE", "EF", "EG", "EH", "AM", "AN", "AO")  # Spain (mainland)
_add("AF", "EA8", "EB8", "EC8", "ED8", "EE8", "EF8", "EG8", "EH8")  # Canary Is.
_add("AF", "EA9", "EB9", "EC9", "ED9", "EE9", "EF9", "EG9", "EH9")  # Ceuta & Melilla
_add("EU", "CT", "CR", "CS", "CQ")  # Portugal
_add("AF", "CT3", "CR3", "CS3", "CQ3", "CT9")  # Madeira
_add("EU", "PA", "PB", "PC", "PD", "PE", "PF", "PG", "PH", "PI")  # Netherlands
_add("EU", "ON", "OO", "OP", "OQ", "OR", "OS", "OT")  # Belgium
_add("EU", "LX")  # Luxembourg
_add("EU", "HB", "HE")  # Switzerland (HB0=Liechtenstein still EU)
_add("EU", "OE")  # Austria
_add("EU", "SM", "SA", "SB", "SC", "SD", "SE", "SF", "SG", "SH", "SI", "SJ", "SK", "SL", "7S", "8S")  # Sweden
_add("EU", "LA", "LB", "LC", "LD", "LE", "LF", "LG", "LH", "LI", "LJ", "LK", "LL", "LM", "LN")  # Norway
_add("EU", "OZ", "OU", "OV", "OW", "5P", "5Q")  # Denmark
_add("EU", "OH", "OF", "OG", "OI", "OJ")  # Finland
_add("EU", "OY")  # Faroe
_add("EU", "TF")  # Iceland
_add("EU", "SP", "SN", "SO", "SQ", "SR", "3Z", "HF")  # Poland
_add("EU", "OK", "OL")  # Czechia
_add("EU", "OM")  # Slovakia
_add("EU", "HA", "HG")  # Hungary
_add("EU", "S5")  # Slovenia
_add("EU", "9A")  # Croatia
_add("EU", "E7")  # Bosnia
_add("EU", "YU", "YT", "YZ")  # Serbia
_add("EU", "Z3")  # North Macedonia
_add("EU", "ZA")  # Albania
_add("EU", "4O")  # Montenegro
_add("EU", "Z6")  # Kosovo
_add("EU", "LZ")  # Bulgaria
_add("EU", "YO", "YP", "YQ", "YR")  # Romania
_add("EU", "ER")  # Moldova
_add("EU", "UR", "US", "UT", "UU", "UV", "UW", "UX", "UY", "UZ", "EM", "EN", "EO")  # Ukraine
_add("EU", "EU", "EV", "EW")  # Belarus
_add("EU", "LY")  # Lithuania
_add("EU", "YL")  # Latvia
_add("EU", "ES")  # Estonia
_add("EU", "SV", "SW", "SX", "SY", "SZ", "J4")  # Greece
_add("EU", "9H")  # Malta
_add("EU", "5B", "C4", "P3", "H2")  # Cyprus (treated EU for our purposes)
_add("EU", "TA1")  # European Turkey (Istanbul) -- rough
_add("EU", "T7")  # San Marino
_add("EU", "9X")  # (placeholder removed below) -- intentionally not EU
del PREFIX_CONTINENT["9X"]  # 9X = Rwanda, set under AF
_add("EU", "T9")  # historic Bosnia
_add("EU", "OE")  # Austria (dup safe)
_add("EU", "3A")  # Monaco
_add("EU", "C3")  # Andorra
_add("EU", "EA6", "EB6", "EC6", "ED6", "EF6", "EG6", "EH6")  # Balearic Is. (EU)
_add("EU", "IS0", "IM0", "IW0")  # Sardinia (EU)
# European Russia (UA/RA ... 1-7 districts) -- Asiatic Russia handled with 0/8/9
_add("EU", "UA", "UB", "UC", "UD", "UE", "UF", "UG", "UH", "UI", "RA", "RB", "RC", "RD", "RE", "RF", "RG", "RH", "RI", "RJ", "RK", "RL", "RM", "RN", "RO", "RP", "RQ", "RR", "RS", "RT", "RU", "RV", "RW", "RX", "RY", "RZ", "R")
_add("AS", "UA0", "UA8", "UA9", "RA0", "RA8", "RA9", "R0", "R8", "R9")  # Asiatic Russia
_add("AS", "UA9", "UA0")  # (dup safe)
# Kaliningrad (EU)
_add("EU", "UA2", "RA2", "R2F", "R2K")

# --- Asia ------------------------------------------------------------------
_add("AS", "JA", "JE", "JF", "JG", "JH", "JI", "JJ", "JK", "JL", "JM", "JN", "JO", "JP", "JQ", "JR", "JS", "7J", "7K", "7L", "7M", "7N", "8J", "8N")  # Japan
_add("AS", "BY", "BA", "BD", "BG", "BH", "BI", "BT", "B")  # China
_add("AS", "BV")  # Taiwan
_add("AS", "VR", "VR2")  # Hong Kong
_add("AS", "XX9")  # Macau
_add("AS", "HL", "DS", "DT", "6K", "6L", "6M", "6N", "D7", "D8", "D9")  # South Korea
_add("AS", "P5")  # North Korea
_add("AS", "VU", "AT", "AU", "AV", "AW", "8T", "8U", "8V", "8W", "8X", "8Y")  # India
_add("AS", "AP", "AQ", "AR", "AS")  # Pakistan
_add("AS", "S2")  # Bangladesh
_add("AS", "4S")  # Sri Lanka
_add("AS", "EP", "EQ")  # Iran
_add("AS", "YK")  # Syria
_add("AS", "YI")  # Iraq
_add("AS", "9K")  # Kuwait
_add("AS", "A4")  # Oman
_add("AS", "A6")  # UAE
_add("AS", "A7")  # Qatar
_add("AS", "A9")  # Bahrain
_add("AS", "HZ", "7Z", "8Z")  # Saudi Arabia
_add("AS", "4X", "4Z")  # Israel
_add("AS", "JY")  # Jordan
_add("AS", "OD")  # Lebanon
_add("AS", "TA", "TB", "TC", "YM")  # Turkey (Asiatic)
_add("AS", "EK")  # Armenia
_add("AS", "4J", "4K")  # Azerbaijan
_add("AS", "4L")  # Georgia
_add("AS", "UN", "UO", "UP", "UQ")  # Kazakhstan
_add("AS", "EX")  # Kyrgyzstan
_add("AS", "EY")  # Tajikistan
_add("AS", "EZ")  # Turkmenistan
_add("AS", "UK", "UJ", "UM")  # Uzbekistan
_add("AS", "HS", "E2")  # Thailand
_add("AS", "XV", "3W")  # Vietnam
_add("AS", "XU")  # Cambodia
_add("AS", "XW")  # Laos
_add("AS", "XY", "XZ")  # Myanmar
_add("AS", "9M", "9W")  # Malaysia
_add("AS", "9V")  # Singapore
_add("AS", "V8")  # Brunei
_add("AS", "DU", "DV", "DW", "DX", "DZ", "4D", "4E", "4F", "4G", "4H", "4I")  # Philippines

# --- Oceania ---------------------------------------------------------------
_add("OC", "VK", "AX", "VH", "VI", "VJ", "VL", "VM", "VN", "VZ")  # Australia
_add("OC", "ZL", "ZK", "ZM", "E5", "E6")  # New Zealand & dependencies
_add("OC", "YB", "YC", "YD", "YE", "YF", "YG", "YH", "7A", "7B", "7C", "7D", "7E", "7F", "7G", "7H", "7I", "8A", "8B", "8C", "8D", "8E", "8F", "8G", "8H", "8I")  # Indonesia
_add("OC", "P2")  # Papua New Guinea
_add("OC", "DU0")  # (not used) -- keep Philippines as AS
del PREFIX_CONTINENT["DU0"]
_add("OC", "FK")  # New Caledonia
_add("OC", "FO")  # French Polynesia
_add("OC", "FW")  # Wallis & Futuna
_add("OC", "3D2")  # Fiji
_add("OC", "5W")  # Samoa
_add("OC", "A3")  # Tonga
_add("OC", "T2")  # Tuvalu
_add("OC", "T3")  # Kiribati
_add("OC", "T8")  # Palau
_add("OC", "V6")  # Micronesia
_add("OC", "V7")  # Marshall Is.
_add("OC", "C2")  # Nauru
_add("OC", "H4")  # Solomon Is.
_add("OC", "YJ")  # Vanuatu
_add("OC", "KH", "AH", "NH", "WH")  # US Pacific (dup safe)

# --- Africa ----------------------------------------------------------------
_add("AF", "ZS", "ZR", "ZT", "ZU", "ZS8", "V5")  # South Africa / Namibia
_add("AF", "5N", "5O")  # Nigeria
_add("AF", "5R", "5S")  # Madagascar
_add("AF", "5H", "5I")  # Tanzania
_add("AF", "5X")  # Uganda
_add("AF", "5Y", "5Z")  # Kenya
_add("AF", "9G")  # Ghana
_add("AF", "9J")  # Zambia
_add("AF", "9L")  # Sierra Leone
_add("AF", "9Q", "9R", "9S", "9T")  # DR Congo
_add("AF", "9U")  # Burundi
_add("AF", "9X")  # Rwanda
_add("AF", "C5")  # The Gambia
_add("AF", "C9")  # Mozambique
_add("AF", "D2", "D3")  # Angola
_add("AF", "D4")  # Cape Verde
_add("AF", "EL")  # Liberia
_add("AF", "ET")  # Ethiopia
_add("AF", "J5")  # Guinea-Bissau
_add("AF", "Z2")  # Zimbabwe
_add("AF", "Z8")  # South Sudan
_add("AF", "TR")  # Gabon
_add("AF", "TT")  # Chad
_add("AF", "TU")  # Cote d'Ivoire
_add("AF", "TY")  # Benin
_add("AF", "TZ")  # Mali
_add("AF", "TJ")  # Cameroon
_add("AF", "TL")  # Central African Rep
_add("AF", "TN")  # Congo
_add("AF", "3B6", "3B7", "3B8", "3B9")  # Mauritius / Agalega / Rodrigues
_add("AF", "3C")  # Equatorial Guinea
_add("AF", "3V")  # Tunisia
_add("AF", "3X")  # Guinea
_add("AF", "6W")  # Senegal
_add("AF", "7P")  # Lesotho
_add("AF", "7Q")  # Malawi
_add("AF", "7X")  # Algeria
_add("AF", "8Q")  # Maldives  -- actually AS; correct below
del PREFIX_CONTINENT["8Q"]
_add("AS", "8Q")  # Maldives (AS)
_add("AF", "A2")  # Botswana
_add("AF", "C8")  # Mozambique alt
_add("AF", "CN")  # Morocco
_add("AF", "SU")  # Egypt (AF)
_add("AF", "ST")  # Sudan
_add("AF", "5A")  # Libya
_add("AF", "5T")  # Mauritania
_add("AF", "5U")  # Niger
_add("AF", "5V")  # Togo
_add("AF", "6V")  # Senegal alt
_add("AF", "V5")  # Namibia (dup safe)
_add("AF", "FR", "FH", "FT")  # Reunion / Mayotte / French sub-Antarctic
_add("AF", "S9")  # Sao Tome
_add("AF", "J2")  # Djibouti
_add("AF", "T5")  # Somalia


def continent_for(call: str) -> str:
    """Return the continent code for ``call``, or ``"?"`` if unknown.

    Uses the operating-location token (handles ``EA8/G4ABC`` -> AF) and matches
    the longest prefix present in the table.
    """
    token = location_token(call)
    if not token:
        return UNKNOWN_CONTINENT
    # Longest-prefix match: try progressively shorter leading substrings.
    for n in range(min(4, len(token)), 0, -1):
        cont = PREFIX_CONTINENT.get(token[:n])
        if cont is not None:
            return cont
    return UNKNOWN_CONTINENT
