from typing import Callable, Any, Awaitable

CallbackType = Callable[..., Awaitable[Any]]

class Command:
    def __init__(self, name: str, callback: CallbackType):
        self.name = name
        self.callback = callback
        
    async def dispatch(self, *args, **kwargs) -> Any:
        await self.callback(*args, **kwargs)