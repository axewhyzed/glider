# glider

venv\Scripts\activate

pip install curl_cffi selectolax playwright pydantic typer colorama

playwright install chromium

pip install lxml

pip freeze > requirements.txt


glider/
│
├── .gitignore             # Ignored files (venv, etc.)
├── requirements.txt       # Locked dependencies
├── main.py                # The CLI Entry Point
│
├── configs/               # WHERE WE DEFINE TARGETS
│   └── example.json       # We will create this next
│
├── engine/                # THE CORE LOGIC
│   ├── __init__.py        # Makes 'engine' importable
│   ├── scraper.py         # Main scraping class (The "Manager")
│   ├── resolver.py        # Selector logic (ID > CSS > XPath)
│   └── utils.py           # Cleaning & Transformers
│
├── logs/                  # Stores error logs (optional but pro)
└── venv/                  # (Hidden) Your Python environment