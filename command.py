import asyncio
from asyncio import ensure_future
from functools import partial

from conf import main_log as log

class CommandDispatcher:

    def __init__(self, client):
        self._registered_commands = []
        self._client = client
        client.event(self.on_message)
        self._tasks = set()

    @property
    def tasks(self):
        return self._tasks

    def register(self, command):
        def add(func):
            if not asyncio.iscoroutinefunction(func):
                raise ValueError('Funciton must be coroutine')
            self._registered_commands.append((command, func))
            return func
        return add

    async def on_message(self, message):
        if message.author == self._client.user:
            return
        for command, handler in self._registered_commands:
            if message.content.startswith(command):
                log.debug('received command %r', message.content)
                task = ensure_future(handler(message), loop=self._client.loop)
                self._tasks.add(task)
                task.add_done_callback(self._tasks.remove)
