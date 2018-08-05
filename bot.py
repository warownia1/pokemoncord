import asyncio
import logging
import os
import pickle
import random
import re
import signal
import sys
import time

from asyncio import ensure_future
from collections import defaultdict
from functools import partial

import discord

import models
import conf

from conf import main_log as log
from command import CommandDispatcher
from models import Pokemon, database


TEAM_SIZE = 6
TEAM = 1
BOX = 2

spawner_loop_tasks = {}
stop_training_events = {}


client = discord.Client()
command = CommandDispatcher(client)


@client.async_event
def on_ready():
    log.info('Logged on as %s', client.user)


@command.register('pkmn help')
async def print_help(message):
    await client.send_message(
        message.channel,
        'Help text'
    )


@command.register('pkmn spawn')
async def spawn_request(message):
    """Command: spawn [name] - spawn a pokemon with given name or random."""
    await spawn_pokemon(message.channel, message.content[11:])


async def spawn_pokemon(channel, name=None):
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
    await client.send_message(channel, embed=em)
    message = await client.wait_for_message(
        300, channel=channel,
        content='catch {}'.format(pkmn.name)
    )
    if message is None:
        await client.send_message(
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


@command.register('pkmn box')
async def list_pokemon_storage(message):
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
    await client.send_message(message.channel, text)


@command.register('pkmn team')
async def list_pokemon_team(message):
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
    await client.send_message(message.channel, text)


@command.register('pkmn show')
async def show_pokemon(message):
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
    await client.send_message(message.channel, embed=em)


@command.register('pkmn start training')
async def start_training(message):
    """Command: start training - starts a one hour training."""
    if message.author.id in stop_training_events:
        await client.send_message(
            message.channel, "You are already training."
        )
        return
    stop_event = asyncio.Event()
    stop_training_events[message.author.id] = stop_event
    start_time = client.loop.time() - 5
    handler = client.loop.call_later(3600, stop_event.set)
    await client.send_message(message.channel, "Training started.")
    await stop_event.wait()
    handler.cancel()
    del stop_training_events[message.author.id]
    delta_time = (client.loop.time() - start_time) // 60
    database.connect()
    try:
        team = (Pokemon.select()
                .where(
                    (Pokemon.owner_id == message.author.id) &
                    (Pokemon.storage == TEAM)
                ))
        for pkmn in team:
            pkmn.add_exp(delta_time)
            pkmn.save()
        database.commit()
    finally:
        database.close()
    await client.send_message(
        message.author,
        "Training finished. You trained for %u minutes." % delta_time
    )


@command.register('pkmn stop training')
async def stop_training(message):
    try:
        stop_training_events[message.author.id].set()
    except KeyError:
        pass


@command.register('pkmn withdraw')
async def withdraw_pokemon(message):
    database.connect()
    num = (Pokemon.select()
           .where(
               (Pokemon.storage == TEAM) &
               (Pokemon.owner_id == message.author.id)
           )
           .count())
    if num >= TEAM_SIZE:
        database.close()
        await client.send_message(message.channel, 'Your team is full.')
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
    await client.send_message(
        message.channel, '{} withdrawn.'.format(pkmn.name)
    )


@command.register('pkmn deposit')
async def deposit_pkmn_handler(message):
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
    await client.send_message(
        message.channel, '{} sent to box'.format(pkmn.name)
    )


@command.register('pkmn trade')
async def start_trade(message):
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
    await client.send_message(channel, text)

    # wait for buyer to accept trade
    def check(message):
        return message.content.startswith(
            'pkmn offer {}'.format(seller.mention)
        )

    response = await client.wait_for_message(
        300, channel=channel, author=buyer, check=check
    )
    if not response:
        await client.send_message(channel, 'Trade cancelled.')
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

    await client.send_message(channel, 'Trade completed.')


# TODO: make spawner resume after application restart
@command.register('pkmn spawner set')
async def start_spawner_handler(message):
    global spawner_loop_tasks
    channel = message.channel
    if channel.id not in spawner_loop_tasks:
        spawner_loop_tasks[channel.id] = ensure_future(spawner_loop(channel))
        await client.send_message(channel, 'Spawner started')


async def spawner_loop(channel):
    while True:
        await spawn_pokemon(channel)
        await asyncio.sleep(random.randint(10, 20))


@command.register('pkmn spawner stop')
async def stop_spawner_handler(message):
    stop_spawner_loop(message.channel.id)
    await client.send_message(message.channel, 'Spawner stopped')


def stop_spawner_loop(channel_id):
    global spawner_loop_tasks
    try:
        spawner_loop_tasks[channel_id].cancel()
        del spawner_loop_tasks[channel_id]
    except KeyError:
        pass


@command.register('pkmn shutdown')
async def shutdown_handler(message):
    await shutdown()
    

async def shutdown():
    log.info('Shutting down')
    for event in stop_training_events.values():
        event.set()
    for channel_id in list(spawner_loop_tasks.keys()):
        stop_spawner_loop(channel_id)
    log.info('Completing unfinished tasks')
    if command.tasks:
        await asyncio.wait(command.tasks, timeout=10)
    log.info('Closing client connection')
    await client.logout()
    await client.close()


def sigterm_handler(signal_number):
    log.warning('Signal %s received', signal_number)
    ensure_future(shutdown(), loop=client.loop)


def main():
    for sig in (signal.SIGTERM, signal.SIGINT):
        client.loop.add_signal_handler(sig, partial(sigterm_handler, sig))
    try:
        try:
            start = client.loop.create_task(client.start(conf.ACCESS_TOKEN))
            client.loop.run_until_complete(start)
        except KeyboardInterrupt:
            log.warning('KeyboardInterrupt received')
            client.loop.run_until_complete(shutdown())
        pending = asyncio.Task.all_tasks(loop=client.loop)
        gathered = asyncio.gather(*pending, loop=client.loop)
        try:
            gathered.cancel()
            client.loop.run_until_complete(gathered)
            gathered.exception()
        except asyncio.CancelledError:
            pass
    finally:
        client.loop.close()
        log.info('Shutdown completed, loop closed')


if __name__ == '__main__':
    try:
        main()
    finally:
        client.close()
