import ast, sys

files = [
    'scrapers/korea/encar_scraper.py',
    'scrapers/korea/kcar_scraper.py',
    'scrapers/acv/acv_scraper.py',
    'scrapers/management/commands/sync_auction.py',
]

all_ok = True
for f in files:
    try:
        with open(f) as fh:
            ast.parse(fh.read())
        print(f'OK  {f}')
    except SyntaxError as e:
        print(f'ERR {f}: {e}')
        all_ok = False

sys.exit(0 if all_ok else 1)
