import asyncio
import csv
import logging
import os
import pickle
import random
import re
import sys
import time
import warnings

from asyncio import ensure_future
from collections import defaultdict, namedtuple

import discord


ACCESS_TOKEN = os.environ['DISCORD_TOKEN']

# logging configuration
log = logging.getLogger('pokebot-main')
log.setLevel(logging.DEBUG)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(name)s %(levelname)s: %(message)s')
console_handler.setFormatter(formatter)
log.addHandler(console_handler)
del console_handler, formatter

logging.basicConfig(level=logging.INFO)

TEAM_SIZE = 6
pkmn_box = []
pkmn_team = []
spawner_loop_tasks = {}
stop_training_events = {}


PokemonRawData = namedtuple('PokemonData',
                            'name, types, evo_level, evo_targets')


class Pokemon:

    __slots__ = ['number', 'name', 'exp', 'level']

    all_pokemon = {}

    def __init__(self, number):
        self.number = number
        self.name = self.all_pokemon[self.number].name
        self.exp = 1
        self.level = 1

    @classmethod
    def spawn_random(cls):
        return cls(random.choice(list(cls.all_pokemon)))

    @classmethod
    def spawn_from_name(cls, name):
        for number, pkmn in cls.all_pokemon.items():
            if name == pkmn[0]:
                return cls(number)
        raise ValueError('No pokemon %s' % name)

    @classmethod
    def name_exists(cls, name):
        return name in cls.all_pokemon.values()

    def get_img_url(self):
        return ('https://assets.pokemon.com/assets/cms2/'
                'img/pokedex/full/{:03}.png'.format(self.number))

    def add_exp(self, exp):
        self.exp += exp
        target_level = self.level_from_exp(self.exp)
        if target_level > self.level:
            self.level = target_level
            if target_level >= self.evolution_level:
                self.number = self.evolution_targets[0]

    @staticmethod
    def level_from_exp(exp):
        return int((5 / 4 * exp) ** (1/3))

    @property
    def evolution_level(self):
        return self.all_pokemon[self.number].evo_level

    @property
    def evolution_targets(self):
        return self.all_pokemon[self.number].evo_targets

    with open('Pokemonsy.csv', newline='', encoding='utf8') as f:
        reader = csv.reader(f)
        for row in reader:
            all_pokemon[int(row[0])] = PokemonRawData(
                row[1],
                row[2].split(),
                int(row[3] or 99999),
                [int(n or -1) for n in row[4].split('/')]
            )
    del f, reader


class CommandDispatcher:

    PREFIX = 'pkmn '

    def __init__(self, client):
        self._registered_commands = []
        self._client = client
        client.event(self.on_message)

    def async_register(self, command):
        if not command.startswith(self.PREFIX):
            command = self.PREFIX + command
        def add(func):
            if not asyncio.iscoroutinefunction(func):
                func = asyncio.coroutine(func)
            self._registered_commands.append((command, func))
            return func
        return add

    @asyncio.coroutine
    def on_message(self, message):
        if message.author == self._client.user:
            return
        if message.content.startswith(self.PREFIX):
            for command, func in self._registered_commands:
                if message.content.startswith(command):
                    return ensure_future(func(message))
            raise ValueError('Invalid command')


client = discord.Client()
command = CommandDispatcher(client)


@client.async_event
def on_ready():
    print('Logged on as {0}'.format(client.user))


@command.async_register('help')
def print_help(message):
    yield from client.send_message(
        message.channel,
        'Help text'
    )


@command.async_register('spawn')
def spawn_request(message):
    """Command: spawn [name] - spawn a pokemon with given name or random."""
    yield from spawn_pokemon(message.channel, message.content[11:])


@asyncio.coroutine
def spawn_pokemon(channel, name=None):
    """Spawn the pokemon with given name in the channel.

    Creates a new Pokemon instance following the name or random if None given.
    The notification of pokemon appearance is then send to a specified
    channel and users can catch the pokemon.
    """
    if name:
        pkmn = Pokemon.spawn_from_name(name)
    else:
        pkmn = Pokemon.spawn_random()
    log.info('spawning {}'.format(pkmn))
    img_url = pkmn.get_img_url()
    log.debug(img_url)
    em = discord.Embed(
        title='A wild {} has appeared!'.format(pkmn.name),
        description=('Type \'catch {}\' before '
                     'it escapes.'.format(pkmn.name)),
        colour=0x00AE86
    )
    em.set_image(url=img_url)
    yield from client.send_message(channel, embed=em)
    message = yield from client.wait_for_message(
        300, channel=channel,
        content='catch {}'.format(pkmn.name)
    )
    if message is None:
        yield from client.send_message(
            channel, '{} escaped.'.format(pkmn.name)
        )
    else:
        add_caught_pokemon(message.author, pkmn, channel)


def add_caught_pokemon(user, pkmn, channel):
    """Add caught pokemon to the user's storage.

    Adds the pokemon to the storage and sends a notification about caught
    pokemon to the channel.
    """
    text = 'Congratulations! {} caught {}.'.format(
        user.mention, pkmn.name
    )
    if len(pkmn_team[user.id]) < TEAM_SIZE:
        pkmn_team[user.id].append(pkmn)
    else:
        pkmn_box[user.id].append(pkmn)
        text += '\nPokemon was added to your storage'
    ensure_future(client.send_message(channel, text))


@command.async_register('box')
def list_pokemon_storage(message):
    """Command: box - list the pokemons in the user's box."""
    text = 'Your pokémons:\n' + '\n'.join(
        " - **{0.name}** lv. {0.level}".format(pkmn)
        for pkmn in pkmn_box[message.author.id]
    )
    yield from client.send_message(message.channel, text)


@command.async_register('team')
def list_pokemon_team(message):
    """Command: team - list the pokemons in user's team."""
    text = 'Your team:\n' + '\n'.join(
        " - **{0.name}** lv. {0.level}".format(pkmn)
        for pkmn in pkmn_team[message.author.id]
    )
    yield from client.send_message(message.channel, text)


@command.async_register('show')
def show_pokemon(message):
    """Command: show [index] - show the pokemon from your team.

    Displays information about the pokemon in the current channel.
    The pokemon is selected fron your team at the specified index,
    if index is not given, show the first pokemon.
    """
    num = int(message.content[10:] or 1)
    pkmn = pkmn_team[message.author.id][num - 1]
    em = discord.Embed(
        title='{} lv. {}'.format(pkmn.name, pkmn.level),
        colour=0xC00000
    )
    em.set_image(url=pkmn.get_img_url())
    yield from client.send_message(message.channel, embed=em)


@command.async_register('start training')
def start_training(message):
    """Command: start training - starts a one hour training."""
    if message.author.id in stop_training_events:
        yield from client.send_message(
            message.channel, "You are already training."
        )
        return
    stop_event = asyncio.Event()
    stop_training_events[message.author.id] = stop_event
    start_time = client.loop.time()
    handler = client.loop.call_later(3600, stop_event.set)
    yield from client.send_message(message.channel, "Training started.")
    yield from stop_event.wait()
    handler.cancel()
    del stop_training_events[message.author.id]
    delta_time = (client.loop.time() - start_time) // 60
    for pkmn in pkmn_team[message.author.id]:
        pkmn.add_exp(delta_time)
    ensure_future(client.send_message(
        message.author,
        "Training finished. You trained for %u minutes." % delta_time
    ))


@command.async_register('stop training')
def stop_training(message):
    try:
        stop_training_events[message.author.id].set()
    except KeyError:
        pass


@command.async_register('withdraw')
def withdraw_pokemon(message):
    if len(pkmn_team[message.author.id]) >= TEAM_SIZE:
        text = 'Your team is full.'
    else:
        tokens = message.content.split()
        pkmn_name = ' '.join(tokens[2:])
        box = pkmn_box[message.author.id]
        index, pkmn = next((i, p) for (i, p) in enumerate(box)
                           if p.name == pkmn_name)
        del box[index]
        pkmn_team[message.author.id].append(pkmn)
        text = '{} withdrawn.'.format(pkmn.name)
    yield from client.send_message(message.channel, text)


@command.async_register('deposit')
def deposit_pkmn_handler(message):
    tokens = message.content.split()
    pkmn_name = ' '.join(tokens[2:])
    team = pkmn_team[message.author.id]
    index, pkmn =  next((i, p) for (i, p) in enumerate(team)
                        if p.name == pkmn_name)
    del team[index]
    pkmn_box[message.author.id].append(pkmn)
    yield from client.send_message(
        message.channel, '{} sent to box'.format(pkmn.name)
    )


@command.async_register('trade')
def start_trade(message):
    seller = message.author
    buyer = message.mentions[0]
    channel = message.channel

    tokens = message.content.split()
    pkmn_name = ' '.join(tokens[3:])
    if not Pokemon.name_exists(pkmn_name):
        return

    # pokemon exists, send invitation to trade
    text = ("{}, {} invites you to trade and offers {}.\n"
            "Enter 'pkmn offer {} <pokemon>' to trade."
            .format(buyer.mention, seller.name, pkmn_name, seller.mention))
    yield from client.send_message(channel, text)

    # wait for buyer to accept trade
    def check(message):
        return message.content.startswith(
            'pkmn offer {}'.format(seller.mention)
        )

    response = yield from client.wait_for_message(
        300, channel=channel, author=buyer, check=check
    )
    if not response:
        yield from client.send_message(channel, 'Trade cancelled.')
        return
    tokens = response.content.split()
    pkmn2_name = ' '.join(tokens[3:])
    if not Pokemon.name_exists(pkmn2_name):
        return

    # trade was accepted by both sides, complete the trade
    trade_pkmns(seller, pkmn_name, buyer, pkmn2_name)
    yield from client.send_message(channel, 'Trade completed.')


def trade_pkmns(seller, sname, buyer, bname):
    sindex, spkmn = next((i, p) for (i, p) in enumerate(pkmn_box[seller.id])
                         if p.name == sname)
    bindex, bpkmn = next((i, p) for (i, p) in enumerate(pkmn_box[buyer.id])
                         if p.name == bname)
    pkmn_box[buyer.id].append(pkmn_box[seller.id].pop(sindex))
    pkmn_box[seller.id].append(pkmn_box[buyer.id].pop(bindex))


@command.async_register('start spawner')
def start_spawner(message):
    global spawner_loop_tasks
    channel = message.channel
    if channel.id not in spawner_loop_tasks:
        # channel = client.get_channel('424271560967323669')
        spawner_loop_tasks[channel.id] = ensure_future(spawner_loop(channel))
        yield from client.send_message(channel, 'Spawner started')


@asyncio.coroutine
def spawner_loop(channel):
    while True:
        yield from spawn_pokemon(channel)
        yield from asyncio.sleep(random.randint(10, 20))


@command.async_register('stop spawner')
def stop_spawner_loop(message):
    global spawner_loop_tasks
    channel = message.channel
    try:
        spawner_loop_tasks[channel.id].cancel()
        del spawner_loop_tasks[channel.id]
        yield from client.send_message(channel, 'Spawner stopped')
    except KeyError:
        pass


@command.async_register('shutdown')
def shutdown(message):
    yield from client.close()
    for task in asyncio.Task.all_tasks():
        task.cancel()


def init():
    """Load previously saved pokemons."""
    global pkmn_box, pkmn_team
    try:
        with open('pkmn-box.dat', 'rb') as box_file, \
                open('pkmn-team.dat', 'rb') as team_file:
            pkmn_box = pickle.load(box_file)
            pkmn_team = pickle.load(team_file)
    except FileNotFoundError:
        pkmn_box = defaultdict(list)
        pkmn_team = defaultdict(list)


def save_pkmn_to_file():
    """Save current team and storage states to files."""
    with open('pkmn-box.dat', 'wb') as storage_file, \
            open('pkmn-team.dat', 'wb') as team_file:
        pickle.dump(pkmn_box, storage_file)
        pickle.dump(pkmn_team, team_file)


if __name__ == '__main__':
    init()
    try:
        client.run(ACCESS_TOKEN)
    finally:
        save_pkmn_to_file()
    client.loop.close()
    client.close()
