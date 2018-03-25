import discord
import asyncio
import random
import re
import logging
import sys
import pickle

from collections import defaultdict, namedtuple

logging.basicConfig(stream=sys.stdout, level=logging.INFO)

PkmnEntry = namedtuple('PkmnEntry', 'no, name')


class Client(discord.Client):

    def __init__(self):
        super().__init__()
        self.pkmn_list = []
        with open('pkmn-list.txt') as f:
            for line in f:
                m = re.match(r'#(\d{3}) (.+)\n', line)
                pkmn = PkmnEntry(int(m.group(1)), m.group(2))
                self.pkmn_list.append(pkmn)
        self._load_pkmn_from_file()
            
    def _load_pkmn_from_file(self):
        try:
            with open('pkmn-storage.dat', 'rb') as storage_file, \
                    open('pkmn-team.dat', 'rb') as team_file:
                self._pkmn_storage = pickle.load(storage_file)
                self._pkmn_team = pickle.load(team_file)
        except FileNotFoundError:
            self._pkmn_storage = defaultdict(list)
            self._pkmn_team = defaultdict(list)

    async def on_ready(self):
        print('Logged on as {0}'.format(self.user))
        
    async def on_message(self, message):
        if message.author == self.user:
            return
        logging.info('Message from {0.author}: {0.content}'.format(message))
        if message.content == 'pkmn spawn':
            await self._spawn_pkmn(message.channel)
        elif message.content.startswith('pkmn spawn'):
            await self._spawn_pkmn(message.channel, message.content[11:])
        elif message.channel.is_private:
            if message.content == 'pkmn help':
                await self._print_help(message.channel)
            elif message.content == 'start spawner':
                self._spawner_loop_task = self.loop.create_task(
                    self.start_spawner_loop(None)
                )
            elif message.content == 'cancel spawner':
                self._spawner_loop_task.cancel()
            elif message.content == 'pkmn storage':
                await self.list_pokemon_storage(
                    message.author, message.channel)
            elif message.content == 'pkmn team':
                await self.list_pokemon_team(message.author, message.channel)
            elif message.content == 'pkmn shutdown':
                await self.close()
                for task in asyncio.Task.all_tasks():
                    task.cancel()
        else:
            if message.content.startswith('pkmn trade'):
                await self._start_trade(message)
             
    async def _print_help(self, channel):
        pass
    
    async def _spawn_pkmn(self, channel, name=None):
        if name is not None:
            pkmn = next(p for p in self.pkmn_list if p.name == name)
        else:
            pkmn = random.choice(self.pkmn_list)
        logging.info('spawning {}'.format(pkmn))
        url = ('https://assets.pokemon.com/assets/cms2/'
               'img/pokedex/full/{:03}.png'.format(pkmn.no))
        logging.debug(url)
        em = discord.Embed(
            title='A wild {} has appeared!'.format(pkmn.name),
            description=('Type \'catch {}\' before '
                         'it escapes.'.format(pkmn.name)),
            colour=0x00AE86
        )
        em.set_image(url=url)
        await self.send_message(channel, embed=em)
        message = await client.wait_for_message(
            300, channel=channel,
            content='catch {}'.format(pkmn.name)
        )
        if message is None:
            await self.send_message(channel, '{} escaped.'.format(pkmn.name))
        else:
            self._add_caught_pokemon(message.author, pkmn, channel)

    def _add_caught_pokemon(self, user, pkmn, channel):
        text = 'Congratulations! {} caught {}.'.format(
            user.mention, pkmn.name
        )
        if len(self._pkmn_team[user.id]) < 5:
            self._pkmn_team[user.id].append(pkmn.name)
        else:
            self._pkmn_storage[user.id].append(pkmn.name)
            text += '\nPokemon was added to your storage'
        asyncio.ensure_future(
            self.send_message(channel,text),
            loop=self.loop
        )

    async def start_spawner_loop(self, channel):
        channel = self.get_channel('424271560967323669')
        while True:
            await self._spawn_pkmn(channel)
            await asyncio.sleep(random.randint(30, 90))

    async def list_pokemon_storage(self, user, channel):
        text = 'Your pokémons:\n' + '\n'.join(self._pkmn_storage[user.id])
        await self.send_message(channel, text)

    async def list_pokemon_team(self, user, channel):
        text = 'Your team:\n' + '\n'.join(self._pkmn_team[user.id])
        await self.send_message(channel, text)
        
    async def _start_trade(self, message):
        author = message.author
        tokens = message.content.split()
        buyer = message.mentions[0]
        for i in [3, 4]:
            pkmn_name = ' '.join(tokens[2:i])
            print('pkmn name =', pkmn_name)
            if pkmn_name in (pkmn.name for pkmn in self.pkmn_list):
                print('pokemon exists')
                break
        else:
            print('pokemon doesn\'t exist')
            return
        text = ("{}, {} invites you to trade and offers {}."
                .format(buyer.mention, author.name, pkmn_name))
        await self.send_message(message.channel, text)
        check = lambda m: m.content in ['pkmn accept trade', 'pkmn cancel trade']
        response = await client.wait_for_message(
            300, channel=message.channel, author=buyer, check=check
        )
        print(response and response.content)

    def save_pkmn_to_file(self):
        with open('pkmn-storage.dat', 'wb') as storage_file, \
                open('pkmn-team.dat', 'wb') as team_file:
            pickle.dump(self._pkmn_storage, storage_file)
            pickle.dump(self._pkmn_team, team_file)


if __name__ == '__main__':
    client = Client()
    client.run('NDI0NjQ1MTUzNzMxNTEwMjky.DY8JIA.MPw2ScY0FqaOfVI5RsFUYIWGWEk')
    client.save_pkmn_to_file()
    client.loop.close()
    client.close()
