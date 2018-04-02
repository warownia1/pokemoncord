import asyncio
import logging
import pickle
import random
import re
import sys
import time
import warnings

from asyncio import ensure_future
from collections import defaultdict, namedtuple

import discord


ACCESS_TOKEN = 'NDI0NjQ1MTUzNzMxNTEwMjky.DY8JIA.MPw2ScY0FqaOfVI5RsFUYIWGWEk'

# logging configuration
log = logging.getLogger('pokebot-main')
log.setLevel(logging.DEBUG)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(name)s %(levelname)s: %(message)s')
console_handler.setFormatter(formatter)
log.addHandler(console_handler)
del console_handler, formatter

PkmnEntry = namedtuple('PkmnEntry', 'no, name')
client = discord.Client()

TEAM_SIZE = 6
pkmn_box = []
pkmn_team = []
spawner_loop_task = None


class Pokemon:

    __slots__ = ['number', 'name', 'exp', 'level']

    all_pokemon = {}

    def __init__(self, number):
        self.number = number
        self.name = self.all_pokemon[number]
        self.exp = 0
        self.level = 1

    @classmethod
    def spawn_random(cls):
        return cls(random.choice(list(cls.all_pokemon)))

    @classmethod
    def spawn_from_name(cls, name):
        for number, pkmn_name in cls.all_pokemon.items():
            if name == pkmn_name:
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
            return True
        return False

    @staticmethod
    def level_from_exp(exp):
        return int((5 / 4 * exp) ** (1/3))

    @property
    def no(self):
        warnings.warn("Use Pokemon.number instead.", DeprecationWarning)
        return self.number

    with open('pkmn-list.txt', 'r', encoding='utf8') as f:
        for line in f:
            m = re.match(r'#(\d{3}) (.+)\n', line)
            all_pokemon[int(m.group(1))] = m.group(2)
    del line, f, m


def init():
    # load previously saved owned pokemons
    global pkmn_box, pkmn_team
    try:
        with open('pkmn-box.dat', 'rb') as box_file, \
                open('pkmn-team.dat', 'rb') as team_file:
            pkmn_box = pickle.load(box_file)
            pkmn_team = pickle.load(team_file)
    except FileNotFoundError:
        pkmn_box = defaultdict(list)
        pkmn_team = defaultdict(list)


@client.async_event
def on_ready():
    print('Logged on as {0}'.format(client.user))


@client.async_event
def on_message(message):
    if message.author == client.user:
        return
    log.info('Message from {0.author}: {0.content}'.format(message))
    if message.content.startswith('pkmn spawn'):
        ensure_future(spawn_pkmn(message.channel, message.content[11:]))
    elif message.content == 'pkmn box':
        ensure_future(list_pokemon_storage(message.author, message.channel))
    elif message.content == 'pkmn team':
        ensure_future(list_pokemon_team(message.author, message.channel))
    elif message.content.startswith('pkmn show'):
        ensure_future(show_pokemon_handler(message))
    elif message.content == 'pkmn start training':
        ensure_future(start_training(message.channel, message.author))
    elif message.channel.is_private:
        if message.content.startswith('pkmn deposit'):
            ensure_future(deposit_pkmn_handler(message))
        elif message.content.startswith('pkmn withdraw'):
            ensure_future(withdraw_pkmn_handler(message))
        elif message.content == 'pkmn help':
            ensure_future(print_help(message.channel))
        elif message.content == 'pkmn shutdown':
            yield from client.close()
            for task in asyncio.Task.all_tasks():
                task.cancel()
    else:
        if message.content.startswith('pkmn trade'):
            ensure_future(start_trade(message))
        elif message.content == 'start spawner':
            global spawner_loop_task
            spawner_loop_task = client.loop.create_task(
                start_spawner_loop(message.channel)
            )
        elif message.content == 'cancel spawner':
            spawner_loop_task.cancel()


@asyncio.coroutine
def print_help(channel):
    pass


@asyncio.coroutine
def spawn_pkmn(channel, name=None):
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
    text = 'Congratulations! {} caught {}.'.format(
        user.mention, pkmn.name
    )
    if len(pkmn_team[user.id]) < TEAM_SIZE:
        pkmn_team[user.id].append(pkmn)
    else:
        pkmn_box[user.id].append(pkmn)
        text += '\nPokemon was added to your storage'
    ensure_future(client.send_message(channel, text))


@asyncio.coroutine
def list_pokemon_storage(user, channel):
    text = 'Your pokémons:\n' + '\n'.join(
        " - **{0.name}** lv. {0.level}".format(pkmn)
        for pkmn in pkmn_box[user.id]
    )
    yield from client.send_message(channel, text)


@asyncio.coroutine
def list_pokemon_team(user, channel):
    text = 'Your team:\n' + '\n'.join(
        " - **{0.name}** lv. {0.level}".format(pkmn)
        for pkmn in pkmn_team[user.id]
    )
    yield from client.send_message(channel, text)


@asyncio.coroutine
def show_pokemon_handler(message):
    num = int(message.content[10:] or 1)
    pkmn = pkmn_team[message.author.id][num - 1]
    em = discord.Embed(
        title='{} lv. {}'.format(pkmn.name, pkmn.level),
        colour=0xC00000
    )
    em.set_image(url=pkmn.get_img_url())
    yield from client.send_message(message.channel, embed=em)


@asyncio.coroutine
def start_training(channel, user):
    client.loop.call_later(3600, complete_training, time.time(), user)
    yield from client.send_message(channel, "Training started.")


def complete_training(start_time, user):
    delta_time = time.time() - start_time
    for pkmn in pkmn_team[user.id]:
        pkmn.add_exp(round(delta_time / 60))
    ensure_future(client.send_message(
        user, "Training finished. You trained for %d seconds." % delta_time
    ))


@asyncio.coroutine
def withdraw_pkmn_handler(message):
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


@asyncio.coroutine
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


@asyncio.coroutine
def start_spawner_loop(channel):
    channel = client.get_channel('424271560967323669')
    while True:
        yield from spawn_pkmn(channel)
        yield from asyncio.sleep(random.randint(30, 90))


@asyncio.coroutine
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

    log.debug('%s sells %s', seller.name, pkmn_name)
    log.debug('%s sells %s', buyer.name, pkmn2_name)

    # trade was accepted by both sides, complete the trade
    trade_pkmns(seller, pkmn_name, buyer, pkmn2_name)
    yield from client.send_message(channel, 'Trade completed.')


def trade_pkmns(seller, sname, buyer, bname):
    log.info('exchange %s for %s', sname, bname)
    sindex, spkmn = next((i, p) for (i, p) in enumerate(pkmn_box[seller.id])
                         if p.name == sname)
    bindex, bpkmn = next((i, p) for (i, p) in enumerate(pkmn_box[buyer.id])
                         if p.name == bname)
    pkmn_box[buyer.id].append(pkmn_box[seller.id].pop(sindex))
    pkmn_box[seller.id].append(pkmn_box[buyer.id].pop(bindex))


def save_pkmn_to_file():
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
