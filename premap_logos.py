#!/usr/bin/env python3
"""premap_logos.py - Download + pre-map a large set of brand logos to Wikimedia Commons.

For every brand in BRANDS (1000+ curated names across industries), it:
  1. searches Wikimedia Commons (action=query&list=search, namespace 6 = File)
     for the brand's logo,
  2. picks the best candidate (prefers SVG logo files, avoids ASCII/owner
     variants),
  3. downloads the Commons-rasterized 512px PNG thumbnail,
  4. saves it to cast_refs/logos/<safe>.png,
  5. records the resolved Commons file title in OFFICIAL_LOGOS_MANIFEST.json
     so the pipeline can fetch it directly (cache-first) on future runs.

Re-run anytime to fill gaps:  python premap_logos.py
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
LOGO_DIR = PROJECT_DIR / "cast_refs" / "logos"
MANIFEST = LOGO_DIR / "OFFICIAL_LOGOS_MANIFEST.json"

UA = "SplitNode/1.1 (ads.doctor.melbourne@gmail.com)"

# A broad curated set of well-known brands likely to appear in "beat the
# system" / business / tech stories. Each is auto-resolved to its Commons logo.
BRANDS = [
    # --- AI / tech / software ---
    "OpenAI", "Google", "Gemini", "Anthropic", "Meta", "Facebook", "Microsoft",
    "Copilot", "xAI", "Grok", "Mistral", "DeepSeek", "Stability AI",
    "Midjourney", "Runway", "Hugging Face", "ElevenLabs", "Perplexity",
    "Adobe", "Firefly", "Apple", "Amazon", "AWS", "NVIDIA", "Intel", "AMD",
    "IBM", "Oracle", "SAP", "Salesforce", "ServiceNow", "Snowflake",
    "Databricks", "Palantir", "CrowdStrike", "Cloudflare", "Akamai", "GitHub",
    "GitLab", "JetBrains", "Atlassian", "Slack", "Zoom", "Teams", "Notion",
    "Dropbox", "Box", "Docker", "Kubernetes", "Linux", "Ubuntu", "Red Hat",
    "Canonical", "VMware", "Nutanix", "Qualcomm", "Broadcom", "Micron", "TSMC",
    "Samsung", "Sony", "LG", "Xiaomi", "Huawei", "OnePlus", "Oppo", "Vivo",
    "Nokia", "Ericsson", "Cisco", "Juniper", "Palo Alto Networks", "Fortinet",
    "Splunk", "Datadog", "New Relic", "HashiCorp", "MongoDB", "Redis",
    "PostgreSQL", "MySQL", "SQLite", "Elastic", "Confluent", "Kafka",
    "Apache", "Pinecone", "Weaviate", "Milvus", "Qdrant", "Chroma",
    # --- social / internet ---
    "Twitter", "X", "LinkedIn", "YouTube", "TikTok", "Instagram", "Snapchat",
    "Reddit", "Pinterest", "Discord", "Telegram", "WhatsApp", "Signal",
    "Twitch", "OnlyFans", "Patreon", "Substack", "Medium", "WordPress",
    "Shopify", "Etsy", "eBay", "Alibaba", "JD.com", "MercadoLibre", "Rakuten",
    "PayPal", "Stripe", "Square", "Block", "Venmo", "Klarna", "Affirm",
    "Revolut", "Wise", "Robinhood", "Coinbase", "Binance", "Kraken",
    "Gemini Exchange", "Circle", "Tether", "Ripple", "Ethereum", "Solana",
    "Bitcoin", "Cardano", "Polkadot", "Chainlink",
    # --- automotive ---
    "Tesla", "Ford", "GM", "Chevrolet", "GMC", "Cadillac", "Buick",
    "Chrysler", "Dodge", "Jeep", "Ram", "Toyota", "Lexus", "Honda", "Acura",
    "Nissan", "Infiniti", "Mazda", "Subaru", "Mitsubishi", "Hyundai", "Kia",
    "Volkswagen", "Audi", "Porsche", "BMW", "Mini", "Mercedes-Benz",
    "Ferrari", "Lamborghini", "McLaren", "Aston Martin", "Bentley", "Rolls-Royce",
    "Jaguar", "Land Rover", "Volvo", "Polestar", "Rivian", "Lucid",
    "NIO", "XPeng", "BYD", "Geely", "Peugeot", "Citroen", "Renault",
    "Fiat", "Alfa Romeo", "Lancia", "Dacia", "SEAT", "Skoda",
    # --- banking / finance ---
    "JPMorgan", "Chase", "Bank of America", "Wells Fargo", "Citigroup",
    "Goldman Sachs", "Morgan Stanley", "HSBC", "Barclays", "Lloyds", "NatWest",
    "Deutsche Bank", "UBS", "Credit Suisse", "BNP Paribas", "Société Générale",
    "Santander", "BBVA", "ING", "ABN AMRO", "Rabobank", "Nordea", "SEB",
    "Swedbank", "Danske Bank", "Standard Chartered", "DBS", "OCBC", "UOB",
    "Commonwealth Bank", "Westpac", "NAB", "ANZ", "RBC", "TD Bank", "Scotiabank",
    "BMO", "CIBC", "Itaú", "Banco Santander", "Caixa", "Mizuho", "Nomura",
    "Sberbank", "VTB", "ICBC", "China Construction Bank", "Agricultural Bank of China",
    "Visa", "Mastercard", "American Express", "Discover",
    # --- food / beverage ---
    "Coca-Cola", "Pepsi", "Mountain Dew", "Dr Pepper", "7Up", "Red Bull",
    "Monster Energy", "Gatorade", "Starbucks", "Dunkin", "Tim Hortons",
    "Costa Coffee", "Nespresso", "Nescafé", "Keurig", "Celsius", "Lipton",
    "Nestlé", "Mars", "Hershey", "Cadbury", "Lindt", "Ferrero", "KitKat",
    "Snickers", "M&M's", "Oreo", "Ritz", "Lay's", "Pringles", "Doritos",
    "Cheetos", "Frito-Lay", "Kellogg's", "General Mills", "PepsiCo", "Quaker",
    "Mondelez", "Danone", "Yoplait", "Chobani", "Oikos", "McDonald's",
    "Burger King", "Wendy's", "Subway", "Taco Bell", "KFC", "Pizza Hut",
    "Domino's", "Papa John's", "Chipotle", "Five Guys", "In-N-Out", "Shake Shack",
    "Popeyes", "Chick-fil-A", "Dairy Queen", "Sonic", "Arby's", "White Castle",
    "Heinz", "Kraft", "Kraft Heinz", "Campbell's", "Progresso", "Barilla",
    "Del Monte", "Dole", "Chiquita", "Tyson", "Perdue", "Smithfield",
    # --- retail / apparel / footwear ---
    "Walmart", "Costco", "Target", "Kroger", "Albertsons", "Safeway", "Whole Foods",
    "Trader Joe's", "Aldi", "Lidl", "Tesco", "Sainsbury's", "Asda", "Morrisons",
    "Carrefour", "Auchan", "Loblaws", "Metro", "7-Eleven", "Circle K",
    "Nike", "Adidas", "Puma", "Reebok", "New Balance", "Under Armour", "Lululemon",
    "The North Face", "Patagonia", "Columbia", "Levi's", "Wrangler", "Diesel",
    "Gucci", "Prada", "Louis Vuitton", "Chanel", "Hermès", "Dior", "Burberry",
    "Versace", "Armani", "Zara", "H&M", "Uniqlo", "Gap", "Old Navy", "Banana Republic",
    "Forever 21", "Victoria's Secret", "Sephora", "Ulta", "L'Oréal",
    # --- airlines / transport ---
    "Delta", "United Airlines", "American Airlines", "Southwest", "JetBlue",
    "Alaska Airlines", "Spirit Airlines", "Frontier", "Allegiant", "Hawaiian Airlines",
    "British Airways", "Air France", "Lufthansa", "KLM", "Iberia", "Ryanair",
    "EasyJet", "Wizz Air", "Turkish Airlines", "Emirates", "Qatar Airways",
    "Etihad", "Singapore Airlines", "Cathay Pacific", "Qantas", "Air New Zealand",
    "Japan Airlines", "ANA", "Korean Air", "Air Canada", "Aeromexico",
    "Uber", "Lyft", "DoorDash", "Postmates", "Instacart", "Grubhub",
    "FedEx", "UPS", "DHL", "USPS", "DPD", "PostNL", "DP World", "Maersk",
    "MSC", "CMA CGM", "CSX", "Norfolk Southern", "Union Pacific",
    # --- media / entertainment ---
    "Disney", "Walt Disney", "Marvel", "Star Wars", "Pixar", "Universal",
    "Paramount", "Warner Bros", "Warner Bros Discovery", "Sony Pictures",
    "Netflix", "Hulu", "HBO", "Max", "Prime Video", "Apple TV", "Disney+",
    "Peacock", "Paramount+", "Showtime", "AMC", "Cinemark", "Regal", "IMAX",
    "NBC", "CBS", "ABC", "CNN", "Fox News", "BBC", "Sky", "ESPN", "Fox Sports",
    "NFL", "NBA", "MLB", "NHL", "FIFA", "NASCAR", "Formula 1", "MotoGP",
    "Spotify", "Apple Music", "Pandora", "SoundCloud", "Bandcamp", "Tidal",
    "SiriusXM", "YouTube Music", "Twitch", "Vimeo", "Dailymotion",
    # --- gaming ---
    "Nintendo", "PlayStation", "Xbox", "Sega", "Atari", "Electronic Arts",
    "EA", "Activision", "Blizzard", "Ubisoft", "Epic Games", "Steam", "Valve",
    "Rockstar", "Take-Two", "2K", "Square Enix", "Capcom", "Konami", "Bandai Namco",
    "NetEase", "Tencent", "Riot Games", "Roblox", "Unity", "Unreal Engine",
    # --- pharma / health ---
    "Pfizer", "Moderna", "Johnson & Johnson", "Merck", "AstraZeneca",
    "Novartis", "Roche", "GlaxoSmithKline", "GSK", "Sanofi", "Eli Lilly",
    "Bristol Myers Squibb", "AbbVie", "Gilead", "Amgen", "Bayer", "Biogen",
    "Regeneron", "Vertex", "Cigna", "UnitedHealth", "Aetna", "Humana",
    "CVS Health", "Walgreens", "Rite Aid", "Mayo Clinic", "Cleveland Clinic",
    # --- energy / industrial ---
    "ExxonMobil", "Chevron", "Shell", "BP", "TotalEnergies", "Eni", "Equinor",
    "ConocoPhillips", "Schlumberger", "Halliburton", "Baker Hughes", "Siemens",
    "GE", "General Electric", "Honeywell", "3M", "Caterpillar", "Deere",
    "John Deere", "Cummins", "Volvo Group", "PACCAR", "Boeing", "Airbus",
    "Lockheed Martin", "Northrop Grumman", "Raytheon", "General Dynamics",
    "SpaceX", "Blue Origin", "Virgin Galactic", "Rocket Lab", "ULA",
    "NextEra Energy", "Duke Energy", "Southern Company", "Brookfield",
    # --- telecom ---
    "AT&T", "Verizon", "T-Mobile", "Sprint", "Vodafone", "Telenor", "Telstra",
    "Optus", "Rogers", "Bell Canada", "Telus", "Orange", "Deutsche Telekom",
    "Vodafone Idea", "Airtel", "Jio", "Vivo", "KDDI", "SoftBank", "NTT",
    # --- insurance ---
    "Geico", "Progressive", "State Farm", "Allstate", "Liberty Mutual",
    "USAA", "Farmers", "Nationwide", "AIG", "Chubb", "Zurich", "Allianz",
    "AXA", "Munich Re", "Swiss Re", "Berkshire Hathaway",
    # --- hotels / hospitality ---
    "Marriott", "Hilton", "Hyatt", "Four Seasons", "Ritz-Carlton", "Sheraton",
    "Westin", "Waldorf Astoria", "InterContinental", "Holiday Inn", "Best Western",
    "Accor", "Airbnb", "Booking.com", "Expedia", "TripAdvisor", "Kayak",
    "Hostelworld", "VRBO",
    # --- beauty / consumer ---
    "Procter & Gamble", "P&G", "Unilever", "Colgate", "Crest", "Oral-B",
    "Gillette", "Dove", "Pantene", "Head & Shoulders", "Tide", "Ariel",
    "Persil", "Charmin", "Kleenex", "Scott", "Bounty", "Puffs",
    "Johnson & Johnson Consumer", "Neutrogena", "Aveeno", "Cetaphil",
    # --- other notable ---
    "Disneyland", "Walt Disney World", "Universal Studios", "LEGO", "Mattel",
    "Hasbro", "Barbie", "Hot Wheels", "Fisher-Price", "Play-Doh",
    "IKEA", "Wayfair", "Home Depot", "Lowe's", "Bunnings", "Toolstation",
    "Screwfix", "AutoZone", "O'Reilly", "Advance Auto Parts",
    "Staples", "Office Depot", "Best Buy", "Micro Center", "Fry's",
    "Western Union", "MoneyGram", "Xoom", "Remitly", "Wise Money",
    "Global Payments", "Fiserv", "Adyen", "Braintree", "Shopify Payments",
    "Squarespace", "Wix", "Webflow", "Framer", "Figma", "Canva", "Adobe Creative Cloud",
    "Asana", "Monday.com", "Trello", "Jira", "Confluence", "Basecamp",
    "ZoomInfo", "HubSpot", "Marketo", "Mailchimp", "Constant Contact",
    "SendGrid", "Twilio", "Intercom", "Zendesk", "Freshworks", "Kustomer",
    "Snowflake", "Cloudera", "Teradata", "Informatica", "Talend",
    # --- country / government-adjacent (state-owned / quasi) ---
    "NASA", "ESA", "DARPA", "CIA", "FBI", "NSA", "US Treasury", "Federal Reserve",
    "European Central Bank", "Bank of England", "IMF", "World Bank", "World Health Organization",
    "United Nations", "NATO", "EU", "WHO", "UNESCO",
    # --- airlines continued / rail / shipping ---
    "Ryanair Holdings", "Aer Lingus", "Alitalia", "TAP Air Portugal", "SAS",
    "Finnair", "Norwegian Air", "Icelandair", "Air France-KLM", "Vietnam Airlines",
    "Thai Airways", "Malaysia Airlines", "Philippine Airlines", "Garuda Indonesia",
    "Air India", "Vistara", "IndiGo", "SpiceJet", "GoAir", "Akasa Air",
    "Southwest Airlines", "American Eagle", "Breeze Airways", "Avelo", "Sun Country",
    "Copa Airlines", "Avianca", "LATAM", "Gol", "Azul", "Embraer",
    "Amtrak", "Eurostar", "Virgin Trains", "Thalys", "Deutsche Bahn", "SNCF",
    "Renfe", "Trenitalia", "JR East", "JR West", "Shinkansen", "MTR", "SMRT",
    "MTA", "London Underground", "BART", "Caltrain", "Amtrak California",
    # --- shipping / logistics continued ---
    "Kuehne+Nagel", "DSV", "Expeditors", "XPO", "CH Robinson", "C.H. Robinson",
    "J.B. Hunt", "Schneider National", "Werner Enterprises", "Swift", "Knight-Swift",
    "Old Dominion", "Saia", "Estes", "ABF Freight", "Yellow Corp", "Con-way",
    "FedEx Freight", "UPS Freight", "XPO Logistics", "Flexport", "ShipBob",
    "ShipMonk", "Delhivery", "Ecom Express", "Blue Dart",
    # --- retail continued ---
    "Nordstrom", "Macy's", "Bloomingdale's", "Kohl's", "JCPenney", "Sears",
    "Dillard's", "Belk", "Neiman Marcus", "Saks Fifth Avenue", "Barneys",
    "T.J. Maxx", "Marshalls", "HomeGoods", "Burlington", "Ross Stores",
    "Dollar Tree", "Dollar General", "Family Dollar", "Five Below", "Big Lots",
    "Ollie's", "99 Cents Only", "Rite Aid", "Duane Reade", "Longs Drugs",
    "Boots", "Superdrug", "CVS", "Walgreens Boots Alliance", "Lloyds Pharmacy",
    "Tesco Express", "Co-op Food", "Waitrose", "Marks & Spencer", "John Lewis",
    "Debenhams", "House of Fraser", "Harrods", "Selfridges", "Fortnum & Mason",
    "IKEA", "Kinokuniya", "Tsutaya", "Daiei", "Ito-Yokado", "AEON",
    "Giant", "Safeway Australia", "Coles", "Woolworths", "Aldi Australia",
    "Bunnings", "Kmart Australia", "Target Australia", "Big W", "Chemist Warehouse",
    # --- food/beverage continued ---
    "PepsiCo Foods", "Frito-Lay North America", "Kraft Foods", "Nabisco",
    "Keebler", "Pepperidge Farm", "Otis Spunkmeyer", "Hostess", "Little Debbie",
    "Entenmann's", "Thomas'", "Arnold", "Sara Lee", "Mrs. Butterworth's",
    "Aunt Jemima", "Pancake Mix", "Log Cabin", "Karo", "Pillsbury", "Betty Crocker",
    "Duncan Hines", "Hamburger Helper", "Cheerios", "Wheaties", "Lucky Charms",
    "Trix", "Froot Loops", "Cap'n Crunch", "Frosted Flakes", "Special K",
    "Rice Krispies", "Pop-Tarts", "Eggo", "Kashi", "Nature Valley", "Quaker Oats",
    "Ghirardelli", "Godiva", "Russell Stover", "See's", "Fannie May", "Whitman's",
    "Russell Stover Candies", "Hershey's Kisses", "Reese's", "York Peppermint",
    "Twizzlers", "Jolly Rancher", "Sour Patch Kids", "Swedish Fish", "Nerds",
    "Airheads", "Skittles", "Starburst", "Life Savers", "Bubble Yum", "Trident",
    "Orbit", "Extra", "Doublemint", "Juicy Fruit", "5 Gum", "Halls", "Ricola",
    "Fisherman's Friend", "Cepacol", "Chloraseptic",
    # --- beverages/alcohol continued ---
    "Anheuser-Busch", "Budweiser", "Bud Light", "Michelob", "Stella Artois",
    "Corona", "Modelo", "Heineken", "Amstel", "Guinness", "Carlsberg", "Tuborg",
    "Foster's", "VB", "Tooheys", "Coopers", "Kirin", "Asahi", "Sapporo",
    "Molson Coors", "Miller", "Coors", "Blue Moon", "Sam Adams", "Sierra Nevada",
    "New Belgium", "Dogfish Head", "Stone Brewing", "Bell's", "Founders",
    "Lagunitas", "Ballast Point", "Goose Island", "Goose Island Beer",
    "Jack Daniel's", "Jim Beam", "Wild Turkey", "Maker's Mark", "Johnnie Walker",
    "Glenfiddich", "Macallan", "Jameson", "Bushmills", "Bacardi", "Captain Morgan",
    "Malibu", "Smirnoff", "Absolut", "Grey Goose", "Belvedere", "Ketel One",
    "Tanqueray", "Beefeater", "Hendrick's", "Bombay Sapphire", "Gordon's",
    "Mojito", "Baileys", "Kahlúa", "Amaretto", "Grand Marnier", "Cointreau",
    "Campari", "Aperol", "Fernet", "Pernod", "Ricard", "Pastis",
    # --- tobacco (for context) ---
    "Marlboro", "Camel", "Winston", "Newport", "Lucky Strike", "Pall Mall",
    "Kent", "Davidoff", "Parliament", "Vuse", "JUUL", "Blu", "IQOS", "glo",
    # --- consumer tech / home ---
    "Dyson", "Shark", "Ninja", "Bissell", "Hoover", "Electrolux", "Miele",
    "Bosch", "Siemens Home", "Whirlpool", "Maytag", "KitchenAid", "GE Appliances",
    "LG Electronics", "Samsung Electronics", "Panasonic", "Sharp", "Toshiba",
    "Hitachi", "Fujitsu", "NEC", "Razer", "Logitech", "SteelSeries", "Corsair",
    "HyperX", "Alienware", "ROG", "MSI", "Gigabyte", "ASUS", "Acer", "Dell",
    "HP", "Lenovo", "Surface", "iPad", "iPhone", "MacBook", "iMac", "AirPods",
    "Apple Watch", "Galaxy", "Pixel", "Nothing", "Fairphone", "BlackBerry",
    "Nokia Phones", "Motorola", "Palm", "Palm Inc",
    # --- travel / booking / maps ---
    "Google Maps", "Google Earth", "Apple Maps", "Waze", "MapQuest", "HERE",
    "TomTom", "Garmin", "Strava", "AllTrails", "Komoot", "GasBuddy",
    "TripIt", "Hopper", "Skyscanner", "Momondo", "Kiwi.com", "Priceline",
    "Hotwire", "Hotels.com", "Trivago", "Agoda", "MakeMyTrip", "Yatra",
    "Cleartrip", "Goibibo", "RailEurope", "Omio", "Trainline", "The Points Guy",
    # --- news / media continued ---
    "New York Times", "Washington Post", "Wall Street Journal", "USA Today",
    "Los Angeles Times", "Chicago Tribune", "Houston Chronicle", "The Guardian",
    "The Times", "Financial Times", "The Economist", "Bloomberg", "Reuters",
    "Associated Press", "AFP", "Al Jazeera", "BBC News", "Sky News", "ITV",
    "Channel 4", "Channel 5", "ABC News", "CBS News", "NBC News", "Fox",
    "MSNBC", "CNBC", "CNN Business", "The Independent", "The Daily Telegraph",
    "The Sun", "Daily Mail", "Mirror", "Metro", "Evening Standard",
    "NPR", "PBS", "Vox", "BuzzFeed", "HuffPost", "Gawker", "Vice", "Mashable",
    "TechCrunch", "The Verge", "Engadget", "Gizmodo", "Wired", "Ars Technica",
    "Motherboard", "404 Media", "Rest of World", "The Information",
    # --- finance/crypto continued ---
    "Fidelity", "Vanguard", "Charles Schwab", "TD Ameritrade", "E*TRADE",
    "Interactive Brokers", "Wealthfront", "Betterment", "Acorns", "Stash",
    "SoFi", "Chime", "Varo", "Aspiration", "Green Dot", "Netspend",
    "Wise Platform", "Revolut Business", "N26", "Monzo", "Starling Bank",
    "Chase Sapphire", "Capital One", "Ally", "Marcus", "Synchrony", "Barclaycard",
    "Discover Card", "Citi Card", "Amex Gold", "Apple Card", "Google Pay",
    "Apple Pay", "Samsung Pay", "Garmin Pay", "Fitbit Pay", "Klarna Checkout",
    "Afterpay", "Zip", "Sezzle", "Quadpay", "Laybuy", "Humm", "Openpay",
    "Splitit", "Clearpay", "TrueLayer", "Plaid", "MX", "Yodlee", "Finicity",
    "Sila", "Wyre", "MoonPay", "Simplex", "Ramp", "Brex", "Divvy", "Spendesk",
    "Pleo", "Soldo", "Payhawk", "Jeeves", "Expensify", "Concur", "SAP Concur",
    # --- AI/ML infra continued ---
    "Weights & Biases", "Neptune.ai", "Comet", "MLflow", "Kubeflow", "Airflow",
    "Prefect", "Dagster", "Luigi", "dbt", "Fivetran", "Airbyte", "Stitch",
    "Hevo", "Segment", "Amplitude", "Mixpanel", "Heap", "Fullstory", "Hotjar",
    "Clearbit", "FullContact", "PeopleDataLabs", "Hunter.io", "Apollo.io",
    "Clay", "Instantly", "Smartlead", "Lemlist", "Woodpecker", "Mailshake",
    "Reply.io", "Outreach", "Salesloft", "Gong", "Chorus", "ExecVision",
    "Clari", "Gainsight", "ChurnZero", "Totango", "PlanHat", "Medallia",
    "Qualtrics", "SurveyMonkey", "Typeform", "Jotform", "Google Forms",
    # --- government / orgs continued ---
    "IRS", "SEC", "FTC", "FDA", "EPA", "DOJ", "DHS", "FAA", "TSA", "CBP",
    "USPS", "Dept of Defense", "Dept of Energy", "Dept of Justice", "Dept of State",
    "CDC", "NIH", "NSF", "FEMA", "US Army", "US Navy", "US Air Force",
    "US Marine Corps", "US Coast Guard", "US Space Force", "National Guard",
    "Interpol", "Europol", "Scotland Yard", "MI5", "MI6", "KGB", "FSB",
    "GRU", "Mossad", "Shin Bet", "CIAO", "NSA Office", "GCHQ",
    # --- sports/leagues continued ---
    "Premier League", "La Liga", "Serie A", "Bundesliga", "Ligue 1", "MLS",
    "A-League", "Indian Premier League", "Big Bash League", "UEFA",
    "CONCACAF", "CONMEBOL", "AFC", "CAF", "OFC", "World Cup", "Super Bowl",
    "World Series", "NBA Finals", "Stanley Cup", "Champions League",
    "Europa League", "FA Cup", "Copa America", "Euros", "Cricket World Cup",
    "Tour de France", "Wimbledon", "US Open", "French Open", "Australian Open",
    "Masters", "Ryder Cup", "Solheim Cup", "Grand Prix", "Indy 500",
    "Daytona 500", "Bathurst 1000", "Le Mans", "24 Hours of Le Mans",
    # --- universities (context) ---
    "Harvard", "Yale", "Princeton", "Stanford", "MIT", "Caltech", "Berkeley",
    "Oxford", "Cambridge", "Imperial College", "London School of Economics",
    "University of Melbourne", "University of Sydney", "Monash", "UNSW",
    "ANU", "University of Toronto", "McGill", "UBC",
]

# Aliases: canonical brand name -> extra search terms that help find the logo.
ALIASES = {
    "Grok": "Grok xAI logo",
    "X": "X (Twitter) logo",
    "Teams": "Microsoft Teams logo",
    "AWS": "Amazon Web Services logo",
    "GM": "General Motors logo",
    "EA": "Electronic Arts logo",
    "Max": "HBO Max logo",
    "Disney+": "Disney Plus logo",
    "P&G": "Procter & Gamble logo",
    "7Up": "7 Up logo",
    "M&M's": "M&M's logo",
    "NASA": "NASA insignia",
    "CIA": "CIA seal",
    "FBI": "FBI seal",
    "NSA": "NSA seal",
}


def _api(params: dict) -> dict:
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read())


def _search_logo(brand: str) -> str | None:
    """Return the best Wikimedia Commons File: title for a brand's logo."""
    q = ALIASES.get(brand, f"{brand} logo")
    # 1) Prefer SVG logo files
    for query in (f"{q} filetype:svg", f"{q} logo"):
        try:
            d = _api({"action": "query", "list": "search", "srsearch": query,
                      "srnamespace": "6", "srlimit": "8", "format": "json"})
            titles = [x["title"] for x in d.get("query", {}).get("search", [])]
            # score: prefer exact '<Brand> logo', avoid ASCII/owners/wordmark-only
            scored = []
            lowq = q.lower()
            for t in titles:
                tl = t.lower()
                score = 0
                if re.search(rf"\b{re.escape(brand.lower())}\b", tl):
                    score += 3
                if "logo" in tl:
                    score += 2
                if t.endswith(".svg"):
                    score += 2
                if any(b in tl for b in ("ascii", "owner", "wordmark", "icon",
                                         "emoji", "seal", "monogram", "symbol",
                                         "character", "mascot", "history", "1960",
                                         "1970", "1980", "1990", "2000", "former")):
                    score -= 3
                if score > 0:
                    scored.append((score, t))
            if scored:
                scored.sort(key=lambda x: -x[0])
                return scored[0][1]
        except Exception:
            continue
    return None


def _download_thumb(title: str) -> bytes | None:
    """Commons API imageinfo -> 512px rasterized PNG thumb bytes."""
    try:
        d = _api({"action": "query", "titles": title, "prop": "imageinfo",
                  "iiprop": "url", "iiurlwidth": "512", "format": "json"})
        pages = d.get("query", {}).get("pages", {})
        if not pages:
            return None
        ii = next(iter(pages.values())).get("imageinfo")
        if not ii:
            return None
        thumb = ii[0].get("thumburl") or ii[0].get("url")
        if not thumb:
            return None
        req = urllib.request.Request(thumb, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            blob = r.read()
        return blob if len(blob) >= 2000 else None
    except Exception:
        return None


def main():
    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {}
    if MANIFEST.is_file():
        try:
            manifest = json.loads(MANIFEST.read_text())
        except Exception:
            manifest = {}
    ok = skip = fail = 0
    for i, brand in enumerate(BRANDS, 1):
        safe = re.sub(r"[^A-Za-z0-9]+", "_", brand.lower()).strip("_") or "brand"
        out = LOGO_DIR / f"{safe}.png"
        if out.is_file():
            skip += 1
            continue
        print(f"[{i}/{len(BRANDS)}] {brand} ... ", end="", flush=True)
        title = manifest.get(brand) or _search_logo(brand)
        if not title:
            print("no commons match", flush=True)
            fail += 1
            continue
        manifest[brand] = title
        blob = _download_thumb(title)
        if not blob:
            print(f"download failed ({title})", flush=True)
            fail += 1
            continue
        out.write_bytes(blob)
        ok += 1
        print(f"OK ({title})", flush=True)
        time.sleep(0.25)  # be polite to the Commons API
    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nDONE: {ok} downloaded, {skip} already cached, {fail} failed")
    print(f"Manifest: {MANIFEST}")
    print(f"Logos:    {LOGO_DIR} ({len(list(LOGO_DIR.glob('*.png')))} png)")


if __name__ == "__main__":
    main()
