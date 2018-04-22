import asyncio
import logging
import os
import pickle
import random
import re
import sys
import time
import warnings

from asyncio import ensure_future
from collections import defaultdict

import discord

import models

from models import Pokemon, database


# ~ ACCESS_TOKEN = os.environ['DISCORD_TOKEN']
ACCESS_TOKEN = 'NDI0NjQ1MTUzNzMxNTEwMjky.DbTWOw.cqirV8y_V4GtfFXpWDrDwYKhJb8'

# logging configuration
log = logging.getLogger('pokebot-main')
log.setLevel(logging.DEBUG)
log.propagate = False
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(name)s %(levelname)s: %(message)s')
console_handler.setFormatter(formatter)
log.addHandler(console_handler)
del console_handler, formatter

logging.basicConfig(level=logging.INFO)


TEAM_SIZE = 6
TEAM = 1
BOX = 2

spawner_loop_tasks = {}
stop_training_events = {}


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
    text = ('Congratulations! {} caught {}.'
            .format(user.mention, pkmn.name))
    pkmn.owner_id = user.id
    database.connect()
    count = (Pokemon.select()
             .where(
                (Pokemon.owner_id == user.id) &
                (Pokemon.storage == 1))
             .count())
    if count < TEAM_SIZE:
        pkmn.storage = TEAM
    else:
        pkmn.storage = BOX
        text += '\nPokemon was added to your box.'
    pkmn.save()
    database.commit()
    database.close()
    ensure_future(client.send_message(channel, text))


@command.async_register('box')
def list_pokemon_storage(message):
    """Command: box - list the pokemons in the user's box."""
    database.connect()
    text = 'Your pokémons:\n' + '\n'.join(
        " - **{0.name}** lv. {0.level}".format(pkmn)
        for pkmn in
        (Pokemon.select()
         .where(
            (Pokemon.owner_id == message.author.id) &
            (Pokemon.storage == BOX)
         ))
    )
    database.close()
    yield from client.send_message(message.channel, text)


@command.async_register('team')
def list_pokemon_team(message):
    """Command: team - list the pokemons in user's team."""
    database.connect()
    text = 'Your team:\n' + '\n'.join(
        " - **{0.name}** lv. {0.level}".format(pkmn)
        for pkmn in
        (Pokemon.select()
         .where(
            (Pokemon.owner_id == message.author.id) &
            (Pokemon.storage == TEAM)
         ))
    )
    database.close()
    yield from client.send_message(message.channel, text)


@command.async_register('show')
def show_pokemon(message):
    """Command: show [index] - show the pokemon from your team.

    Displays information about the pokemon in the current channel.
    The pokemon is selected fron your team at the specified index,
    if index is not given, show the first pokemon.
    """
    num = int(message.content[10:] or 1)
    database.connect()
    pkmn = (Pokemon.select()
            .where(
                (Pokemon.owner_id == message.author.id) &
                (Pokemon.storage == TEAM)
            )
            .offset(num - 1)
            .limit(1)
            .first())
    database.close()
    if pkmn is None:
        return
    em = discord.Embed(
        title='{} lv. {}'.format(pkmn.name, pkmn.level),
        colour=0xC00000
    )
    em.set_image(url=pkmn.get_img_url())
    yield from client.send_message(message.channel, embed=em)


# ~ @command.async_register('start training')
# ~ def start_training(message):
    # ~ """Command: start training - starts a one hour training."""
    # ~ if message.author.id in stop_training_events:
        # ~ yield from client.send_message(
            # ~ message.channel, "You are already training."
        # ~ )
        # ~ return
    # ~ stop_event = asyncio.Event()
    # ~ stop_training_events[message.author.id] = stop_event
    # ~ start_time = client.loop.time()
    # ~ handler = client.loop.call_later(3600, stop_event.set)
    # ~ yield from client.send_message(message.channel, "Training started.")
    # ~ yield from stop_event.wait()
    # ~ handler.cancel()
    # ~ del stop_training_events[message.author.id]
    # ~ delta_time = (client.loop.time() - start_time) // 60
    # ~ for pkmn in pkmn_team[message.author.id]:
        # ~ pkmn.add_exp(delta_time)
    # ~ ensure_future(client.send_message(
        # ~ message.author,
        # ~ "Training finished. You trained for %u minutes." % delta_time
    # ~ ))


# ~ @command.async_register('stop training')
# ~ def stop_training(message):
    # ~ try:
        # ~ stop_training_events[message.author.id].set()
    # ~ except KeyError:
        # ~ pass


@command.async_register('withdraw')
def withdraw_pokemon(message):
    database.connect()
    num = (Pokemon.select()
           .where(
               (Pokemon.storage == TEAM) &
               (Pokemon.owner_id == message.author.id)
           )
           .count())
    if num >= TEAM_SIZE:
        database.close()
        yield from client.send_message(message.channel, 'Your team is full.')
        return
    try:
        tokens = message.content.split()
        pkmn_name = ' '.join(tokens[2:])
        pkmn = (Pokemon.select()
                .where(
                    (Pokemon.storage == BOX) &
                    (Pokemon.owner_id == message.author.id) &
                    (Pokemon.name == pkmn_name)
                )
                .first())
        pkmn.storage = TEAM
        pkmn.save()
    finally:
        database.commit()
        database.close()
    yield from client.send_message(
        message.channel, '{} withdrawn.'.format(pkmn.name)
    )


@command.async_register('deposit')
def deposit_pkmn_handler(message):
    tokens = message.content.split()
    pkmn_name = ' '.join(tokens[2:])
    database.connect()
    try:
        pkmn = (Pokemon.select()
                .where(
                    (Pokemon.storage == TEAM) &
                    (Pokemon.owner_id == message.author.id) &
                    (Pokemon.name == pkmn_name)
                )
                .first())
        pkmn.storage = BOX
        pkmn.save()
    finally:
        database.commit()
        database.close()
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
    database.connect()
    try:
        seller_pkmn = Pokemon.get(
            Pokemon.owner_id == seller.id,
            Pokemon.name == pkmn_name
        )
    except Pokemon.DoesNotExist:
        return
    finally:
        database.close()

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
    pkmn_name = ' '.join(tokens[3:])
    database.connect()
    try:
        buyer_pkmn = Pokemon.get(
            Pokemon.owner_id == buyer.id,
            Pokemon.name == pkmn_name
        )
        buyer_pkmn.owner_id = seller.id
        seller_pkmn.owner_id = buyer.id
        buyer_pkmn.storage = seller_pkmn.storage = BOX
        buyer_pkmn.save()
        seller_pkmn.save()
        database.commit()
    except Pokemon.DoesNotExist:
        return
    except:
        database.rollback()
        raise
    finally:
        database.close()

    yield from client.send_message(channel, 'Trade completed.')


# TODO: make spawner resume after application restart
@command.async_register('start spawner')
def start_spawner(message):
    global spawner_loop_tasks
    channel = message.channel
    if channel.id not in spawner_loop_tasks:
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


def main():
    try:
        client.run(ACCESS_TOKEN)
    finally:
        client.loop.close()
        client.close()


if __name__ == '__main__':
    main()
