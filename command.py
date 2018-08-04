import asyncio
from asyncio import ensure_future

from conf import main_log as log

class CommandDispatcher:

    def __init__(self, client):
        self._registered_commands = []
        self._client = client
        client.event(self.on_message)

    def async_register(self, command):
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
        for command, handler in self._registered_commands:
            if message.content.startswith(command):
                log.debug('received command %r', message.content)
                yield from handler(message)
