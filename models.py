import csv
import random

from collections import namedtuple

from peewee import Model, IntegerField, CharField, SqliteDatabase


database = SqliteDatabase('sqlite.db')

PokemonRawData = namedtuple('PokemonData',
                            'name, types, evo_level, evo_targets')

_pokemon_data = {}
_highest_number = 0
with open('Pokemonsy.csv', newline='', encoding='utf8') as f:
    reader = csv.reader(f)
    for row in reader:
        _pokemon_data[int(row[0])] = PokemonRawData(
            row[1],
            row[2].split(),
            int(row[3] or 99999),
            [int(n or -1) for n in row[4].split('/')]
        )
    _highest_number = int(row[0])
del f, reader, row


def get_img_url(number):
    return ('https://assets.pokemon.com/assets/cms2/'
            'img/pokedex/full/{:03}.png'.format(number))


class Pokemon(Model):

    id = IntegerField(primary_key=True)
    number = IntegerField()
    name = CharField(max_length=64)
    exp = IntegerField()
    level = IntegerField()
    owner_id = CharField(max_length=32)
    storage = IntegerField()

    def get_img_url(self):
        return get_img_url(self.number)

    def add_exp(self, exp):
        self.exp += exp
        target_level = self.exp_to_level(self.exp)
        if target_level > self.level:
            self.level = target_level
            if target_level >= self.evolution_level:
                self.number = self.evolution_targets[0]
                self.name = _pokemon_data[self.number].name

    @staticmethod
    def exp_to_level(exp):
        return int((5 / 4 * exp) ** (1/3))

    @property
    def evolution_level(self):
        return _pokemon_data[self.number].evo_level

    @property
    def evolution_targets(self):
        return _pokemon_data[self.number].evo_targets

    def __repr__(self):
        return "<Pokemon %s>" % self.name

    @staticmethod
    def spawn_from_number(number):
        dat = _pokemon_data[number]
        return Pokemon(number=number, name=dat.name, exp=1, level=1)

    @staticmethod
    def spawn_from_name(name):
        for number, dat in _pokemon_data.items():
            if name == dat.name:
                return Pokemon.spawn_from_number(number)
        raise ValueError('No pokemon %s' % name)

    @staticmethod
    def spawn_random():
        return Pokemon.spawn_from_number(random.randint(1, _highest_number))

    @staticmethod
    def pokemon_exists(name):
        for dat in _pokemon_data.values():
            if dat.name == name:
                return True
        return False

    class Meta:
        database = database
