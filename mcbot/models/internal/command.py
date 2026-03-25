from typing import Callable, Any, Awaitable

CallbackType = Callable[..., Awaitable[Any]]

class Command:
    def __init__(self, name: str, callback: CallbackType, description: str = "", help: str = ""):
        self.name = name
        self.callback = callback
        self.description = description or callback.__doc__
        self.help = help
        
    async def dispatch(self, *args, **kwargs) -> Any:
        await self.callback(*args, **kwargs)