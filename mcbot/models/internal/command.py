import inspect
from typing import Callable, Any, Awaitable, TYPE_CHECKING

from mcbot.settings import load_settings

if TYPE_CHECKING:
    from mcbot import Context
    from mcbot.models.internal.extension import Extension

CallbackType = Callable[..., Awaitable[Any]]

class Command:
    def __init__(self, name: str, callback: CallbackType, description: str = "", help: str = ""):
        self.name = name
        self.callback = callback
        self.description = description or callback.__doc__
        self.help = help
        
    async def dispatch(self, ctx: Context, *args, **kwargs) -> Any:
        if mself := getattr(self.callback, "__self__", None):
            self.callback(mself, ctx, *args, **kwargs)
        else:
            await self.callback(ctx, *args, **kwargs)
            
def command(
    name: str = "",
    *,
    description: str = "", 
    help: str = ""
) -> Callable[[CallbackType], Command]:
    """Create a new command.
    
    Usage:
    ```
    bot = Bot(settings)
    
    @bot.command(description="Pong!")
    async def ping(ctx):
        await ctx.send("Pong!")
    ```
    
    Args:
        callback: Function to call on command execution
    """
    def wrapper(func: CallbackType) -> Command:
        settings = load_settings()
        if not inspect.iscoroutinefunction(func):
            raise ValueError("Commands must be coroutines!")
        
        _name = name or func.__name__
        _description = description or func.__doc__ or "No description"
        _help = help or settings.prefix + _name
        
        cmd = Command(_name, func, _description, _help)
        return cmd
    return wrapper