import os
import logging
import csv

from collections import namedtuple

try:
    from .dev import *
except ImportError:
    from .production import *


DIR = os.path.dirname(os.path.dirname(__file__))

# logging configuration
logging.basicConfig(level=logging.INFO)

main_log = logging.getLogger('pokebot-main')
console_handler = logging.StreamHandler()
if DEBUG:
    main_log.setLevel(logging.DEBUG)
    console_handler.setLevel(logging.DEBUG)
else:
    main_log.setLevel(logging.WARNING)
    console_handler.setLevel(logging.WARNING)
main_log.propagate = False
formatter = logging.Formatter('%(name)s %(levelname)s: %(message)s')
console_handler.setFormatter(formatter)
main_log.addHandler(console_handler)
del console_handler, formatter


# loading Pokemon data from file
PokemonDataRow = namedtuple('PokemonData',
                            'name, types, evo_level, evo_targets')
pokemon_data = {}
pokedex_size = 0
data_file_path = os.path.join(DIR, 'Pokemonsy.csv')
with open(data_file_path, newline='', encoding='utf8') as f:
    for row in csv.reader(f):
        pokemon_data[int(row[0])] = PokemonDataRow(
            name=row[1],
            types=row[2].split(),
            evo_level=int(row[3] or 99999),
            evo_targets=[int(n or -1) for n in row[4].split('/')]
        )
    pokedex_size += 1
del data_file_path, f, row
