import discord
import asyncio
import random
import re
import logging
import sys
import pickle

from collections import defaultdict, namedtuple


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

pkmn_list = []
pkmn_storage = []
pkmn_team = []
spawner_loop_task = None


def init():
    # load pokemon list form file
    with open('pkmn-list.txt', 'r', encoding='utf8') as f:
        for line in f:
            m = re.match(r'#(\d{3}) (.+)\n', line)
            pkmn = PkmnEntry(int(m.group(1)), m.group(2))
            pkmn_list.append(pkmn)

    # load previously saved owned pokemons
    global pkmn_storage, pkmn_team
    try:
        with open('pkmn-storage.dat', 'rb') as storage_file, \
                open('pkmn-team.dat', 'rb') as team_file:
            pkmn_storage = pickle.load(storage_file)
            pkmn_team = pickle.load(team_file)
    except FileNotFoundError:
        pkmn_storage = defaultdict(list)
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
        yield from spawn_pkmn(message.channel, message.content[11:])
    elif message.content == 'pkmn box':
        yield from list_pokemon_storage(message.author, message.channel)
    elif message.content == 'pkmn team':
        yield from list_pokemon_team(message.author, message.channel)
    elif message.channel.is_private:
        if message.content.startswith('pkmn deposit'):
            yield from deposit_pkmn_handler(message)
        elif message.content.startswith('pkmn withdraw'):
            yield from withdraw_pkmn_handler(message)
        elif message.content == 'pkmn help':
            yield from print_help(message.channel)
        elif message.content == 'pkmn shutdown':
            yield from client.close()
            for task in asyncio.Task.all_tasks():
                task.cancel()
    else:
        if message.content.startswith('pkmn trade'):
            yield from start_trade(message)
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
def withdraw_pkmn_handler(message):
    if len(pkmn_team[message.author.id]) >= 6:
        text = 'Your team is full.'
    else:
        tokens = message.content.split()
        pkmn_name = ' '.join(tokens[2:])
        print(pkmn_storage[message.author.id])
        pkmn_storage[message.author.id].remove(pkmn_name)
        pkmn_team[message.author.id].append(pkmn_name)
        text = '{} withdrawn.'.format(pkmn_name)
    yield from client.send_message(message.channel, text)


@asyncio.coroutine
def deposit_pkmn_handler(message):
    tokens = message.content.split()
    pkmn_name = ' '.join(tokens[2:])
    print(pkmn_team[message.author.id])
    pkmn_team[message.author.id].remove(pkmn_name)
    pkmn_storage[message.author.id].append(pkmn_name)
    yield from client.send_message(
        message.channel, '{} sent to box'.format(pkmn_name)
    )


@asyncio.coroutine
def spawn_pkmn(channel, name=None):
    if name:
        pkmn = next(p for p in pkmn_list if p.name == name)
    else:
        pkmn = random.choice(pkmn_list)
    log.info('spawning {}'.format(pkmn))
    img_url = ('https://assets.pokemon.com/assets/cms2/'
               'img/pokedex/full/{:03}.png'.format(pkmn.no))
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
    if len(pkmn_team[user.id]) < 6:
        pkmn_team[user.id].append(pkmn.name)
    else:
        pkmn_storage[user.id].append(pkmn.name)
        text += '\nPokemon was added to your storage'
    asyncio.ensure_future(client.send_message(channel, text))


@asyncio.coroutine
def start_spawner_loop(channel):
    channel = client.get_channel('424271560967323669')
    while True:
        yield from _spawn_pkmn(channel)
        yield from asyncio.sleep(random.randint(30, 90))


@asyncio.coroutine
def list_pokemon_storage(user, channel):
    text = 'Your pokémons:\n' + '\n'.join(
        " - **%s**" % name for name in pkmn_storage[user.id]
    )
    yield from client.send_message(channel, text)


@asyncio.coroutine
def list_pokemon_team(user, channel):
    text = 'Your team:\n' + '\n'.join(
        " - **%s**" % name for name in pkmn_team[user.id]
    )
    yield from client.send_message(channel, text)


@asyncio.coroutine
def start_trade(message):
    seller = message.author
    buyer = message.mentions[0]
    channel = message.channel
    
    tokens = message.content.split()
    pkmn_name = ' '.join(tokens[3:])
    if pkmn_name not in (pkmn.name for pkmn in pkmn_list):
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
    if pkmn2_name not in (pkmn.name for pkmn in pkmn_list):
        return
    
    log.debug('%s sells %s', seller.name, pkmn_name)
    log.debug('%s sells %s', buyer.name, pkmn2_name)
    
    # trade was accepted by both sides, complete the trade
    trade_pkmns(seller, pkmn_name, buyer, pkmn2_name)
    yield from client.send_message(channel, 'Trade completed.')


def trade_pkmns(seller, soffer, buyer, boffer):
    log.info('exchange %s for %s', soffer, boffer)
    sarg = pkmn_storage[seller.id].index(soffer)
    barg = pkmn_storage[buyer.id].index(boffer)
    pkmn_storage[buyer.id].append(pkmn_storage[seller.id].pop(sarg))
    pkmn_storage[seller.id].append(pkmn_storage[buyer.id].pop(barg))


def save_pkmn_to_file():
    with open('pkmn-storage.dat', 'wb') as storage_file, \
            open('pkmn-team.dat', 'wb') as team_file:
        pickle.dump(pkmn_storage, storage_file)
        pickle.dump(pkmn_team, team_file)


if __name__ == '__main__':
    init()
    try:
        client.run(ACCESS_TOKEN)
    finally:
        save_pkmn_to_file()
    client.loop.close()
    client.close()
